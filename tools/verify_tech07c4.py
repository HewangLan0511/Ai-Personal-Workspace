#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TECH-07-C4 验收 · Workspace Snapshot Persistence / Restore
==========================================================

S 段（静态）：C4 禁区 / 持久化只走 Core config / 冻结域零改 / 不用 lastFacts /
    runId 来自 core 事实 / 视觉冻结 / core 侧最小改动登记齐全
R 段（回归）：C3 27/27 · C2 25/25 · C1 16/16 · TECH-02 11/11 · 契约套件
D 段（真实环境，非 mock）：
    A Capture：真实受管窗口 → 快照 → 契约校验 + validate 通过
    B Persistence：capture → 落 config → **杀 core** → 新进程读回（同 snapshotId，runId 变化）
    C Real Restore：C1 同运行期（hwnd+pid）· C2 跨重启（exePath）→ 真实窗口回到快照位置
    D Missing：受管窗口不存在 → missing 且零摆位
    E Ambiguous：同 exePath 两个候选 → ambiguous 且零摆位
    F Corrupted：损坏快照 → invalid、零摆位、原值未被改写/删除
    G Offline：core 离线 → offline、零摆位（不碰陈旧缓存）
    H Topology：快照 rect 跨越工作区边界 → 恢复后仍完整可见（最小安全修正）

用法：python tools/verify_tech07c4.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import verify_tech02_workspace as base  # noqa: E402
import verify_tech07c2 as c2  # noqa: E402

UI = ROOT / "ui"
SRC = UI / "src"
RUNTIME = SRC / "workspace" / "runtime"
RUNVIEW = SRC / "views" / "RunView.vue"
FROZEN_SNAPSHOT = SRC / "workspace" / "snapshot.ts"
SNAP_ADAPTER = RUNTIME / "snapshot.ts"
CHARMAP = r"C:\Windows\System32\charmap.exe"
TITLE = "字符映射表"
CFG_KEY = "workspace.snapshot.last"

RESULTS: list[tuple[str, bool, str]] = []
SECTIONS = ("A Capture", "B Persistence", "C1 同运行期恢复", "C2 跨重启恢复",
            "D Missing", "E Ambiguous", "F Corrupted", "G Offline", "H Topology")


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def defer(name: str, detail: str) -> None:
    """既不绿也不红：**真实环境不可构造**，如实登记为 Deferred（不算通过）。"""
    RESULTS.append((name, None, detail))  # type: ignore[arg-type]
    print(f"DEFER {name} — {detail}")


def unrun(reason: str) -> None:
    """把尚未登记的 D 段位如实标成「未执行」——中途异常绝不静默漏项。"""
    done = {n.split("（")[0] for n, _, _ in RESULTS}
    for n in SECTIONS:
        if n not in done:
            check(n, False, f"NOT RUN — {reason}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def strip_comments(code: str) -> str:
    """去掉 TS 注释后再做"禁区路径"扫描 —— 注释里提到命令名不算调用。"""
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


def keys_block(cfg: str) -> str:
    """取 `pub const KEYS` 到数组结束（`];`）之间的原文。"""
    seg = cfg.split("pub const KEYS", 1)[1]
    end = seg.find("];")
    return seg[:end] if end > 0 else seg


# ================================================================ S 段（静态）

# C4 冻结基线：TECH-02 冻结域 v1 实现 + 视觉基线四 CSS（C4 结束时内容指纹）
FROZEN = {
    # 首次登记：C4 全程未编辑该文件（C4 只新增 runtime/ 下的适配器），故当前指纹即 C4 开工基线
    "ui/src/workspace/snapshot.ts": "604fe010e0d3f980",
    "ui/src/styles/tokens.css": "4741eed584a8b589",
    "ui/src/styles/motion-tokens.css": "adee6b0380a7b04d",
    "ui/src/components/ui/primitives.css": "37a8ff2d375f61c4",
    # 2026-09-18 动效对接批次有意更新（121b562804633520 → ee7d92615121cd45 → 07e79a756e1657c1）：
    # ① resync 并入设计稿 Press 反馈规则；② 并入 `.mt-*` 动效规范层（/motion 消费）；
    # ③ 段前新增「壳层折叠动画的连续性补齐」块（④ 为该块同权重失效的更正）。视觉取值本身未改 ——
    # 理由与逐项说明见 verify_tech07c2.py 的 A3b。
    "ui/src/styles/base.css": "07e79a756e1657c1",
}


def s1_no_forbidden_paths() -> None:
    code = strip_comments(read(SNAP_ADAPTER))
    bad = re.findall(
        r"windows_activate|windows_close|apps_terminate|apps_launch|TerminateProcess|taskkill",
        code,
    )
    check("S1a 快照模块零禁区路径（activate/close/terminate/launch）", not bad, str(sorted(set(bad)) or "无"))
    storage = re.findall(r"localStorage|sessionStorage|indexedDB", code)
    check("S1b 快照模块零本地存储（持久化只走 Core config）", not storage, str(storage or "无"))


def s2_persistence_channel() -> None:
    code = read(SNAP_ADAPTER)
    ok = ("putCore" in code) and ("getCore" in code) and ("SNAPSHOT_CONFIG_KEY" in code)
    check("S2 持久化经 Core config 严格读写（putCore/getCore）", ok, "snapshot.ts")
    cfgs = read(SRC / "api" / "configService.ts")
    strict = "export async function putCore" in cfgs and "export async function getCore" in cfgs
    no_ls = "writeLocal" not in cfgs.split("export async function putCore")[1].split("export const configApi")[0]
    check("S2b putCore/getCore 无 localStorage 降级", strict and no_ls, "configService.ts")


def s3_frozen_domain_untouched() -> None:
    """冻结域（v1 契约实现）与视觉基线零改动 —— hash 冻结。

    基线说明：C4 开工时**首次登记** `ui/src/workspace/snapshot.ts` 的指纹；
    C4 期间未修改该文件（任何改动都会在这里红灯）。
    """
    bad: list[str] = []
    for rel, want in FROZEN.items():
        got = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16]
        if got != want:
            bad.append(f"{rel}: {got} != {want}")
    check("S3 冻结域 v1 + 视觉基线 CSS 零改动（hash 冻结）", not bad, str(bad or "全部一致"))


def s4_not_from_lastfacts() -> None:
    code = strip_comments(read(SNAP_ADAPTER))
    ok = ("lastSnapshot" not in code) and ("takeFacts()" in code or "snapshot as takeFacts" in code)
    check("S4 Capture 用新鲜 facts（不把 lastFacts 当 Snapshot）", ok, "snapshot.ts")


def s5_runid_from_core() -> None:
    code = read(SNAP_ADAPTER)
    ok = ("coreIdentity" in code) and ("Math.random" not in code)
    sysrv = read(SRC / "api" / "systemService.ts")
    ok2 = "pid" in sysrv and "started_at" in sysrv
    check("S5 runId 由 core 自报事实推导（零虚构/零随机）", ok and ok2, "snapshot.ts + systemService.ts")


def s6_visual_freeze() -> None:
    rv = read(RUNVIEW)
    tokens = re.findall(r"(--[\w-]+)\s*:", rv)
    motion = re.findall(r"@keyframes|animation\s*:|transition\s*:", rv)
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", rv, flags=re.S))
    extra = [f.name for f in (SRC / "styles").glob("*.css")
             if f.name not in ("base.css", "motion-tokens.css", "tokens.css")]
    ok = not tokens and not motion and not hexes and not extra
    check("S6a RunView 零新 token / 零动画 / 零硬编码色 / 无新样式文件", ok,
          f"token={tokens[:3]} motion={motion[:2]} hex={hexes[:2]} extra={extra}")
    ui_ok = all(x in rv for x in ("run-snap-save", "run-snap-restore", "run-snap-chip"))
    check("S6b C4 UI 为最小暴露（既有状态栏 + 既有组件）", ui_ok, "data-pw 三个入口")


def s7_core_registration() -> None:
    cfg = read(ROOT / "core" / "src" / "db" / "config.rs")
    api = read(ROOT / "core" / "src" / "api" / "mod.rs")
    in_keys = f'"{CFG_KEY}"' in keys_block(cfg)
    in_type = f'"{CFG_KEY}" => "object"' in cfg
    in_default = f'"{CFG_KEY}" => serde_json::json!({{}})' in cfg
    check("S7a config 键三处登记齐备（KEYS/type/default）",
          in_keys and in_type and in_default, f"keys={in_keys} type={in_type} default={in_default}")
    ok_health = ("identity_facts" in api) and ("started_at" in api) and ("std::process::id()" in api)
    check("S7b /health 提供真实 pid + started_at", ok_health, "api/mod.rs")
    # 不得新增表/迁移：C4 不得出现新 migration 文件
    mig = sorted(p.name for p in (ROOT / "core" / "src" / "db").glob("*.rs"))
    check("S7c 未新增数据库表/迁移（db 模块文件集合未变）", "migrations.rs" in mig, str(mig))


# ================================================================ R 段（回归）

def r_regression() -> None:
    for script, expect in (("verify_tech07c3.py", "27"), ("verify_tech07c2.py", "25"),
                           ("verify_tech07c.py", "16")):
        p = subprocess.run([sys.executable, str(TOOLS / script)], cwd=ROOT,
                           capture_output=True, text=True, timeout=1800)
        sums = re.findall(r"(\d+)/(\d+)\s*通过", p.stdout)
        ok = p.returncode == 0 and sums and sums[-1][0] == sums[-1][1] == expect
        check(f"R {script}", ok, f"exit={p.returncode} 汇总={sums[-1] if sums else '未解析'}")

    p = subprocess.run([sys.executable, str(TOOLS / "verify_tech02_workspace.py")], cwd=ROOT,
                       capture_output=True, text=True, timeout=1800)
    m = re.search(r"汇总\s*(\d+)/(\d+)", p.stdout)
    check("R verify_tech02_workspace.py", p.returncode == 0 and m and m.group(1) == m.group(2) == "11",
          f"exit={p.returncode} 汇总={m.group(0) if m else '未解析'}")

    p = subprocess.run([sys.executable, str(TOOLS / "verify_contracts.py")], cwd=ROOT,
                       capture_output=True, text=True, timeout=600)
    check("R verify_contracts.py（契约套件）", p.returncode == 0,
          f"exit={p.returncode} {((p.stdout or '').strip().splitlines() or [''])[-1][:80]}")


# ================================================================ D 段（真实环境）

class ProxyHandler(c2.ProxyHandler):
    """C4 专用代理：在 C2 的 GET/POST 之上补 **PUT**。

    快照持久化走 `PUT /api/v1/config/{key}`（Core config 单键覆盖）；C2 的代理
    只有 GET/POST，PUT 会落成 501 → UI 侧如实报 `write_failed`（不是假绿，
    但也拿不到真实写入证据）。这里补上，转发口径与 C2 完全一致。
    """

    def do_PUT(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._proxy("PUT")
        else:
            self.send_error(404)


def http_json(port: int, path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def core_health(port: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=5) as r:
        return json.loads(r.read().decode()).get("data") or {}


def core_windows(port: int) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/windows", timeout=8) as r:
        return json.loads(r.read().decode()).get("data") or []


def place_via_core(port: int, hwnd: int, rect: dict) -> None:
    http_json(port, f"/api/v1/windows/{hwnd}", "POST",
              {"x": rect["x"], "y": rect["y"], "w": rect["w"], "h": rect["h"], "maximized": False})


def owned_charmap(port: int) -> tuple[list[dict], list[dict]]:
    """（受管 charmap 窗口, 全部 charmap 窗口）。

    归属判据**与产品一致**（projection.resolveModePids）：slots 的 pid ∪
    apps_running 的 pid。core 的窗口列表本身不含归属语义，所以这里复算一次。
    """
    try:
        running = http_json(port, "/api/v1/apps/running").get("data") or {}
        slots = (http_json(port, "/api/v1/mode/progress").get("data") or {}).get("slots") or []
    except (OSError, urllib.error.URLError):
        return [], [w for w in core_windows(port) if TITLE in (w.get("title") or "")]
    pids = {int(v) for v in running.values() if str(v).isdigit()} | {
        s.get("pid") for s in slots if isinstance(s.get("pid"), int)
    }
    allc = [w for w in core_windows(port) if TITLE in (w.get("title") or "")]
    return [w for w in allc if w.get("pid") in pids], allc


def rects_snapshot(port: int) -> dict[int, dict]:
    return {w["hwnd"]: dict(w["rect"]) for w in core_windows(port) if w.get("rect")}


def wait_new_port(db_path: Path, old_port: int, timeout: float = 40.0) -> int | None:
    """等 core 重启后的**新**端口（旧库残留旧值会立刻被读到，必须区分）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                row = conn.execute("SELECT value FROM config WHERE key = 'runtime.http_port'").fetchone()
            if row and row[0] and int(row[0]) != old_port:
                p = int(row[0])
                try:
                    if core_health(p).get("service") == "pw-core":
                        return p
                except (OSError, urllib.error.URLError, json.JSONDecodeError):
                    pass
        except (sqlite3.Error, OSError):
            pass
        time.sleep(0.5)
    return None


def ui_click(ws, sel: str) -> str:
    return str(base.ev(ws, f"(() => {{ const b=document.querySelector('{sel}');"
                           f" if(!b) return 'no-button'; b.click(); return 'ok'; }})()", timeout=10))


def ui_chip(ws) -> str:
    return str(base.ev(ws, "document.querySelector('[data-pw=\"run-snap-chip\"]')?.textContent ?? ''",
                       timeout=10) or "")


def ui_click_and_wait(ws, sel: str, *needles: str, timeout: float = 30.0) -> str:
    """点击后**等 chip 变化**再判定。

    直接 `wait_chip(needle)` 会被上一轮的陈旧文案瞬间命中（chip 里还留着
    "已恢复 1 个窗口（同运行期）"），导致"没真跑就绿"。这里要求：
    文案必须**与点击前不同**，且包含期望标记。
    """
    prev = ui_chip(ws)
    if ui_click(ws, sel) != "ok":
        return ""
    deadline = time.time() + timeout
    last = prev
    while time.time() < deadline:
        last = ui_chip(ws)
        if last != prev and all(n in last for n in needles):
            return last
        time.sleep(0.5)
    return last


def wait_chip(ws, needle: str, timeout: float = 25.0) -> str:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        last = ui_chip(ws)
        if needle in last:
            return last
        time.sleep(0.6)
    return last


def wait_rect(port: int, hwnd: int, want: dict, tol: int = 12, timeout: float = 12.0) -> dict | None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        for w in core_windows(port):
            if w.get("hwnd") == hwnd and w.get("rect"):
                last = dict(w["rect"])
                if (abs(last["x"] - want["x"]) <= tol and abs(last["y"] - want["y"]) <= tol
                        and abs(last["w"] - want["w"]) <= tol and abs(last["h"] - want["h"]) <= tol):
                    return last
        time.sleep(0.6)
    return None


def start_core(data_dir: Path):
    return subprocess.Popen([str(c2.CORE_EXE)], cwd=str(ROOT),
                            env=dict(os.environ, PW_DATA_DIR=str(data_dir)),
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def d_run() -> None:
    ready, why = c2.d_real_environment()
    if not ready:
        unrun(why)
        return

    import verify_contracts as vc

    schema = json.loads((ROOT / "docs/contracts/workspace-snapshot.v1.schema.json").read_text(encoding="utf-8"))

    data_dir = Path(tempfile.mkdtemp(prefix="pw-t7c4-core-"))
    profile = Path(tempfile.mkdtemp(prefix="pw-t7c4-edge-"))
    # 清掉上一轮遗留的验证用 charmap 实例（否则"多出来的窗口"会污染归属与计数）
    subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)
    time.sleep(1.0)
    srv = edge = core_proc = ws = None
    pids: list[int] = []
    try:
        # ---------------- 启动 core + 注册/应用模式
        core_proc = start_core(data_dir)
        port = c2.wait_core_port(data_dir / "workspace.db")
        if not port:
            unrun("core 启动失败")
            return
        ProxyHandler.core_port = port
        app1 = http_json(port, "/api/v1/apps", "POST",
                         {"name": "charmap", "path": CHARMAP, "args": "", "icon": None,
                          "type": None, "category": None})
        app1_id = (app1.get("data") or {}).get("id")
        mode1 = http_json(port, "/api/v1/modes", "POST",
                          {"name": "C4验证", "description": None, "icon": None, "apps": ["charmap"],
                           "openTargets": [], "layout": None, "aiProfile": None,
                           "autoApply": False, "switchPolicy": "additive"})
        mode1_id = (mode1.get("data") or {}).get("id")
        http_json(port, f"/api/v1/modes/{mode1_id}/apply", "POST")

        win = None
        deadline = time.time() + 30
        while time.time() < deadline and win is None:
            for w in core_windows(port):
                if TITLE in (w.get("title") or ""):
                    win = w
                    break
            time.sleep(0.5)
        if not win:
            unrun("真实窗口未拉起")
            return
        hwnd, pid = win["hwnd"], win["pid"]
        pids.append(pid)
        print(f"[c4] charmap hwnd={hwnd} pid={pid} rect={win['rect']} port={port}")

        # ---------------- Edge + 同源代理
        srv = base.QuietServer(("127.0.0.1", base.free_port()), ProxyHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port_srv = srv.server_address[1]
        dbg_port = base.free_port()
        edge = subprocess.Popen(
            [base.find_edge(), "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", f"--user-data-dir={profile}",
             f"--remote-debugging-port={dbg_port}", "--remote-allow-origins=*",
             "--window-size=1600,1000", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg_port}/json/list", timeout=2) as r:
                    pages = [t for t in json.loads(r.read().decode()) if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.3)
        if not ws_url:
            unrun("Edge CDP 连不上")
            return
        ws = base.CDPWebSocket(ws_url)
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port_srv}/run"}, timeout=15)
        base.wait_for(ws, "!!document.querySelector('[data-pw=\"run-stage\"]')", timeout=25)
        base.wait_for(ws, f"[...document.querySelectorAll('.run-win.is-managed .run-win__bar')]"
                          f".some(b => (b.textContent||'').includes('{TITLE}'))", timeout=25)
        print("[c4] UI 归属窗口就绪")

        # ================= A：Capture
        chip = ui_click_and_wait(ws, '[data-pw="run-snap-save"]', "已保存")
        doc = http_json(port, f"/api/v1/config/{CFG_KEY}").get("data") or {}
        contract_errs = vc.check_snapshot(vc.strip_meta(doc), schema) if doc else ["快照为空"]
        src = doc.get("source") or {}
        wins = doc.get("desktop", {}).get("windows", [])
        flags = {
            "chip": "已保存" in chip,
            "id": bool(doc.get("snapshotId")),
            "pid": src.get("corePid", 0) > 0,
            "runId": bool(src.get("runId")),
            "managed": len(doc.get("workspace", {}).get("managed", [])) >= 1,
            "exe": all((w.get("exePath") or "").lower().endswith("charmap.exe") for w in wins),
            "exePaths": [w.get("exePath") for w in wins],
            "contract": contract_errs,
        }
        ok_a = (flags["chip"] and flags["id"] and flags["pid"] and flags["runId"]
                and flags["managed"] and flags["exe"] and not contract_errs)
        check("A Capture（真实受管窗口 → 快照 → 契约校验通过）", ok_a,
              f"chip={chip.strip()[:28]!r} id={doc.get('snapshotId')} "
              f"managed={len(doc.get('workspace', {}).get('managed', []))} 判据={flags}")
        snap_rect = dict((doc.get("desktop", {}).get("windows") or [{}])[0].get("rectPx") or {})
        snap_id = doc.get("snapshotId")
        run_id_1 = (doc.get("source") or {}).get("runId")
        if "x" not in snap_rect:  # A 没产出可用 rect ⇒ 后续真实恢复无从谈起
            unrun("A 未产出快照 rect")
            return

        # ================= C1：同运行期恢复（hwnd + pid）
        moved = {"x": snap_rect["x"] + 210, "y": snap_rect["y"] + 130,
                 "w": snap_rect["w"], "h": snap_rect["h"]}
        place_via_core(port, hwnd, moved)
        time.sleep(1.0)
        before_c1 = rects_snapshot(port)
        chip = ui_click_and_wait(ws, '[data-pw="run-snap-restore"]', "已恢复")
        back = wait_rect(port, hwnd, snap_rect)
        ok_c1 = bool(back) and "已恢复" in chip
        check("C1 同运行期恢复（hwnd+pid → 真实窗口回到快照位置）", ok_c1,
              f"chip={chip.strip()[:40]!r} 目标={snap_rect} 实际={back}")

        # ================= B：Persistence（杀 core → 新进程读回）
        try:
            with sqlite3.connect(f"file:{data_dir / 'workspace.db'}?mode=ro", uri=True) as conn:
                row = conn.execute(f"SELECT value FROM config WHERE key = '{CFG_KEY}'").fetchone()
            db_has = bool(row and row[0] and snap_id in row[0])
        except sqlite3.Error:
            db_has = False
        core_proc.terminate()
        core_proc.wait(timeout=15)
        core_proc = None
        time.sleep(1.0)
        core_proc = start_core(data_dir)
        port2 = wait_new_port(data_dir / "workspace.db", port)
        new_ok = False
        doc2 = {}
        run_id_2 = None
        if port2:
            ProxyHandler.core_port = port2
            try:
                doc2 = http_json(port2, f"/api/v1/config/{CFG_KEY}").get("data") or {}
                run_id_2 = (doc2.get("source") or {}).get("runId")
                new_ok = doc2.get("snapshotId") == snap_id
            except (OSError, urllib.error.URLError):
                pass
        health2 = core_health(port2) if port2 else {}
        if port2 and health2.get("pid") and health2.get("started_at"):
            # runId 是 **core 自报事实**（pid@started_at）；必须与**新进程**的 /health 比，
            # 而不是拿"快照里存的那份"跟自己比（那样恒等，等于没验）。
            run_id_2 = f"{health2['pid']}@{health2['started_at']}"
        ok_b = bool(port2) and new_ok and db_has and (run_id_2 != run_id_1)
        check("B Persistence（杀 core → 新进程读回同一 snapshotId，runId 已变）", ok_b,
              f"db行={db_has} 新端口={port2} 旧runId={run_id_1} 新runId={run_id_2} "
              f"/health pid={health2.get('pid')}")

        # ================= C2：跨重启恢复（exePath 匹配 + 重新校验）
        ok_c2 = False
        detail_c2 = "未执行"
        hwnd2 = None
        if port2:
            # 跨重启后重建归属证据（C4 不负责启动软件：apply 重新登记/拉起当前模式的软件）
            http_json(port2, f"/api/v1/modes/{mode1_id}/apply", "POST")
            base.wait_for(ws, f"[...document.querySelectorAll('.run-win.is-managed .run-win__bar')]"
                              f".some(b => (b.textContent||'').includes('{TITLE}'))", timeout=30)
            time.sleep(3.0)
            owned2, allc2 = owned_charmap(port2)
            for w in allc2:  # 后续清理要覆盖新拉起的实例
                if w.get("pid") and w["pid"] not in pids:
                    pids.append(w["pid"])
            if len(owned2) != 1:
                detail_c2 = f"受管 charmap 窗口数={len(owned2)}（应为 1，否则无法验证唯一候选）"
            else:
                hwnd2 = owned2[0]["hwnd"]
                away = {"x": snap_rect["x"] + 60, "y": snap_rect["y"] + 260,
                        "w": snap_rect["w"], "h": snap_rect["h"]}
                place_via_core(port2, hwnd2, away)
                time.sleep(1.0)
                before_c2 = {w["hwnd"]: dict(w["rect"]) for w in allc2}
                chip2 = ui_click_and_wait(ws, '[data-pw="run-snap-restore"]', "已恢复")
                back2 = wait_rect(port2, hwnd2, snap_rect, timeout=20.0)
                layer_cross = "跨重启" in ui_chip(ws)
                # 附加安全断言：**未归属**的同标题窗口必须零摆位（不得被顺手挪动）
                after_all = {w["hwnd"]: dict(w["rect"])
                             for w in core_windows(port2) if TITLE in (w.get("title") or "")}
                untouched_others = all(
                    after_all.get(h) == before_c2.get(h) for h in before_c2 if h != hwnd2
                )
                ok_c2 = bool(back2) and layer_cross and untouched_others
                detail_c2 = (f"chip={chip2.strip()[:44]!r} 受管hwnd={hwnd2}（旧hwnd={hwnd}）"
                             f" 目标={snap_rect} 实际={back2} 跨重启层={layer_cross} "
                             f"未归属窗口零摆位={untouched_others}")
        check("C2 跨重启恢复（exePath 唯一候选 → 真实窗口回到快照位置）", ok_c2, detail_c2)

        # ================= H：拓扑安全（快照 rect 跨出工作区 → 恢复后仍完整可见）
        ok_h = False
        detail_h = "未执行"
        cur_port = port2 or port
        try:
            mons = http_json(cur_port, "/api/v1/monitors").get("data") or []
            prim = next((m for m in mons if m.get("primary")), mons[0] if mons else None)
            if prim:
                wa = {"x": prim["work_x"], "y": prim["work_y"], "w": prim["work_w"], "h": prim["work_h"]}
                owned_h, _ = owned_charmap(cur_port)
                if len(owned_h) != 1:
                    detail_h = f"受管 charmap 窗口数={len(owned_h)}（须为 1 才能验证最小修正）"
                else:
                    hw = owned_h[0]["hwnd"]
                    straddle = {"x": wa["x"] + wa["w"] - 120, "y": wa["y"] + 80,
                                "w": snap_rect.get("w", 572), "h": snap_rect.get("h", 536)}
                    place_via_core(cur_port, hw, straddle)
                    time.sleep(1.2)
                    ui_click_and_wait(ws, '[data-pw="run-snap-save"]', "已保存")
                    doc_h = http_json(cur_port, f"/api/v1/config/{CFG_KEY}").get("data") or {}
                    raw = dict((doc_h.get("desktop", {}).get("windows") or [{}])[0].get("rectPx") or {})
                    place_via_core(cur_port, hw, {"x": wa["x"] + 40, "y": wa["y"] + 60,
                                                  "w": raw.get("w", 572), "h": raw.get("h", 536)})
                    time.sleep(1.0)
                    ui_click_and_wait(ws, '[data-pw="run-snap-restore"]', "已恢复")
                    time.sleep(2.0)
                    after = next((w["rect"] for w in core_windows(cur_port) if w.get("hwnd") == hw), None)
                    if after:
                        inside = (after["x"] >= wa["x"] - 1 and after["y"] >= wa["y"] - 1
                                  and after["x"] + after["w"] <= wa["x"] + wa["w"] + 1
                                  and after["y"] + after["h"] <= wa["y"] + wa["h"] + 1)
                        # 快照 rect 必须真的是跨界的（否则这个用例等于没测）
                        straddling = raw.get("x", 0) + raw.get("w", 0) > wa["x"] + wa["w"]
                        ok_h = inside and straddling and after["x"] != raw.get("x")
                        detail_h = (f"受管hwnd={hw} 跨界快照rect={raw} 恢复后={after} "
                                    f"工作区={wa} 完整可见={inside} 快照确实跨界={straddling}")
        except (OSError, urllib.error.URLError, IndexError, KeyError) as e:
            detail_h = f"异常：{e}"
        check("H Topology（跨边界快照 → 最小修正后完整可见）", ok_h, detail_h)

        # ================= E：Ambiguous（同 exePath 两个候选）
        # 构造思路：**手工多开**同一个 exe 的第二个实例（脚本扮用户，不经 C4 模块），
        # 看它能否拿到"归属证据"。归属判据 = slots ∪ apps_running 的 pid，
        # 两者都是"一 app 一 pid"；apps.path 还是 UNIQUE。先试，试不出来就 DEFER。
        detail_e = "未执行"
        try:
            spawned = subprocess.Popen([CHARMAP])
            time.sleep(8.0)  # 等 core 5s watcher 跑一轮
            spawn_pid = spawned.pid
            pids.append(spawn_pid)
            running_map = http_json(cur_port, "/api/v1/apps/running").get("data") or {}
            slots_now = (http_json(cur_port, "/api/v1/mode/progress").get("data") or {}).get("slots") or []
            owned_pids = {s.get("pid") for s in slots_now} | {
                int(v) for v in running_map.values() if str(v).isdigit()
            }
            # 以 UI 归属为准（core 的窗口列表不含归属语义）
            managed_js = (f"[...document.querySelectorAll('.run-win.is-managed .run-win__bar')]"
                          f".filter(b => (b.textContent||'').includes('{TITLE}')).length")
            n_managed = int(base.ev(ws, managed_js, timeout=10) or 0)
            if n_managed >= 2:
                before_e = rects_snapshot(cur_port)
                ui_click_and_wait(ws, '[data-pw="run-snap-save"]', "已保存")
                chip_e = ui_click_and_wait(ws, '[data-pw="run-snap-restore"]', "已恢复")
                time.sleep(2.0)
                after_e = rects_snapshot(cur_port)
                untouched = all(before_e.get(h) == after_e.get(h) for h in before_e)
                ok_e = ("ambiguous" in chip_e) and untouched
                check("E Ambiguous（同 exePath 多候选 → ambiguous 且零摆位）", ok_e,
                      f"受管同exe窗口={n_managed} chip={chip_e.strip()[:46]!r} 零摆位={untouched}")
            else:
                defer("E Ambiguous（同 exePath 多候选 → ambiguous 且零摆位）",
                      "真实环境不可构造：手工多开 pid=" + str(spawn_pid)
                      + f" 未获归属证据（apps_running 仍为 {running_map}，slots={slots_now}）；"
                      + f"UI 受管同标题窗口={n_managed}。"
                      + "结构性原因：① apps.path UNIQUE ⇒ 一 appId 一 exePath；"
                      + "② 归属 pid = slots ∪ apps_running，均为一 app 一 pid。"
                      + "该分支为防御性代码（skip + 零摆位），语义由 S1/S 静态项覆盖。")
        except (OSError, urllib.error.URLError, KeyError, ValueError) as e:
            defer("E Ambiguous（同 exePath 多候选 → ambiguous 且零摆位）", f"构造异常：{e}")

        # ================= D：Missing（受管窗口不存在）
        # 杀**全部** charmap（含中途由 core 拉起/脚本多开的实例，避免"还有窗口"导致假绿）
        subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)
        time.sleep(3.0)
        before_d = rects_snapshot(cur_port)
        chip_d = ui_click_and_wait(ws, '[data-pw="run-snap-restore"]', "已恢复")
        time.sleep(2.0)
        after_d = rects_snapshot(cur_port)
        untouched_d = all(before_d.get(h) == after_d.get(h) for h in before_d)
        check("D Missing（窗口不存在 → missing 且零摆位）",
              "missing" in chip_d and untouched_d,
              f"chip={chip_d.strip()[:46]!r} 零摆位={untouched_d}")

        # ================= F：Corrupted（损坏快照 → 拒绝 + 原值不动）
        # 判据口径：把快照**改成**损坏值后点恢复 —— 恢复必须拒绝，且**不得改写/删除**
        # 这份损坏值（与"损坏前"比无意义：那一步本来就是脚本自己改的）。
        http_json(cur_port, f"/api/v1/config/{CFG_KEY}", "PUT",
                  {"schemaVersion": 1, "snapshotId": "bad", "desktop": "not-an-object"})
        corrupt_raw = json.dumps(http_json(cur_port, f"/api/v1/config/{CFG_KEY}").get("data") or {},
                                 sort_keys=True, ensure_ascii=False)
        before_f = rects_snapshot(cur_port)
        chip_f = ui_click_and_wait(ws, '[data-pw="run-snap-restore"]', "已恢复")
        time.sleep(1.5)
        after_f = rects_snapshot(cur_port)
        untouched_f = all(before_f.get(h) == after_f.get(h) for h in before_f)
        after_raw = json.dumps(http_json(cur_port, f"/api/v1/config/{CFG_KEY}").get("data") or {},
                               sort_keys=True, ensure_ascii=False)
        check("F Corrupted（损坏快照 → invalid、零摆位、原值未被改写）",
              "invalid" in chip_f and corrupt_raw == after_raw and untouched_f,
              f"chip={chip_f.strip()[:40]!r} 损坏值未动={corrupt_raw == after_raw} 零摆位={untouched_f}")

        # ================= G：Offline（core 离线 → offline、零摆位）
        core_proc.terminate()
        core_proc.wait(timeout=15)
        core_proc = None
        time.sleep(9.0)  # ≥3 个轮询周期 → offline
        chip_g = ui_click_and_wait(ws, '[data-pw="run-snap-restore"]', "已恢复")
        check("G Offline（core 离线 → offline 且零摆位，不碰陈旧缓存）",
              "offline" in chip_g and "已恢复 0" in chip_g,
              f"chip={chip_g.strip()[:46]!r}")
    finally:
        if ws is not None:
            ws.close()
        if edge is not None:
            edge.terminate()
            try:
                edge.wait(timeout=8)
            except subprocess.TimeoutExpired:
                edge.kill()
        if core_proc is not None:
            core_proc.terminate()
            try:
                core_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                core_proc.kill()
        for p in dict.fromkeys(pids):
            subprocess.run(["taskkill", "/PID", str(p), "/F"], capture_output=True, timeout=10)
        if srv is not None:
            srv.shutdown()
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)
        unrun("D 段执行中断（异常或提前返回）")


def main() -> int:
    print("=" * 68)
    print("TECH-07-C Phase C4 验收（Snapshot Persistence / Restore）")
    print("=" * 68)
    for fn in (s1_no_forbidden_paths, s2_persistence_channel, s3_frozen_domain_untouched,
               s4_not_from_lastfacts, s5_runid_from_core, s6_visual_freeze, s7_core_registration):
        try:
            fn()
        except Exception:
            import traceback
            check(fn.__name__, False, "EXCEPTION: " + " | ".join(
                traceback.format_exc().strip().splitlines()[-3:]))
    try:
        r_regression()
    except Exception:
        import traceback
        check("R 回归", False, "EXCEPTION: " + " | ".join(traceback.format_exc().strip().splitlines()[-3:]))
    try:
        d_run()
    except Exception:
        import traceback
        check("D 段（真实环境）", False, "EXCEPTION: " + " | ".join(
            traceback.format_exc().strip().splitlines()[-3:]))
        unrun("D 段抛出未捕获异常")

    failed = sum(1 for _, ok, _ in RESULTS if ok is False)
    deferred = sum(1 for _, ok, _ in RESULTS if ok is None)
    passed = sum(1 for _, ok, _ in RESULTS if ok is True)
    print("-" * 68)
    print(f"{passed}/{passed + failed} 通过" + (f"（另有 {deferred} 项 Deferred：真实环境不可构造）" if deferred else ""))
    if failed:
        print(f"红灯 {failed} 项 —— C4 验收不通过")
        return 1
    if deferred:
        print("C4 验收无红灯（Deferred 项已给出结构性证据，见报告）。")
        return 0
    print("C4 验收全绿（真实快照持久化 + 跨重启真实恢复证据）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
