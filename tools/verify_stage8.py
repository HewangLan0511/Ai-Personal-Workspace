#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段8 验收自动核验：把 11「验收标准」8 项做成机器可判。

覆盖（docs/agent-dev/11-阶段指令-生活与设备.md §验收标准）：

| # | 验收项 | 本脚本怎么判 |
|---|--------|--------------|
| 1 | 天气 | `PW_WEATHER_FAKE=1`：设城市 → 返回 mock（来源显式标注）；**未设城市 → no_city（绝不自动定位）**；连续两次请求一致（缓存路径无异常） |
| 2 | 音乐 | `/life/media` 200 且含 available 字段；winsdk 不可用 → `available:false` 优雅降级（真实播放人工核对） |
| 3 | 消息概览 | 添加 demo 服务 → overview 返回未读数；**全库无消息正文**（断言无 message/chat 类表与列） |
| 4 | 使用时间 | 采样间隔设 1s → 等待 ≥6s → `/life/usage/today` 出现前台条目且总量 > 0 |
| 5 | 隐私 | sqlite_master 全表扫描：usage_stats 只有 (day,app_name,seconds) 聚合列；无任何消息内容表 |
| 6 | 设备指标 | cpu∈[0,100]、mem_total>0、disks 非空；history 随时间推进（环形缓冲活着）；psutil 可用时内存对照 |
| 7 | 进程管理 | 进程列表非空且含 core 自身；kill：confirm=false → 400，confirm=true → 受控子进程真实退出 |
| 8 | 插件形态 | 如实判据：核心模块存在（modules/life+device）+ README 声明阶段9 迁移口径 + core 无插件特判（`plugin_id ==` 零命中） |

## 边界如实声明（红线 V6）

 - **真实天气 API**：crates.io 在本机不可达（代理），公网 API 可达性因环境而异 ——
   机器验收走 `PW_WEATHER_FAKE=1`（响应里显式标注 fake 来源）；真实 Open-Meteo
   端到端需人工在有网环境核对（脚本不强测，避免环境假失败）。
 - **音乐真实播放**：需要用户真的在放音乐（SMTC 会话存在）—— 机器只能验证端点
   与降级路径；真实会话信息人工核对。
 - **GPU/温度**：Windows 无免驱动通用通道，实现如实不提供，验收同样不断言。
 - **11 §验收8（插件形态）与 12 §验收11（生活中心迁移）口径差**：本阶段以核心
   模块交付，插件迁移归阶段9 —— 判据 8 校验的是"模块齐 + 迁移口径已声明 +
   无插件特判"，不是"已是插件"。
 - 事件投递到 webview 只有**接线级**证据（同阶段5/6/7 口径）。

用法：
  python tools/verify_stage8.py
  python tools/verify_stage8.py --exe core/target/release/personal-workspace-core.exe
  python tools/verify_stage8.py --keep

前置：先 `cargo build --release`（可用 `python tools/rust.py build --release`）。
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
PY = sys.executable

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")


def http_json(url: str, method: str = "GET", body=None, timeout: float = 30.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    # 本机直连 core：绕过 http_proxy 等环境代理（沙箱代理无法回连宿主 loopback）
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None
    except Exception as e:  # noqa: BLE001
        return 0, {"ok": False, "error": {"code": "transport", "message": str(e)}}


def data_of(resp):
    st, body = resp
    if not body:
        return None
    d = body.get("data")
    return d if body.get("ok") is True else None


def wait_port(db_path: Path, old_port: str, timeout_s: float = 40.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        port = read_config_map(db_path).get("runtime.http_port", "")
        if port and str(port) != str(old_port):
            return str(port)
        time.sleep(0.3)
    return ""


def read_config_map(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {k: v for k, v in con.execute("SELECT key, value FROM config").fetchall()}
    except Exception:  # noqa: BLE001
        return {}
    finally:
        con.close()


def wait_sidecar(db_path: Path, old: str, timeout_s: float = 60.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        port = read_config_map(db_path).get("runtime.sidecar_port", "")
        if port and str(port) != str(old):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
                    if r.status == 200:
                        return str(port)
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.3)
    return ""


def start_app(exe: Path, data_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PW_DATA_DIR"] = str(data_dir)
    env["PW_SIDECAR_FORCE_DEV"] = "1"      # 钉死 sidecar 到当前源码（防旧快照）
    env["PW_WEATHER_FAKE"] = "1"           # 天气走 fake（机器可判；真实 API 人工）
    return subprocess.Popen(
        [str(exe)], cwd=str(REPO_ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def stop_app(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()


def db_tables(db_path: Path) -> list[str]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    finally:
        con.close()


def db_columns(db_path: Path, table: str) -> list[str]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="阶段8 验收自动核验")
    ap.add_argument("--exe", help="release 可执行文件路径")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    exe = (
        Path(args.exe)
        if args.exe
        else REPO_ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"
    )
    if not exe.exists():
        print(f"[FATAL] 可执行文件不存在：{exe}\n        先跑 `python tools/rust.py build --release`。")
        return 2

    data_dir = Path(tempfile.mkdtemp(prefix="pw-verify8-"))
    db_path = data_dir / "workspace.db"

    procs: list[subprocess.Popen] = []
    core: subprocess.Popen | None = None
    base = ""
    http_port = ""

    print(f"[verify8] exe = {exe}")
    print(f"[verify8] data dir = {data_dir}")

    def api(path: str, method: str = "GET", body=None, timeout: float = 30.0):
        return http_json(base + path, method, body, timeout)

    def start_core(old_port: str, old_sc: str) -> tuple[str, str]:
        p = start_app(exe, data_dir)
        procs.append(p)
        port = wait_port(db_path, old_port)
        if not port:
            raise RuntimeError("core 未写出 runtime.http_port")
        nb = f"http://127.0.0.1:{port}"
        deadline = time.time() + 15
        while time.time() < deadline:
            st, _ = http_json(nb + "/health", timeout=3)
            if st == 200:
                break
            time.sleep(0.3)
        return nb, wait_sidecar(db_path, old_sc)

    try:
        # ---------------------------------------------------------- 起 core
        print("\n启动 core（release，开发态拉 sidecar，PW_WEATHER_FAKE=1）...")
        base, sc_port = start_core("", "")
        http_port = base.rsplit(":", 1)[-1]
        print(f"  core http = {base}")
        check("前置：core 存活 + sidecar /health 可用", bool(sc_port),
              f"sidecar port={sc_port or '（未就绪）'}")

        # 契约版本：0007 迁移已执行 ⇒ 契约版本**至少** v10。
        # 注（TECH-04/TECH-05-C）：同 `verify_stage7.py:348-355` —— 契约版本单调递增，
        # 该断言表达的是"迁移 0007 已生效"，用 `>=` 而非钉死常量。
        st_v, b_v = api("/api/v1/config/schema_version")
        check("前置：契约版本 ≥ v10（迁移 0007 生效）",
              (data_of((st_v, b_v)) or 0) >= 10, f"schema_version={data_of((st_v, b_v))}")

        # ======================================================== 验收 1 天气
        print("\n--- 验收项 1：天气（手动城市 + 缓存 + 不自动定位）" + "-" * 12)
        st_n, b_n = api("/api/v1/life/weather")
        got_n = data_of((st_n, b_n)) or {}
        check("1a 未设置城市 → no_city（绝不自动获取系统定位）",
              st_n == 200 and got_n.get("reason") == "no_city",
              f"status={st_n} reason={got_n.get('reason')!r}")

        st_w1, b_w1 = api("/api/v1/life/weather?city=" + urllib.parse.quote("杭州"))
        w1 = data_of((st_w1, b_w1)) or {}
        st_w2, b_w2 = api("/api/v1/life/weather?city=" + urllib.parse.quote("杭州"))
        w2 = data_of((st_w2, b_w2)) or {}
        check("1b 设置城市 → 返回数据（fake 来源显式标注）+ 两次一致（缓存路径）",
              st_w1 == 200 and w1.get("city") and w1 == w2
              and "fake" in str(w1.get("source", "")),
              f"city={w1.get('city')!r} source={w1.get('source')!r}")

        # ======================================================== 验收 2 音乐
        print("\n--- 验收项 2：音乐（SMTC 端点 + 降级路径）" + "-" * 12)
        st_m, b_m = api("/api/v1/life/media")
        m = data_of((st_m, b_m)) or {}
        if m.get("available"):
            sess = m.get("session")
            check("2a SMTC 可用 → 会话结构完整（无会话时 session=null）",
                  sess is None or {"title", "artist", "status"} <= set(sess),
                  f"session={bool(sess)} title={(sess or {}).get('title', '')!r}")
            print("         ⚠️ 真实播放核对（歌曲名/进度）需人工：开一个播放器放歌再看本页")
        else:
            check("2a winsdk 不可用 → available:false 优雅降级（不崩、不假数据）",
                  st_m == 200 and bool(m.get("reason")),
                  f"reason={m.get('reason')!r}")
        check("2b 媒体控制端点：非法 action 被拒（400）",
              api("/api/v1/life/media/control", "POST", {"action": "hack"})[0] == 400)

        # ======================================================== 验收 3 消息概览
        print("\n--- 验收项 3：消息概览（接入服务 → 未读数；无内容落库）" + "-" * 12)
        st_cfg, _ = api("/api/v1/life/social/config", "PUT",
                        {"services": [{"name": "演示信箱", "type": "demo", "demoUnread": 7}]})
        st_o, b_o = api("/api/v1/life/social/overview")
        items = (data_of((st_o, b_o)) or {}).get("items") or []
        demo = next((i for i in items if i.get("name") == "演示信箱"), {})
        check("3a 接入 demo 服务 → 未读数返回（7）",
              st_cfg == 200 and demo.get("ok") is True and demo.get("unread") == 7,
              f"status={st_cfg} item={demo}")
        check("3b 概览条目不含正文（只有 name/type/unread/summary）",
              set(demo.keys()) <= {"name", "type", "ok", "unread", "summary"},
              f"keys={sorted(demo.keys())}")

        # ======================================================== 验收 4 使用时间
        print("\n--- 验收项 4：使用时间（前台采样 → 今日排行）" + "-" * 12)
        st_i, _ = api("/api/v1/config/life.usage_sample_interval_sec", "PUT", 1)
        check("4a 采样间隔可配（1s，验收加速）", st_i == 200, f"status={st_i}")
        print("  等待 8s 采样（间隔 1s）...")
        time.sleep(8)
        st_u, b_u = api("/api/v1/life/usage/today")
        u = data_of((st_u, b_u)) or {}
        ranking = u.get("ranking") or []
        check("4b 今日出现前台使用条目且总量 > 0（聚合口径）",
              st_u == 200 and u.get("totalSeconds", 0) > 0 and len(ranking) > 0,
              f"totalSeconds={u.get('totalSeconds')} top={[r.get('app_name') for r in ranking[:3]]}")
        st_wk, b_wk = api("/api/v1/life/usage/week")
        days = (data_of((st_wk, b_wk)) or {}).get("days") or []
        check("4c 周趋势端点返回今日数据", any(str(d.get("day", "")).endswith(str(u.get("day", ""))) for d in days) if days else False,
              f"days={len(days)}")

        # ======================================================== 验收 5 隐私
        print("\n--- 验收项 5：隐私（数据库无聊天内容；usage 只存聚合）" + "-" * 12)
        tables = db_tables(db_path)
        bad_tables = [t for t in tables if any(k in t.lower() for k in ("message", "chat", "social_content"))]
        cols = db_columns(db_path, "usage_stats")
        check("5a 无任何消息/聊天内容表", not bad_tables,
              f"表数={len(tables)} 可疑表={bad_tables or '无'}")
        check("5b usage_stats 只有聚合列（day/app_name/seconds），无时间点明细",
              sorted(cols) == ["app_name", "day", "seconds"], f"cols={sorted(cols)}")

        # ======================================================== 验收 6 设备指标
        print("\n--- 验收项 6：设备指标（与系统实际值接近）" + "-" * 12)
        st_d1, b_d1 = api("/api/v1/device/metrics")
        d1 = data_of((st_d1, b_d1)) or {}
        cur = d1.get("current") or {}
        cpu_ok = isinstance(cur.get("cpu"), (int, float)) and 0 <= cur["cpu"] <= 100
        mem_ok = (cur.get("mem_total") or 0) > 0 and 0 < (cur.get("mem_used") or 0) <= cur.get("mem_total", 0)
        check("6a CPU ∈ [0,100] 且内存值合理（总量>0、已用≤总量）", cpu_ok and mem_ok,
              f"cpu={cur.get('cpu')} mem={cur.get('mem_used')}/{cur.get('mem_total')}")
        check("6b 磁盘列表非空且数值合理", len(cur.get("disks") or []) > 0
              and all((d.get("total_bytes") or 0) > (d.get("free_bytes") or 0) for d in cur.get("disks", [])),
              f"disks={[(d.get('letter'), d.get('total_bytes')) for d in cur.get('disks', [])]}")
        h1 = len(d1.get("history") or [])
        time.sleep(3)
        st_d2, b_d2 = api("/api/v1/device/metrics")
        d2 = data_of((st_d2, b_d2)) or {}
        h2 = len(d2.get("history") or [])
        check("6c 环形缓冲随时间推进（不落库、内存内）", h2 >= h1 and h2 >= 1, f"history {h1} → {h2}")

        try:
            import psutil  # type: ignore[import-not-found]

            pm = psutil.virtual_memory()
            expect = pm.total
            got = cur.get("mem_total") or 0
            diff = abs(got - expect) / expect if expect else 1
            check("6d 内存总量与 psutil 对照（±5%）", diff < 0.05,
                  f"core={got} psutil={expect} 偏差={diff:.1%}")
        except ImportError:
            check("6d 内存总量与 psutil 对照（±5%）", False,
                  "psutil 未安装 —— 请 `pip install psutil` 后重跑（对照断言需要它）")

        # ======================================================== 验收 7 进程管理
        print("\n--- 验收项 7：进程管理（列表 + 结束进程二次确认）" + "-" * 12)
        st_p, b_p = api("/api/v1/device/processes")
        plist = (data_of((st_p, b_p)) or {}).get("processes") or []
        core_pid = os.getpid()  # 脚本自身不在 core 里；改用"列表非空 + 含 core 进程名"
        self_row = next((p for p in plist if "personal-workspace-core" in str(p.get("name", ""))), None)
        check("7a 进程列表非空且含 core 自身", st_p == 200 and len(plist) > 5 and self_row is not None,
              f"count={len(plist)} self={'有' if self_row else '无'}")

        # 受控子进程：python -c sleep 300
        victim = subprocess.Popen(
            [PY, "-c", "import time; time.sleep(300)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        procs.append(victim)
        time.sleep(0.5)
        victim_alive_0 = victim.poll() is None

        st_k0, _ = api("/api/v1/device/processes/kill", "POST",
                       {"pid": victim.pid, "confirm": False})
        confirm_guard = st_k0 == 400
        st_k1, _ = api("/api/v1/device/processes/kill", "POST",
                       {"pid": victim.pid, "confirm": True})
        time.sleep(1.0)
        victim_dead = victim.poll() is not None
        check("7b 结束进程：confirm=false 被拒（V5 API 侧闸）+ confirm=true 真结束",
              victim_alive_0 and confirm_guard and st_k1 == 200 and victim_dead,
              f"alive0={victim_alive_0} guard400={confirm_guard} kill200={st_k1 == 200} dead={victim_dead}")

        # ======================================================== 验收 8 插件形态（如实判据）
        print("\n--- 验收项 8：插件形态（模块齐备 + 阶段9 迁移口径声明 + 无插件特判）" + "-" * 12)
        life_readme = (REPO_ROOT / "modules" / "life" / "README.md").read_text(encoding="utf-8")
        device_readme = (REPO_ROOT / "modules" / "device" / "README.md").read_text(encoding="utf-8")
        check("8a 核心模块与 README 齐备（迁移口径已声明）",
              "迁移" in life_readme and "插件" in life_readme
              and "迁移" in device_readme and "插件" in device_readme)

        core_src = list((REPO_ROOT / "core" / "src").rglob("*.rs"))
        hit_special = []
        for f in core_src:
            text = f.read_text(encoding="utf-8", errors="replace")
            if 'plugin_id ==' in text or 'plugin_id==' in text or 'if plugin_id ==' in text:
                hit_special.append(str(f.relative_to(REPO_ROOT)))
        check("8b core 无插件特判（`plugin_id ==` 零命中）", not hit_special,
              f"命中={hit_special or '无'}")

        # ======================================================== 汇总
        print("\n" + "=" * 70)
        total = len(results)
        passed = sum(1 for _, ok, _ in results if ok)
        for name, ok, _ in results:
            if not ok:
                print(f"  [FAIL] {name}")
        print(f"合计 {passed}/{total} 通过")
        return 0 if passed == total else 1

    except Exception as exc:  # noqa: BLE001
        print(f"[FATAL] {exc}")
        import traceback

        traceback.print_exc()
        return 2
    finally:
        stop_app(core)
        for p in procs:
            stop_app(p)
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)
        else:
            print(f"[verify8] 数据目录保留：{data_dir}")


if __name__ == "__main__":
    sys.exit(main())
