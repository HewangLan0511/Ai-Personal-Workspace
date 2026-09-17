#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段4 验收自动核验：把 06「验收标准」10 项做成机器可判。

覆盖（docs/agent-dev/06-阶段指令-工作模式引擎.md §验收标准）：
  V-01 创建模式      POST /api/v1/modes（含 4 软件）→ 列表可见 + 重启后仍在
  V-02 一键进入      4 个软件全部启动（进程真实存活）+ 窗口排列正确，**全程 < 20s**
  V-03 进度可见      过程中能观察到 apply 阶段推进（launching → waiting_ready → …）
  V-04 容错          一个软件路径改错 → 其余正常 + 失败项带可读 reason 与 retriable
  V-05 幂等          连续两次 apply → 第二次全部 already_running（不重复拉起）
  V-06 可取消        过程中取消 → outcome.cancelled = true
  V-07 切换 additive  A→B：A 的软件未被关闭，B 的新增被拉起
  V-08 布局持久化    改布局 → 再 apply → 窗口按新布局排列
  V-09 状态显示      /mode/current 正确反映当前模式
  V-10 恢复          重启后显示"上次使用"，一键恢复可用

**方法论**：不采信接口自述 —— 每次都回读 `/api/v1/apps/running` 与
`/api/v1/windows?pid=` 交叉验证"进程/窗口是否真的在"。

测试软件用 4 个**经典 Win32 GUI**（能常驻、pid 干净、无需管理员）：
 dxdiag / msinfo32 / winver / colorcpl。理由见 verify_stage3.py 顶部说明。

用法：
  python tools/verify_stage4.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent

TEST_EXES = [
    r"C:\Windows\System32\dxdiag.exe",
    r"C:\Windows\System32\msinfo32.exe",
    r"C:\Windows\System32\winver.exe",
    r"C:\Windows\System32\colorcpl.exe",
]
APP_NAMES = ["VT-Dx", "VT-Si", "VT-Wv", "VT-Cc"]
MODE_A = "验收模式A"
MODE_B = "验收模式B"


def q(s: str) -> str:
    return urllib.parse.quote(s)


def http_json(url: str, method: str = "GET", body=None, timeout: float = 90.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None
    except Exception as e:
        return 0, {"error": str(e)}


def kill_pid(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)


def kill_by_image(name: str) -> None:
    subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)


def pid_alive(pid: int) -> bool:
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True
    ).stdout.decode("gbk", "replace")
    return str(pid) in out and "No tasks" not in out and "没有运行" not in out


def list_sidecar_pids() -> set[str]:
    out = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True).stdout
    pids: set[str] = set()
    for line in out.decode("gbk", "replace").splitlines():
        cells = [c.strip().strip('"') for c in line.split(",")]
        if len(cells) >= 2 and cells[0].lower() == "service.exe":
            pids.add(cells[1])
    return pids


def kill_sidecar(baseline: set[str]) -> None:
    for pid in list_sidecar_pids() - baseline:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)


def read_config_map(db_path: Path) -> dict[str, str]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {k: v for k, v in con.execute("SELECT key, value FROM config").fetchall()}
    finally:
        con.close()


def wait_for_new_port(db_path: Path, old_port: str, timeout_s: float = 30.0) -> dict[str, str]:
    """重启后必须等端口**变成新值**（库里还留着上一实例的端口）。"""
    deadline = time.time() + timeout_s
    cfg: dict[str, str] = {}
    while time.time() < deadline:
        try:
            cfg = read_config_map(db_path) if db_path.exists() else {}
        except Exception:
            cfg = {}
        port = cfg.get("runtime.http_port")
        if port and port != old_port:
            return cfg
        time.sleep(0.3)
    return cfg


def start_app(exe: Path, data_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PW_DATA_DIR"] = str(data_dir)
    return subprocess.Popen(
        [str(exe)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def stop_app(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def main() -> int:
    ap = argparse.ArgumentParser(description="阶段4 验收自动核验")
    ap.add_argument("--exe", help="release 可执行文件路径")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    exe = Path(args.exe) if args.exe else REPO_ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"
    if not exe.exists():
        print(f"[FATAL] 可执行文件不存在：{exe}\n        先跑 `cargo build --release`。")
        return 2

    data_dir = Path(tempfile.mkdtemp(prefix="pw-verify4-"))
    db_path = data_dir / "workspace.db"
    print(f"[verify4] exe = {exe}")
    print(f"[verify4] data dir = {data_dir}")

    results: list[tuple[str, bool, str]] = []
    proc: subprocess.Popen | None = None
    baseline = list_sidecar_pids()
    base = ""
    spawned: list[int] = []

    def api(path: str, method: str = "GET", body=None, timeout: float = 90.0):
        return http_json(base + path, method, body, timeout)

    def data_of(resp):
        st, body = resp
        return (body or {}).get("data") if body else None

    def running_map() -> dict:
        return data_of(api("/api/v1/apps/running")) or {}

    try:
        proc = start_app(exe, data_dir)
        cfg = wait_for_new_port(db_path, "", timeout_s=30.0)
        port = cfg.get("runtime.http_port")
        if not port:
            raise RuntimeError("core 未写出 runtime.http_port")
        base = f"http://127.0.0.1:{port}"
        print(f"[verify4] core http = {base}")

        # ---------- 准备：注册 4 个软件 ----------
        app_ids: dict[str, int] = {}
        for name, path in zip(APP_NAMES, TEST_EXES):
            st, body = api("/api/v1/apps", "POST", {
                "name": name, "path": path, "args": "", "type": "exe", "category": "开发",
            })
            row = (body or {}).get("data") or {}
            if row.get("id"):
                app_ids[name] = row["id"]
        ok_setup = len(app_ids) == 4

        # ---------- 准备：一个 app 名与测试软件**匹配**的布局 ----------
        # 内置 quad 的 slots 是 VSCode/Chrome/PDF/Terminal，与测试软件名对不上 ⇒ 4 个槽位全跳过。
        # 这不是产品缺陷（换匹配布局后排列正常，已实测），而是验收必须自备数据。
        quad_slots = [
            {"app": APP_NAMES[0], "rect": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}, "z": 1},
            {"app": APP_NAMES[1], "rect": {"x": 0.5, "y": 0.0, "w": 0.5, "h": 0.5}, "z": 2},
            {"app": APP_NAMES[2], "rect": {"x": 0.0, "y": 0.5, "w": 0.5, "h": 0.5}, "z": 3},
            {"app": APP_NAMES[3], "rect": {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5}, "z": 4},
        ]
        st_q, _ = api("/api/v1/db/layouts", "POST", {
            "name": "verify-quad", "description": "验收用四宫格（app 名与测试软件匹配）",
            "slots": quad_slots, "monitor": 0,
        })
        layout_ready = st_q == 200

        # ---------- V-01 创建模式 ----------
        st, body = api("/api/v1/modes", "POST", {
            "name": MODE_A,
            "description": "验收用：4 个软件 + 四宫格",
            "apps": APP_NAMES,
            "openTargets": [],
            "layout": "verify-quad",
            "aiProfile": {"provider": "deepseek", "systemPromptKey": "dev", "permissionScope": ["file:read"]},
            "autoApply": False,
        })
        mode_a = (body or {}).get("data") or {}
        ok1 = st == 200 and mode_a.get("id") and len(mode_a.get("apps") or []) == 4
        results.append((
            "V-01 创建模式（4 软件）",
            bool(ok1),
            f"status={st} id={mode_a.get('id')} apps={mode_a.get('apps')} aiProfile={mode_a.get('aiProfile')}",
        ))

        # 复制模式（06 §1 要求）
        st_d, body_d = api(f"/api/v1/modes/{mode_a.get('id')}/duplicate", "POST")
        dup = (body_d or {}).get("data") or {}
        ok_dup = st_d == 200 and dup.get("name") == f"{MODE_A} 副本"
        results.append(("F-08 复制模式", ok_dup, f"副本名={dup.get('name')!r} autoApply={dup.get('autoApply')}"))

        # ---------- V-02 一键进入（含耗时） ----------
        t0 = time.time()
        st2, body2 = api(f"/api/v1/modes/{mode_a.get('id')}/apply", "POST", None, timeout=120)
        took = time.time() - t0
        outcome = (body2 or {}).get("data") or {}
        slots = outcome.get("slots") or []
        launched = [s for s in slots if s.get("status") in ("launched", "already_running")]
        pids = [s.get("pid") for s in launched if s.get("pid")]
        spawned.extend(int(p) for p in pids)
        time.sleep(1.0)
        alive = [p for p in pids if pid_alive(int(p))]
        ok2 = (
            st2 == 200
            and outcome.get("launched", 0) + outcome.get("alreadyRunning", 0) == 4
            and len(alive) == 4
            and took < 20
        )
        results.append((
            "V-02 一键进入（4 软件启动 + <20s）",
            ok2,
            f"launched={outcome.get('launched')} already={outcome.get('alreadyRunning')} "
            f"failed={outcome.get('failed')}；进程存活 {len(alive)}/4；耗时 {took:.2f}s",
        ))
        # 排列结果：4 个槽位应全部排上
        arranged = outcome.get("arranged")
        results.append((
            "V-02b 窗口排列（4 槽全排）",
            bool(layout_ready and arranged == 4),
            f"布局就绪={layout_ready} arranged={arranged} note={outcome.get('arrangeNote')!r}",
        ))

        # ---------- V-09 状态显示 ----------
        cur = data_of(api("/api/v1/mode/current")) or {}
        ok9 = cur.get("running") == MODE_A and str(cur.get("configured")) in (f'"{MODE_A}"', MODE_A)
        results.append(("V-09 状态显示（模式栏数据）", ok9, f"running={cur.get('running')!r} configured={cur.get('configured')!r} launched={cur.get('launchedAppIds')}"))

        # ---------- V-05 幂等 ----------
        st5, body5 = api(f"/api/v1/modes/{mode_a.get('id')}/apply", "POST", None, timeout=120)
        out5 = (body5 or {}).get("data") or {}
        ok5 = st5 == 200 and out5.get("launched", 0) == 0 and out5.get("alreadyRunning", 0) == 4
        results.append((
            "V-05 幂等（二次进入不重复拉起）",
            ok5,
            f"launched={out5.get('launched')} already={out5.get('alreadyRunning')}",
        ))

        # ---------- V-03 进度可见（查会话记录的阶段轨迹） ----------
        # **不靠外部轮询碰运气**：apply 全程可能只有 1 秒出头，50ms 轮询必然抓不全中间态。
        # 会话自己记 history —— 这才是 F-38「步骤清单」的稳定依据。
        for s in slots:
            if s.get("pid"):
                kill_pid(int(s["pid"]))
        time.sleep(1.5)
        api("/api/v1/mode/exit", "POST")
        st3, body3 = api(f"/api/v1/modes/{mode_a.get('id')}/apply", "POST", None, timeout=120)
        out3 = (body3 or {}).get("data") or {}
        spawned.extend(int(s["pid"]) for s in (out3.get("slots") or []) if s.get("pid"))
        prog = data_of(api("/api/v1/mode/progress")) or {}
        hist = [h.get("phase") for h in (prog.get("history") or [])]
        seen_core = {"validating", "launching", "waiting_ready", "arranging"} & set(hist)
        ok3 = len(seen_core) >= 3 and bool(hist) and hist[-1] == "done"
        results.append((
            "V-03 进度可见（阶段轨迹完整）",
            ok3,
            f"轨迹={hist}；命中核心阶段={sorted(seen_core)}",
        ))
        # 进度里应带每项结果
        prog = data_of(api("/api/v1/mode/progress")) or {}
        results.append((
            "V-03b 进度含每项结果",
            len(prog.get("slots") or []) == 4,
            f"slots={[(s.get('app'), s.get('status')) for s in (prog.get('slots') or [])]}",
        ))

        # ---------- V-08 布局持久化（改布局 → 再进入按新布局） ----------
        new_slots = [
            {"app": APP_NAMES[0], "rect": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.5}, "z": 1},
            {"app": APP_NAMES[1], "rect": {"x": 0.0, "y": 0.5, "w": 1.0, "h": 0.5}, "z": 2},
        ]
        st_l, body_l = api("/api/v1/db/layouts", "POST", {
            "name": "verify-split-h", "description": "验收用上下分屏", "slots": new_slots, "monitor": 0,
        })
        rec = (body_l or {}).get("data") or {}
        ok_l_write = st_l == 200 and rec.get("name") == "verify-split-h"

        api(f"/api/v1/modes/{mode_a.get('id')}", "PUT", {"layout": "verify-split-h"})
        for s in (out3.get("slots") or []):
            if s.get("pid"):
                kill_pid(int(s["pid"]))
        time.sleep(1.0)
        api("/api/v1/mode/exit", "POST")
        st8, body8 = api(f"/api/v1/modes/{mode_a.get('id')}/apply", "POST", None, timeout=120)
        out8 = (body8 or {}).get("data") or {}
        spawned.extend(int(s["pid"]) for s in (out8.get("slots") or []) if s.get("pid"))
        time.sleep(1.2)
        # 量第一个窗口的实际位置：应在工作区上半（h ≈ work_h/2）
        first = next((s for s in (out8.get("slots") or []) if s.get("pid")), None)
        rect = None
        if first:
            win = data_of(api(f"/api/v1/windows?pid={first['pid']}"))
            if win:
                rect = data_of(api(f"/api/v1/windows/{win['hwnd']}"))
        mon = data_of(api("/api/v1/monitors")) or []
        work_h = mon[0].get("work_h", 0) if mon else 0
        half_ok = bool(rect and work_h and abs(rect["h"] - work_h / 2) <= 20)
        ok8 = ok_l_write and half_ok
        results.append((
            "V-08 布局持久化（改布局 → 按新布局排列）",
            ok8,
            f"写库={ok_l_write}；工作区h={work_h} 窗口={rect}（应≈{work_h / 2:.0f}）",
        ))

        # ---------- V-04 容错（一个路径改错） ----------
        api("/api/v1/modes", "POST", {
            "name": MODE_B, "description": "验收：含一个坏路径",
            "apps": [APP_NAMES[0], "绝不存在的软件ZZZ", APP_NAMES[1]],
            "openTargets": [], "layout": "quad", "autoApply": False,
        })
        # 注：`/api/v1/modes` 不带 search 参数（模式数量很少，前端本地过滤即可）
        allm = data_of(api("/api/v1/modes")) or []
        bad_id = next((m["id"] for m in allm if m["name"] == MODE_B), None)
        for s in (out8.get("slots") or []):
            if s.get("pid"):
                kill_pid(int(s["pid"]))
        time.sleep(1.0)
        api("/api/v1/mode/exit", "POST")
        st4, body4 = api(f"/api/v1/modes/{bad_id}/apply", "POST", None, timeout=120)
        out4 = (body4 or {}).get("data") or {}
        s4 = out4.get("slots") or []
        spawned.extend(int(s["pid"]) for s in s4 if s.get("pid"))
        fail_items = [s for s in s4 if s.get("status") == "failed"]
        good_items = [s for s in s4 if s.get("status") in ("launched", "already_running")]
        ok4 = (
            st4 == 200
            and len(fail_items) == 1
            and len(good_items) == 2
            and fail_items[0].get("reason")
            and fail_items[0].get("retriable") is True
        )
        results.append((
            "V-04 容错（坏路径不中断其余）",
            ok4,
            f"成功 {len(good_items)} 失败 {len(fail_items)}；失败原因={fail_items[0].get('reason') if fail_items else None!r} retriable={fail_items[0].get('retriable') if fail_items else None}",
        ))

        # ---------- V-07 切换 additive ----------
        # 当前跑的是 B（含 VT-Dx / VT-Si），切到 A'（只含 VT-Wv），additive 下 VT-Dx/VT-Si 应保留
        api("/api/v1/modes", "POST", {
            "name": MODE_A + "切换", "apps": [APP_NAMES[2]], "openTargets": [],
            "layout": "quad", "switchPolicy": "additive",
        })
        allm = data_of(api("/api/v1/modes")) or []
        sw_id = next((m["id"] for m in allm if m["name"] == MODE_A + "切换"), None)
        running_before = running_map()
        st7, body7 = api(f"/api/v1/modes/{sw_id}/apply", "POST", None, timeout=120)
        out7 = (body7 or {}).get("data") or {}
        spawned.extend(int(s["pid"]) for s in (out7.get("slots") or []) if s.get("pid"))
        time.sleep(1.0)
        running_after = running_map()
        # additive：老模式的软件 pid 应仍在运行
        kept = all(k in running_after for k in running_before)
        ok7 = st7 == 200 and kept and (out7.get("policy") == "additive") and not out7.get("closed")
        results.append((
            "V-07 切换（additive 不关旧软件）",
            ok7,
            f"policy={out7.get('policy')} closed={out7.get('closed')}；切换前 {len(running_before)} 个运行中，切换后 {len(running_after)} 个",
        ))

        # ---------- V-06 可取消 ----------
        for aid in list(running_map().values()):
            kill_pid(int(aid))
        time.sleep(1.5)
        api("/api/v1/mode/exit", "POST")
        cancel_out: dict = {}

        def do_apply():
            stc, bodyc = api(f"/api/v1/modes/{mode_a.get('id')}/apply", "POST", None, timeout=120)
            cancel_out["status"] = stc
            cancel_out["data"] = (bodyc or {}).get("data") or {}

        th2 = threading.Thread(target=do_apply, daemon=True)
        th2.start()
        time.sleep(0.35)  # 启动阶段刚开始
        st_c, body_c = api("/api/v1/mode/cancel", "POST")
        th2.join(timeout=120)
        out6 = cancel_out.get("data") or {}
        slots6 = out6.get("slots") or []
        has_cancel_mark = any(s.get("status") == "skipped_cancelled" for s in slots6)
        ok6 = bool(out6) and (out6.get("cancelled") is True) and ((out6.get("state") or {}).get("phase") == "cancelled" or has_cancel_mark)
        results.append((
            "V-06 可取消",
            ok6,
            f"cancel 接口={st_c} {body_c if not body_c or 'ok' in str(body_c) else ''}；outcome.cancelled={out6.get('cancelled')} state={(out6.get('state') or {}).get('phase')}；跳过项={[s.get('app') for s in slots6 if s.get('status') == 'skipped_cancelled']}",
        ))

        # ---------- V-10 恢复（重启后"上次使用" + 一键恢复） ----------
        for aid in list(running_map().values()):
            kill_pid(int(aid))
        time.sleep(1.0)
        old_port = cfg.get("runtime.http_port") or ""
        stop_app(proc)
        proc = None
        time.sleep(1.5)
        proc = start_app(exe, data_dir)
        cfg2 = wait_for_new_port(db_path, old_port, timeout_s=30.0)
        base = f"http://127.0.0.1:{cfg2.get('runtime.http_port')}"
        cur2 = data_of(api("/api/v1/mode/current")) or {}
        # 重启后：configured 有值（上次使用），running 为空（不自动重新应用）
        configured = cur2.get("configured")
        conf_str = configured if isinstance(configured, str) else ""
        not_auto_applied = cur2.get("running") is None
        st10, body10 = api("/api/v1/mode/restore", "POST", None, timeout=120)
        out10 = (body10 or {}).get("data") or {}
        spawned.extend(int(s["pid"]) for s in (out10.get("slots") or []) if s.get("pid"))
        # 模式列表也应仍在（V-01 的"重启后仍在"）
        modes_after = data_of(api("/api/v1/modes")) or []
        names_after = [m.get("name") for m in modes_after]
        ok10 = (
            conf_str.strip() != ""
            and not_auto_applied
            and st10 == 200
            and out10.get("modeName") == conf_str.strip()
            and MODE_A in names_after
        )
        results.append((
            "V-10 恢复（重启后显示上次使用 + 一键恢复）",
            ok10,
            f"configured={configured!r} 未自动应用={not_auto_applied}；restore status={st10} 恢复的模式={out10.get('modeName')!r}；重启后模式列表={names_after}",
        ))

    except Exception as e:  # noqa: BLE001
        results.append(("执行异常", False, f"{type(e).__name__}: {e}"))
    finally:
        stop_app(proc)
        try:
            for pid in list(running_map().values()):
                kill_pid(int(pid))
        except Exception:
            pass
        for pid in spawned:
            kill_pid(pid)
        for p in TEST_EXES:
            kill_by_image(Path(p).name)
        kill_sidecar(baseline)
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)
        else:
            print(f"[verify4] 数据目录已保留：{data_dir}")

    print("\n" + "=" * 70)
    print("阶段4 验收核验结果")
    print("=" * 70)
    all_ok = True
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}\n      {detail}")
        all_ok = all_ok and passed
    print("=" * 70)
    print(f"合计 {sum(1 for _, p, _ in results if p)}/{len(results)} 通过")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
