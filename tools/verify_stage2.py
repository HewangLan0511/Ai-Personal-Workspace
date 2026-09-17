#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段2 验收自动核验：把 05「验收标准」8 项做成机器可判。

覆盖（docs/agent-dev/05-阶段指令-软件管理.md §验收标准）：
  1 添加软件        POST /api/v1/apps → 列表查得到
  2 启动软件        启动后 pid **真的**存在（tasklist 复核）
  3 启动失败提示    路径不存在 → 返回**可读**错误（不是崩溃、不是 500 堆栈）
  4 状态同步        杀掉进程 → 5s 内 /api/v1/apps/running 不再含该 id
  5 分类与搜索      ?category= / ?search= 都能正确过滤
  6 排序            launch_count 多的靠前，pinned 置顶
  7 扫描            POST /api/v1/scan 列出本机已安装软件（经 sidecar 读注册表）
  8 持久化          重启应用 → 软件列表与启动次数仍在

另附 2 项本阶段自加的强化检查：
  9  图标接口的**目录穿越防护**（传缓存目录外的路径必须被拒）
  10 自动补全（FileDescription → name，内嵌图标 → PNG 缓存）

为什么走 HTTP 而不是点界面：
  验收 1/2/4 的本质是"**Rust 真的把进程启起来了、真的检测到了退出**" ——
  直接打 core 的同一份业务逻辑（HTTP 与 invoke 同源）比在无头浏览器里点 DOM 更接近真相
  （浏览器里没有进程能力，只能造假）。

用法：
  python tools/verify_stage2.py
  python tools/verify_stage2.py --exe core/target/release/personal-workspace-core.exe
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

# 被测目标：无窗口、能存活一会儿、随时可杀（避免 GUI 弹窗干扰）
TEST_EXE_A = r"C:\Windows\System32\cmd.exe"
TEST_ARGS_A = "/c ping -n 60 127.0.0.1 >nul"
TEST_EXE_B = r"C:\Windows\System32\where.exe"  # 与 A 不同路径，避免撞 UNIQUE


def q(s: str) -> str:
    return urllib.parse.quote(s)


def http_json(url: str, method: str = "GET", body=None, timeout: float = 8.0):
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


# ---------------------------------------------------------------- Windows 进程

def pid_alive(pid: int) -> bool:
    """用 tasklist 复核 pid 是否真实存在（不信 core 的返回值本身）。"""
    out = subprocess.run(
        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
        capture_output=True,
    ).stdout.decode("gbk", errors="replace")
    return str(pid) in out and "No tasks" not in out and "没有运行" not in out


def kill_pid(pid: int) -> None:
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)


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


# ---------------------------------------------------------------- 数据库（只读）

def read_config_map(db_path: Path) -> dict[str, str]:
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {k: v for k, v in con.execute("SELECT key, value FROM config").fetchall()}
    finally:
        con.close()


def wait_for_config(db_path: Path, keys: tuple[str, ...], timeout_s: float = 30.0) -> dict[str, str]:
    """轮询等待配置键落库（sidecar 是单文件 exe，要先自解包才能 announce 端口）。"""
    deadline = time.time() + timeout_s
    cfg: dict[str, str] = {}
    while time.time() < deadline:
        if db_path.exists():
            try:
                cfg = read_config_map(db_path)
            except Exception:
                cfg = {}
            if all(cfg.get(k) not in (None, "null") for k in keys):
                return cfg
        time.sleep(0.3)
    return cfg


def wait_for_new_port(db_path: Path, old_port: str, timeout_s: float = 30.0) -> dict[str, str]:
    """**重启**后等 http 端口变成新值。

    ⚠️ 这里不能用 `wait_for_config`：库里还留着**上一个实例**写入的端口，
    "非空"判定会立刻返回旧值 → 请求打到已死进程（连接被拒 / 502）。
    本脚本第一版正是栽在这 —— 于是"持久化"被误判为失败，实际数据完好。
    """
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


# ---------------------------------------------------------------- 主流程

def main() -> int:
    ap = argparse.ArgumentParser(description="阶段2 验收自动核验")
    ap.add_argument("--exe", help="release 可执行文件路径")
    ap.add_argument("--keep", action="store_true", help="保留临时数据目录")
    args = ap.parse_args()

    exe = Path(args.exe) if args.exe else REPO_ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"
    if not exe.exists():
        print(f"[FATAL] 可执行文件不存在：{exe}\n        先跑 `cargo build --release`。")
        return 2

    data_dir = Path(tempfile.mkdtemp(prefix="pw-verify2-"))
    db_path = data_dir / "workspace.db"
    print(f"[verify2] exe      = {exe}")
    print(f"[verify2] data dir = {data_dir}")

    results: list[tuple[str, bool, str]] = []
    proc: subprocess.Popen | None = None
    baseline = list_sidecar_pids()
    base = ""
    spawned_pids: list[int] = []

    def api(path: str, method: str = "GET", body=None):
        return http_json(base + path, method, body)

    def data_of(resp) -> object:
        st, body = resp
        return (body or {}).get("data") if body else None

    try:
        proc = start_app(exe, data_dir)
        cfg = wait_for_config(db_path, ("runtime.http_port",))
        port = cfg.get("runtime.http_port")
        if not port:
            raise RuntimeError("core 未写出 runtime.http_port，无法继续")
        base = f"http://127.0.0.1:{port}"
        print(f"[verify2] core http = {base}")

        # ---- 7 扫描（顺带确认 sidecar 就绪）----
        wait_for_config(db_path, ("runtime.sidecar_port",), timeout_s=30.0)
        st, body = api("/api/v1/scan", "POST", {})
        items = ((body or {}).get("data") or {}).get("items", [])
        ok7 = st == 200 and len(items) > 0
        results.append(("7 扫描已安装软件（注册表）", ok7, f"status={st} 条目={len(items)}"))

        # ---- 10 自动补全 + 图标安全 ----
        st, body = api("/api/v1/probe", "POST", {"path": r"C:\Windows\System32\notepad.exe"})
        probe = (body or {}).get("data") or {}
        icon_path = probe.get("iconPath")
        note = f"name={probe.get('name')!r}"
        icon_ok = True
        if icon_path:
            st_i, body_i = api(f"/api/v1/icon?path={q(icon_path)}")
            icon_ok = st_i == 200 and str((body_i or {}).get("data", "")).startswith("data:image")
            note += f"；图标 dataURL={'OK' if icon_ok else 'FAIL'}"
        else:
            note += "；图标降级（该 exe 无内嵌图标）"
        st_bad, _ = api(f"/api/v1/icon?path={q(r'C:\Windows\win.ini')}")
        escape_ok = st_bad != 200
        note += f"；越权路径被拒={escape_ok}"
        ok10 = bool(probe.get("name")) and escape_ok and icon_ok
        results.append(("10 自动补全（名称/图标/目录穿越防护）", ok10, note))

        # ---- 1 添加软件 ----
        st, body = api("/api/v1/apps", "POST", {
            "name": "验收测试A", "path": TEST_EXE_A, "args": TEST_ARGS_A,
            "type": "exe", "category": "开发",
        })
        id_a = ((body or {}).get("data") or {}).get("id")
        ok1 = st == 200 and bool(id_a)
        results.append(("1 添加软件", ok1, f"status={st} id={id_a}"))

        st, body = api("/api/v1/apps", "POST", {
            "name": "验收测试B", "path": TEST_EXE_B, "args": "",
            "type": "exe", "category": "媒体",
        })
        id_b = ((body or {}).get("data") or {}).get("id")

        listed = data_of(api("/api/v1/apps")) or []
        names = [x.get("name") for x in listed]
        ok1b = "验收测试A" in names and "验收测试B" in names
        results.append(("1b 列表可见", ok1b, f"列表={names}"))

        # ---- 2 启动软件（pid 真实存在）----
        spawned = data_of(api(f"/api/v1/apps/{id_a}/launch", "POST")) or {}
        pid_a = spawned.get("pid")
        if pid_a:
            spawned_pids.append(int(pid_a))
        time.sleep(1.0)
        alive = pid_alive(int(pid_a)) if pid_a else False
        ok2 = bool(alive) and spawned.get("pidTracked") is True
        results.append(("2 启动软件（tasklist 复核 pid）", ok2, f"pid={pid_a} 进程存在={alive}"))

        # ---- 3 启动失败提示（可读错误 + core 未崩）----
        st, body = api("/api/v1/apps", "POST", {
            "name": "验收测试-坏路径", "path": r"C:\__no_such_dir__\nope.exe", "args": "",
            "type": "exe", "category": "其他",
        })
        bad_id = ((body or {}).get("data") or {}).get("id")
        st3, body3 = api(f"/api/v1/apps/{bad_id}/launch", "POST")
        msg = ((body3 or {}).get("error") or {}).get("message", "") if body3 else ""
        st_h, _ = api("/health")
        ok3 = st3 != 200 and ("不存在" in msg or "不可启动" in msg) and st_h == 200
        results.append(("3 启动失败提示（可读且未崩溃）", ok3, f"status={st3} msg={msg!r} core存活={st_h == 200}"))

        # ---- 6 排序：B 多启动几次，应排到 A 前面；pinned 应置顶 ----
        for _ in range(3):
            r = data_of(api(f"/api/v1/apps/{id_b}/launch", "POST")) or {}
            pid = r.get("pid")
            if pid:
                spawned_pids.append(int(pid))
                kill_pid(int(pid))  # 杀掉才能再次计数（"已在运行"不重复计数）
            time.sleep(0.8)
        rows = [x for x in (data_of(api("/api/v1/apps")) or []) if (x.get("name") or "").startswith("验收测试")]
        counts = [(x["name"], x["launch_count"]) for x in rows]
        non_increasing = all(counts[i][1] >= counts[i + 1][1] for i in range(len(counts) - 1))
        # B 的计数应 >= A
        cb = next((c for n, c in counts if n == "验收测试B"), 0)
        ca = next((c for n, c in counts if n == "验收测试A"), 0)
        # pinned 置顶
        api(f"/api/v1/apps/{bad_id}", "PUT", {"pinned": True})
        rows2 = [x for x in (data_of(api("/api/v1/apps")) or []) if (x.get("name") or "").startswith("验收测试")]
        pinned_first = bool(rows2 and rows2[0]["name"] == "验收测试-坏路径")
        ok6 = non_increasing and cb >= ca and pinned_first
        results.append(("6 排序（次数非降序 + 置顶优先）", ok6, f"次数={counts} 置顶项在最前={pinned_first}"))

        # ---- 5 分类与搜索 ----
        cat_rows = data_of(api("/api/v1/apps?category=" + q("开发"))) or []
        cat_ok = len(cat_rows) >= 1 and all(x.get("category") == "开发" for x in cat_rows)
        search_rows = data_of(api("/api/v1/apps?search=" + q("测试B"))) or []
        search_ok = len(search_rows) >= 1 and all("测试B" in (x.get("name") or "") for x in search_rows)
        cats = data_of(api("/api/v1/apps/categories")) or []
        cats_ok = "开发" in cats and "媒体" in cats
        ok5 = cat_ok and search_ok and cats_ok
        results.append(("5 分类与搜索", ok5, f"分类过滤={cat_ok}({len(cat_rows)}) 搜索={search_ok}({len(search_rows)}) 分类清单={cats}"))

        # ---- 4 状态同步：杀掉进程 → 5s 内清标记 ----
        running_now = data_of(api("/api/v1/apps/running")) or {}
        # 确保 A 在运行
        r = data_of(api(f"/api/v1/apps/{id_a}/launch", "POST")) or {}
        pid_a2 = r.get("pid") or running_now.get(str(id_a))
        before = bool(pid_a2)
        if pid_a2:
            kill_pid(int(pid_a2))
        time.sleep(7.0)  # 轮询周期 5s，留余量
        after = data_of(api("/api/v1/apps/running")) or {}
        cleared = str(id_a) not in after
        ok4 = before and cleared
        results.append(("4 状态同步（杀进程后 5s 内清标记）", ok4, f"杀前运行中={before} 杀后已清={cleared} after={after}"))

        # ---- 8 持久化：重启后列表与计数仍在 ----
        old_port = cfg.get("runtime.http_port") or ""
        stop_app(proc)
        proc = None
        time.sleep(1.5)
        proc = start_app(exe, data_dir)
        cfg2 = wait_for_new_port(db_path, old_port, timeout_s=30.0)
        base = f"http://127.0.0.1:{cfg2.get('runtime.http_port')}"
        rows3 = data_of(api("/api/v1/apps")) or []
        names3 = [x.get("name") for x in rows3]
        counts3 = {x["name"]: x["launch_count"] for x in rows3}
        persisted = "验收测试A" in names3 and "验收测试B" in names3
        counts_kept = counts3.get("验收测试B", 0) >= 1
        ok8 = persisted and counts_kept
        results.append(("8 持久化（重启后列表与计数保持）", ok8, f"列表={names3} 计数={counts3}"))

    except Exception as e:  # noqa: BLE001
        results.append(("执行异常", False, f"{type(e).__name__}: {e}"))
    finally:
        stop_app(proc)
        for pid in spawned_pids:
            kill_pid(pid)
        kill_sidecar(baseline)
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)
        else:
            print(f"[verify2] 数据目录已保留：{data_dir}")

    print("\n" + "=" * 64)
    print("阶段2 验收核验结果")
    print("=" * 64)
    all_ok = True
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}\n      {detail}")
        all_ok = all_ok and passed
    print("=" * 64)
    print(f"合计 {sum(1 for _, p, _ in results if p)}/{len(results)} 通过")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
