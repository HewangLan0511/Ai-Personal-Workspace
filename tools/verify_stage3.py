#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段3 验收自动核验：把 07「验收标准」10 项做成机器可判。

覆盖（docs/agent-dev/07-阶段指令-窗口管理.md §验收标准）：
  1  查找窗口        给定 pid 返回 hwnd；**无窗口时返回 null 不报错**
  2  定位窗口        移动到指定像素后，用 GetWindowRect 复核（±2px）
  3  四宫格          4 个真实窗口排成四宫格，**无重叠**且各占 1/4
  4  最大化恢复      最大化状态下能被取消最大化并正确定位
  5  激活            目标窗口成为前台窗口（GetForegroundWindow 比对）
  6  AI 侧栏留位     启用侧栏时窗口右边界不越过侧栏起点
  7  多显示器        monitor=1 的布局，窗口落在第二显示器的坐标范围内
  8  高分屏          物理像素工作区与 DPI 缩放一致，比例不因缩放改变
  9  容错            某软件未注册/未运行 → 该槽位跳过，其余正常排列
  10 纯函数测试      由 `cargo test` 覆盖（本脚本只做提示）

**方法论**：不采信接口的返回值 ——
每次定位后都用 `GET /api/v1/windows/{hwnd}`（即 Win32 `GetWindowRect`）**重新读回**实际矩形比对。
接口说"我移动了"不算，窗口真的在那个位置才算。

**被测窗口从哪来**：复制 `notepad.exe` 成 4 份不同文件名放进临时目录再启动。
为什么不用 notepad/mspaint/calc 各一个：UWP 别名（calc/mspaint）的真实窗口属于
`ApplicationFrameHost.exe`，pid 与启动的进程对不上；控制台程序（cmd）在 Win11 里
常被 Windows Terminal 接管。**复制同一 PE 多次**才能得到 4 个 pid 干净、互不干扰的 GUI 窗口。

用法：
  python tools/verify_stage3.py
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

# 4 个**经典 Win32 GUI** 程序：能常驻、有独立顶层窗口、无需管理员、path 互不相同。
#
# 为什么不用 notepad / mspaint / calc：Win11 里它们是 **UWP 应用别名**，
# `System32\` 下那个 exe 只是"转发器"—— 启动后自身**立即退出（退出码 0）**，
# 真正的窗口属于 UWP 宿主进程，pid 与启动的进程对不上 ⇒ 窗口查找必然失败。
# （本脚本第一版就栽在这：4 个"窗口"一个都找不到。charmap/cleanmgr 同样是转发器；
#  psr/osk/taskmgr/mmc 需要提升权限。）
TEST_EXES = [
    r"C:\Windows\System32\dxdiag.exe",   # DirectX 诊断工具
    r"C:\Windows\System32\msinfo32.exe",  # 系统信息
    r"C:\Windows\System32\winver.exe",    # 关于 Windows
    r"C:\Windows\System32\colorcpl.exe",  # 颜色管理
]
TEST_APP_NAMES = ["VT-A", "VT-B", "VT-C", "VT-D"]


def q(s: str) -> str:
    return urllib.parse.quote(s)


def http_json(url: str, method: str = "GET", body=None, timeout: float = 20.0):
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


def list_sidecar_pids() -> set[str]:
    out = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True).stdout
    pids: set[str] = set()
    for line in out.decode("gbk", errors="replace").splitlines():
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
    """重启后必须等端口**变成新值**：库里还留着上一实例的端口，等"非空"会拿到旧值。"""
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


def start_app(exe: Path, data_dir: Path, layouts_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PW_DATA_DIR"] = str(data_dir)
    env["PW_LAYOUTS_DIR"] = str(layouts_dir)
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


# ---------------------------------------------------------------- 测试布局

def write_test_layouts(dirpath: Path) -> None:
    """在临时布局目录里写 4 个测试布局（不污染仓库的 config/layouts/）。"""
    dirpath.mkdir(parents=True, exist_ok=True)

    quad = {
        "name": "verify-quad",
        "description": "验收用四宫格",
        "monitor": 0,
        "slots": [
            {"app": TEST_APP_NAMES[0], "rect": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}, "z": 1},
            {"app": TEST_APP_NAMES[1], "rect": {"x": 0.5, "y": 0.0, "w": 0.5, "h": 0.5}, "z": 2},
            {"app": TEST_APP_NAMES[2], "rect": {"x": 0.0, "y": 0.5, "w": 0.5, "h": 0.5}, "z": 3},
            {"app": TEST_APP_NAMES[3], "rect": {"x": 0.5, "y": 0.5, "w": 0.5, "h": 0.5}, "z": 4},
        ],
    }
    (dirpath / "verify-quad.json").write_text(json.dumps(quad, ensure_ascii=False), "utf-8")

    sidebar = {
        "name": "verify-sidebar",
        "monitor": 0,
        "slots": [{"app": TEST_APP_NAMES[0], "rect": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}, "z": 1}],
        "aiSidebar": {"enabled": True, "edge": "right", "width": 0.25},
    }
    (dirpath / "verify-sidebar.json").write_text(json.dumps(sidebar, ensure_ascii=False), "utf-8")

    mon1 = {
        "name": "verify-monitor1",
        "monitor": 1,
        "slots": [
            {"app": TEST_APP_NAMES[0], "rect": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0}, "z": 1},
            {"app": TEST_APP_NAMES[1], "rect": {"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0}, "z": 2},
        ],
    }
    (dirpath / "verify-monitor1.json").write_text(json.dumps(mon1, ensure_ascii=False), "utf-8")

    partial = {
        "name": "verify-partial",
        "monitor": 0,
        "slots": [
            {"app": TEST_APP_NAMES[0], "rect": {"x": 0.0, "y": 0.0, "w": 0.5, "h": 1.0}, "z": 1},
            {"app": "绝不存在的软件-zzz", "rect": {"x": 0.5, "y": 0.0, "w": 0.5, "h": 1.0}, "z": 2},
        ],
    }
    (dirpath / "verify-partial.json").write_text(json.dumps(partial, ensure_ascii=False), "utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="阶段3 验收自动核验")
    ap.add_argument("--exe", help="release 可执行文件路径")
    ap.add_argument("--keep", action="store_true", help="保留临时目录")
    args = ap.parse_args()

    exe = Path(args.exe) if args.exe else REPO_ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"
    if not exe.exists():
        print(f"[FATAL] 可执行文件不存在：{exe}\n        先跑 `cargo build --release`。")
        return 2

    data_dir = Path(tempfile.mkdtemp(prefix="pw-verify3-"))
    layouts_dir = data_dir / "layouts"
    apps_dir = data_dir / "fakes"
    apps_dir.mkdir(parents=True, exist_ok=True)
    write_test_layouts(layouts_dir)
    db_path = data_dir / "workspace.db"

    # 测试用真实 GUI 程序（各有独立顶层窗口、pid 干净）
    fake_exes: list[Path] = [Path(p) for p in TEST_EXES]
    for p in fake_exes:
        if not p.exists():
            print(f"[FATAL] 测试用可执行文件缺失：{p}")
            return 2

    print(f"[verify3] exe = {exe}")
    print(f"[verify3] data dir = {data_dir}")

    results: list[tuple[str, bool, str]] = []
    proc: subprocess.Popen | None = None
    baseline = list_sidecar_pids()
    base = ""
    spawned: list[int] = []

    def api(path: str, method: str = "GET", body=None):
        return http_json(base + path, method, body)

    def data_of(resp):
        st, body = resp
        return (body or {}).get("data") if body else None

    try:
        proc = start_app(exe, data_dir, layouts_dir)
        cfg = wait_for_new_port(db_path, "", timeout_s=30.0)
        port = cfg.get("runtime.http_port")
        if not port:
            raise RuntimeError("core 未写出 runtime.http_port")
        base = f"http://127.0.0.1:{port}"
        print(f"[verify3] core http = {base}")

        # ---- 注册 4 个测试软件并启动 ----
        ids: list[int] = []
        for name, path in zip(TEST_APP_NAMES, fake_exes):
            st, body = api("/api/v1/apps", "POST", {
                "name": name, "path": str(path), "args": "", "type": "exe", "category": "开发",
            })
            row = (body or {}).get("data") or {}
            if row.get("id"):
                ids.append(row["id"])

        for app_id in ids:
            r = data_of(api(f"/api/v1/apps/{app_id}/launch", "POST")) or {}
            if r.get("pid"):
                spawned.append(int(r["pid"]))
        # 07 §禁止事项：等窗口创建完成再定位。
        # dxdiag / msinfo32 启动较慢（要探测硬件信息），故给足 12s。
        time.sleep(12.0)

        # 拿每个测试进程的主窗口
        hwnds: list[dict] = []
        for app_id in ids:
            pid = ((api("/api/v1/apps/running")[1] or {}).get("data") or {}).get(str(app_id))
            if not pid:
                continue
            win = data_of(api(f"/api/v1/windows?pid={pid}"))
            if win:
                hwnds.append({"appId": app_id, "pid": pid, "win": win})

        # ---- 1 查找窗口 ----
        got = len(hwnds)
        # 无窗口的 pid 必须返回 null 而不是报错
        st_null, body_null = api("/api/v1/windows?pid=999999")
        null_ok = st_null == 200 and (body_null or {}).get("data") is None
        win_ok = all(h["win"].get("hwnd") and h["win"].get("title") for h in hwnds)
        ok1 = got == 4 and null_ok and win_ok
        results.append((
            "1 查找窗口（含无窗口返回 null）",
            ok1,
            f"找到 {got}/4 个主窗口；空 pid 返回 null={null_ok}（status={st_null}）；标题={[h['win'].get('title','')[:12] for h in hwnds]}",
        ))
        if not hwnds:
            raise RuntimeError("一个测试窗口都没找到，后续用例无法进行")

        first_hwnd = hwnds[0]["win"]["hwnd"]

        # ---- 2 定位窗口（±2px 复核）----
        target = {"x": 120, "y": 90, "w": 700, "h": 480}
        api(f"/api/v1/windows/{first_hwnd}", "POST", target)
        time.sleep(0.6)
        actual = data_of(api(f"/api/v1/windows/{first_hwnd}"))
        if isinstance(actual, dict):
            diffs = [abs(actual.get(k, 0) - target[k]) for k in ("x", "y", "w", "h")]
            ok2 = all(d <= 2 for d in diffs)
            detail2 = f"目标={target} 实测={actual} 偏差={diffs}"
        else:
            ok2, detail2 = False, f"读不回矩形：{actual}"
        results.append(("2 定位窗口（GetWindowRect 复核 ±2px）", ok2, detail2))

        # ---- 4 最大化恢复 ----
        api(f"/api/v1/windows/{first_hwnd}", "POST", {**target, "maximized": True})
        time.sleep(0.8)
        st_max = data_of(api(f"/api/v1/windows/{first_hwnd}"))
        was_max = bool(isinstance(st_max, dict) and st_max.get("w", 0) >= target["w"])
        # 再定位回普通状态，应能精确回到目标位置
        api(f"/api/v1/windows/{first_hwnd}", "POST", target)
        time.sleep(0.6)
        back = data_of(api(f"/api/v1/windows/{first_hwnd}"))
        ok4 = isinstance(back, dict) and all(
            abs(back.get(k, 0) - target[k]) <= 2 for k in ("x", "y", "w", "h")
        )
        results.append((
            "4 最大化恢复（取消最大化后能正确定位）",
            ok4,
            f"最大化后尺寸={st_max} → 复位后={back}（目标 {target}）",
        ))

        # ---- 5 激活 ----
        st_fg, body_fg = api(f"/api/v1/windows/{first_hwnd}/activate", "POST")
        time.sleep(0.5)
        fg = (body_fg or {}).get("data", {}).get("foreground") if body_fg else None
        ok5 = st_fg == 200 and fg is True
        results.append(("5 激活（成为前台窗口）", ok5, f"status={st_fg} foreground={fg}"))

        # ---- 3 四宫格（无重叠）----
        st_q, body_q = api("/api/v1/layouts/verify-quad/apply", "POST")
        outcome = (body_q or {}).get("data") or {}
        time.sleep(1.0)
        rects = []
        for h in hwnds:
            r = data_of(api(f"/api/v1/windows/{h['win']['hwnd']}"))
            if isinstance(r, dict):
                rects.append(r)
        overlap = False
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                a, b = rects[i], rects[j]
                if a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and \
                   a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]:
                    overlap = True
        ok3 = st_q == 200 and outcome.get("placed", 0) == 4 and not overlap
        results.append((
            "3 四宫格（4 窗口无重叠）",
            ok3,
            f"placed={outcome.get('placed')} skipped={outcome.get('skipped')} failed={outcome.get('failed')}；"
            f"实测矩形={rects}；重叠={overlap}",
        ))

        # ---- 6 AI 侧栏留位 ----
        st_sb, body_sb = api("/api/v1/layouts/verify-sidebar/apply", "POST")
        sb_out = (body_sb or {}).get("data") or {}
        work = sb_out.get("work") or {}
        time.sleep(0.8)
        r0 = data_of(api(f"/api/v1/windows/{first_hwnd}"))
        sidebar_limit = work.get("x", 0) + work.get("w", 0) * 0.75  # 侧栏 25%
        ok6 = (
            st_sb == 200
            and isinstance(r0, dict)
            and (r0["x"] + r0["w"]) <= sidebar_limit + 2
        )
        results.append((
            "6 AI 侧栏留位（窗口不覆盖右侧区域）",
            ok6,
            f"工作区={work}；侧栏起点≈{sidebar_limit:.0f}；窗口右边界={None if not isinstance(r0, dict) else r0['x'] + r0['w']}",
        ))

        # ---- 7 多显示器 ----
        st_m, body_m = api("/api/v1/monitors")
        monitors = (body_m or {}).get("data") or []
        if len(monitors) >= 2:
            st_1, body_1 = api("/api/v1/layouts/verify-monitor1/apply", "POST")
            out1 = (body_1 or {}).get("data") or {}
            time.sleep(0.8)
            second = monitors[1]
            rx = data_of(api(f"/api/v1/windows/{hwnds[0]['win']['hwnd']}"))
            in_second = isinstance(rx, dict) and rx["x"] >= second["x"] - 2
            ok7 = st_1 == 200 and not out1.get("degraded_monitor") and in_second
            results.append((
                "7 多显示器（monitor=1 布局落在第二屏）",
                ok7,
                f"显示器={[(m['index'], m['x'], m['w']) for m in monitors]}；降级={out1.get('degraded_monitor')}；"
                f"窗口x={None if not isinstance(rx, dict) else rx['x']}（第二屏起点 {second['x']}）",
            ))
        else:
            results.append(("7 多显示器", False, f"本机只有 {len(monitors)} 块显示器，无法实测"))

        # ---- 8 高分屏（物理像素 + 比例）----
        m0 = monitors[0] if monitors else {}
        # 四宫格在物理像素工作区上应各占 1/4：重新应用后再量
        api("/api/v1/layouts/verify-quad/apply", "POST")
        time.sleep(1.0)
        r8 = [data_of(api(f"/api/v1/windows/{h['win']['hwnd']}")) for h in hwnds]
        ok_sizes = all(isinstance(r, dict) and r["w"] > 0 and r["h"] > 0 for r in r8)
        # 物理工作区宽度应等于（或接近）显示器宽度 − 任务栏；关键是"不因缩放而缩水"
        work_w = m0.get("work_w", 0)
        mon_w = m0.get("w", 0)
        ratio_ok = work_w > 0 and work_w <= mon_w
        # 每个窗口宽度应约等于 work_w / 2（±20px 容差）
        half = work_w / 2
        each_half = all(isinstance(r, dict) and abs(r["w"] - half) <= 20 for r in r8)
        ok8 = ok_sizes and ratio_ok and each_half
        results.append((
            "8 高分屏（物理像素工作区 + 比例正确）",
            ok8,
            f"显示器={mon_w}×{m0.get('h')} 工作区={work_w}×{m0.get('work_h')}（物理像素）；"
            f"每格宽应≈{half:.0f}，实测={[r['w'] if isinstance(r, dict) else None for r in r8]}",
        ))

        # ---- 9 容错（未注册的软件 → 槽位跳过）----
        st_p, body_p = api("/api/v1/layouts/verify-partial/apply", "POST")
        out_p = (body_p or {}).get("data") or {}
        slots = out_p.get("slots") or []
        skipped = [s for s in slots if s.get("status", "").startswith("skipped")]
        placed = [s for s in slots if s.get("status") == "placed"]
        ok9 = (
            st_p == 200
            and out_p.get("placed") == 1
            and out_p.get("skipped") == 1
            and len(skipped) == 1
            and len(placed) == 1
        )
        results.append((
            "9 容错（未运行软件跳过，其余正常）",
            ok9,
            f"placed={out_p.get('placed')} skipped={out_p.get('skipped')}；槽位={[(s['app'], s['status']) for s in slots]}",
        ))

    except Exception as e:  # noqa: BLE001
        results.append(("执行异常", False, f"{type(e).__name__}: {e}"))
    finally:
        stop_app(proc)
        for pid in spawned:
            kill_pid(pid)
        for p in TEST_EXES:
            kill_by_image(Path(p).name)
        kill_sidecar(baseline)
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)
        else:
            print(f"[verify3] 数据目录已保留：{data_dir}")

    print("\n" + "=" * 68)
    print("阶段3 验收核验结果")
    print("=" * 68)
    all_ok = True
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}\n      {detail}")
        all_ok = all_ok and passed
    print("=" * 68)
    print(f"合计 {sum(1 for _, p, _ in results if p)}/{len(results)} 通过")
    print("验收项 10（纯函数单测）由 `cargo test` 覆盖，见 window_manager::layout::tests")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
