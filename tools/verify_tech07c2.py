#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TECH-07-C2 验收 · Workspace Runtime Observe 接线
=================================================

三段式验收（与 verify_tech02 同源的可信度纪律：就绪门是 DOM 条件，
否定断言带对照，失败不连坐，收尾零残留）：

  A 段（静态，源码）：RunView 边界 / 无窗口控制 / 无新增 token / 无新增动画 /
     无第二套 CSS / adapter 投影边界 / 无本地事实源
  R 段（回归）：verify_tech07c.py 16/16 + verify_tech02_workspace.py 11/11
  D 段（动态，真实环境）：真实 core 进程 + 真实 notepad 窗口：
     D1 core 启动（临时数据目录，不污染真实库）
     D2 真实窗口 → adapter → RunView 显示（title 证据）
     D3 UI 投影集合 ⊆ core 真实窗口集合（无伪造）
     D4 facts 轮询更新前后页面壳 DOM identity 保持（S2）
     D5 关闭 notepad → UI 投影同步消失（观察实时性）
     D6 停 core → UI 显示"未连接"，不伪造任何窗口

真实环境无法启动时（core exe 缺失 / core 起不来），D 段明确判 FAIL 并打印
「代码接线验证 ≠ 真实运行时验证」—— 不允许用空数据冒充"真实接通"。

用法：python tools/verify_tech07c2.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from http.server import SimpleHTTPRequestHandler
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import verify_tech02_workspace as base  # noqa: E402  (CDPWebSocket / find_edge / ev / wait_for)

UI = ROOT / "ui"
SRC = UI / "src"
DIST = UI / "dist"
RUNTIME = SRC / "workspace" / "runtime"
RUNVIEW = SRC / "views" / "RunView.vue"
CORE_EXE = ROOT / "core" / "target" / "debug" / "personal-workspace-core.exe"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def strip_comments(src: str) -> str:
    """剥掉 /* */ 与 // 注释行，只留真实代码（防「说明文字」误报）。"""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(
        ln for ln in src.splitlines() if not ln.strip().startswith(("*", "//"))
    )


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ================================================================ A 段（静态）

# C3 演进：windows_place 移入 adapter 白名单（RunView 仍不得出现任何 command 名），
# FORBIDDEN 收窄并新增 windows_close / apps_terminate 明确禁区。
FORBIDDEN_CMDS = [
    "windows_activate", "windows_find", "windows_rect",
    "layout_apply", "mode_restore", "modes_capture_current", "apps_launch",
    "windows_close", "apps_terminate",
]
KNOWN_CMDS = FORBIDDEN_CMDS + [
    "modes_list", "modes_current", "mode_progress", "layouts_list",
    "monitors_list", "windows_list", "apps_list", "windows_place",
    "mode_apply", "mode_cancel", "mode_exit",
]


def a1_runview_boundary() -> None:
    """RunView 不直接访问 core：零 @/api / tauri invoke / command 名。"""
    code = strip_comments(read(RUNVIEW))
    api_bad = re.findall(r"from\s+['\"]@/api[^'\"]*['\"]", code)
    tauri_bad = re.findall(r"from\s+['\"]@tauri-apps[^'\"]*['\"]", code)
    cmd_leak = sorted(c for c in KNOWN_CMDS if re.search(rf"['\"]{c}['\"]", code))
    check("A1a RunView 零 @/api import", not api_bad, str(api_bad or "无"))
    check("A1b RunView 零 tauri invoke", not tauri_bad, str(tauri_bad or "无"))
    check("A1c RunView 零 core command 名", not cmd_leak, str(cmd_leak or "无"))


def a2_no_window_control() -> None:
    """observe 段不执行窗口控制：无 drag/pointer 事件桥、无 actions 调用、零 place 路径。"""
    code = strip_comments(read(RUNVIEW))
    # C3 演进（2026-09-16）：actuate 段放开 windows_place。RunView 允许经 adapter
    # 语义接口 placeWindow 做摆位（commit 边界 = pointerup，单次提交）；仍禁止
    # mode_apply / exitMode / cancelApply 等其它 action 与任何 @/api / tauri 通道。
    place_calls = re.findall(r"placeWindow\(", code)
    acts = re.findall(r"actions\.(?:applyMode|cancelApply|exitMode)", code)
    check("A2a 摆位 commit 边界唯一（placeWindow 恰好 1 处调用）", len(place_calls) == 1, f"调用点={len(place_calls)}")
    check("A2b RunView 仅允许 placeWindow（其余 action 禁止）", not acts, str(acts or "无"))
    # adapter 侧：actuate 段位 + place 准入校验仍在
    boundary = read(RUNTIME / "boundary.ts")
    actions = strip_comments(read(RUNTIME / "actions.ts"))
    check("A2c 段位演进为 actuate（C3）", "ADAPTER_MODE: AdapterMode = 'actuate'" in boundary, "boundary.ts")
    check("A2d 段位拒绝机制仍在（ActionBlockedError）", "ActionBlockedError" in actions, "actions.ts")


def a3_no_new_tokens() -> None:
    """无新增 UI Token：视觉基线 CSS 冻结（hash 基线）+ RunView 零私造定义。

    判据说明：本仓库无 git。基线 hash = C1 验收通过时的内容指纹（C2 零改动）。
    若未来确需新增 token/动效，必须走 UI-FUSION-STANDARD 的「整段并入」流程，
    并在此登记新基线 —— 静默改基线会在这里红灯。
    """
    import hashlib
    rv = read(RUNVIEW)
    defined = re.findall(r"(--[\w-]+)\s*:", rv)
    check("A3a RunView 零私造 token 定义", not defined, str(defined[:5] or "无"))

    frozen = {
        "ui/src/styles/tokens.css": "f329f50bddd31d59",
        "ui/src/styles/motion-tokens.css": "e5e44af4aa807d38",
        "ui/src/components/ui/primitives.css": "2de660ce01c2c7d5",
        "ui/src/styles/base.css": "46d26e1bc27716a7",
    }
    bad: list[str] = []
    for rel, want in frozen.items():
        got = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16]
        if got != want:
            bad.append(f"{rel}: {got} != 基线 {want}")
    check("A3b 视觉基线 CSS 零改动（hash 冻结，C1 验收指纹）", not bad, str(bad or "四文件与基线一致"))


def a4_no_new_animation() -> None:
    """无新增动画：RunView 无 keyframes / animation / transition。"""
    rv = read(RUNVIEW)
    hits = re.findall(r"@keyframes|animation\s*:|transition\s*:", rv)
    check("A4 RunView 零动画声明（沿用基线）", not hits, str(hits or "无"))


def a5_no_second_css() -> None:
    """无第二套 CSS：styles 目录无新增文件、RunView 零硬编码色值。"""
    files = sorted(p.name for p in (SRC / "styles").glob("*.css"))
    allowed = ["base.css", "motion-tokens.css", "tokens.css"]
    extra = [f for f in files if f not in allowed]
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", strip_comments(read(RUNVIEW)))
    check("A5a styles 目录无新增 token 文件", not extra, str(extra or "无"))
    check("A5b RunView 零硬编码色值", not hexes, str(hexes[:5] or "无"))


def a6_projection_boundary() -> None:
    """adapter 投影边界：core 结构与命令名不出 runtime/；白名单含 apps_list。"""
    ok_files = all((RUNTIME / n).exists() for n in
                   ["boundary.ts", "facts.ts", "actions.ts", "index.ts", "projection.ts"])
    check("A6a runtime 五文件齐备（含 C2 projection）", ok_files, "boundary/facts/actions/index/projection")
    leaks: list[str] = []
    for n in ["facts.ts", "actions.ts", "index.ts", "projection.ts"]:
        code = strip_comments(read(RUNTIME / n))
        for c in FORBIDDEN_CMDS:
            if re.search(rf"['\"]{c}['\"]", code):
                leaks.append(f"{n}:{c}")
    check("A6b facts/actions/projection 零黑名单命令", not leaks, str(leaks or "无"))
    boundary = read(RUNTIME / "boundary.ts")
    check("A6c 白名单含 apps_list（既有读命令）", "'apps_list'" in boundary, "boundary.ts")
    # RunView 只消费投影类型（@/workspace/runtime/facts 或 runtime/index），不 import @/api/types
    rv = read(RUNVIEW)
    ok_imports = all(
        i.startswith("vue") or i.startswith("vue-router") or i.startswith("@/workspace/runtime")
        or i.startswith("@/stores/")
        for i in re.findall(r"from\s+['\"]([^'\"]+)['\"]", rv)
    )
    check("A6d RunView import 白名单（runtime 投影 + ai store）", ok_imports, "import 集合合规")


def a7_no_local_fact_source() -> None:
    """RunView 不自持第二份窗口事实（无 localStorage / 无本地 windows 缓存写入）。"""
    rv = read(RUNVIEW)
    bad = re.findall(r"localStorage|sessionStorage|indexedDB", rv)
    check("A7 RunView 零本地事实源（单一数据通道 = adapter）", not bad, str(bad or "无"))


# ================================================================ R 段（回归）


def r_regression() -> None:
    for script, expect in (("verify_tech07c.py", "16"), ("verify_tech02_workspace.py", "11")):
        p = subprocess.run(
            [sys.executable, str(TOOLS / script)], cwd=ROOT, capture_output=True, text=True, timeout=900
        )
        m = re.search(r"汇总\s*(\d+)/(\d+)", p.stdout) or re.search(r"(\d+)/(\d+)\s*通过", p.stdout)
        ok = p.returncode == 0 and m is not None and m.group(1) == expect == m.group(2)
        check(f"R {script} 回归", ok, f"exit={p.returncode} 汇总={m.group(0) if m else '未解析'}")


# ================================================================ D 段（真实环境）

class ProxyHandler(base.SPAHandler):
    """ui/dist 静态服务（含 SPA 回退）+ /api/v1 与 /health 同源代理。

    dist 以 VITE_CORE_BASE='' 构建 → request 走相对路径 → 同源 → 绕开 core
    无 CORS 头的限制；core 随机端口由此处转发。**必须继承 SPAHandler**：
    /run 深链需要回退 index.html，否则 404（diag 实测踩过）。"""

    core_port: int = 0

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/") or self.path == "/health":
            self._proxy("GET")
        else:
            super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if self.path.startswith("/api/"):
            self._proxy("POST")
        else:
            self.send_error(404)

    def _proxy(self, method: str) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.core_port}{self.path}", data=body, method=method
        )
        # C3 修复：转发 Content-Type —— urllib 默认 form-urlencoded，core 的 axum
        # Json 提取器会拒收 415；POST JSON 通路（windows_place）依赖这一行。
        ctype = self.headers.get("Content-Type")
        if ctype:
            req.add_header("Content-Type", ctype)
        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                payload = resp.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except urllib.error.HTTPError as e:
            # C3 closure audit：core 的业务错误（4xx/5xx，如 415/400）必须**如实透传**
            # 状态码与原始 body —— 不能被包装成 proxy_down，否则 UI 会把"业务失败"
            # 误判成"core 未连接（offline）"，掩盖真实错误。
            payload = e.read() or json.dumps(
                {"ok": False, "error": {"code": f"http_{e.code}", "message": str(e)}}
            ).encode()
            self.send_response(e.code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (OSError, urllib.error.URLError) as e:
            payload = json.dumps({"ok": False, "error": {"code": "proxy_down", "message": str(e)}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    def log_message(self, *args):  # 静音
        pass


def wait_core_port(db_path: Path, timeout: float = 40.0) -> int | None:
    """轮询临时库 config.runtime.http_port（core 随机端口写入点）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                row = conn.execute(
                    "SELECT value FROM config WHERE key = 'runtime.http_port'"
                ).fetchone()
            if row and row[0]:
                return int(row[0])
        except (sqlite3.Error, OSError):
            pass
        time.sleep(0.5)
    return None


def core_windows(port: int) -> list[dict]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/windows", timeout=8) as resp:
        data = json.loads(resp.read().decode())
    return data.get("data") or []


def d_real_environment() -> tuple[bool, str]:
    """返回 (真实环境可用, 说明)。core 无法启动时明确报告，D 段不伪造。"""
    if not DIST.exists() or (DIST / "index.html").stat().st_mtime < max(
        (p.stat().st_mtime for p in SRC.rglob("*") if p.is_file()), default=0
    ):
        return False, "ui/dist 不存在或早于 ui/src —— 先构建（VITE_CORE_BASE='' 同源验证构建）"
    if not CORE_EXE.exists():
        return False, f"core 未构建：{CORE_EXE} 不存在（cargo build core）"
    return True, "core exe 就绪"


def d_run() -> None:
    ready, why = d_real_environment()
    if not ready:
        for name in ("D1 core 启动", "D2 真实窗口进 UI", "D3 UI 投影不伪造", "D4 DOM identity（S2）",
                     "D5 关窗后投影消失", "D6 停 core 显示未连接"):
            check(name, False, f"NOT RUN — {why}（代码接线验证 ≠ 真实运行时验证）")
        return

    data_dir = Path(tempfile.mkdtemp(prefix="pw-t7c2-core-"))
    profile = Path(tempfile.mkdtemp(prefix="pw-t7c2-edge-"))
    port_srv = base.free_port()
    dbg_port = base.free_port()
    srv = None
    edge = core_proc = None
    ws = None
    notepad: subprocess.Popen | None = None
    np_pid: int | None = None  # 真实窗口 pid（Win11 notepad 的 Popen pid 是 stub，杀 stub 泄漏真窗口）
    try:
        # ---- D1：真实 core（临时数据目录，干净库，无 autoApply 干扰）
        env = dict(os.environ, PW_DATA_DIR=str(data_dir))
        core_proc = subprocess.Popen(
            [str(CORE_EXE)], cwd=str(ROOT), env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        port = wait_core_port(data_dir / "workspace.db")
        if port:
            ProxyHandler.core_port = port
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                    health_ok = json.loads(r.read().decode()).get("ok") is True
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                health_ok = False
        else:
            health_ok = False
        check("D1 真实 core 启动 + /health", bool(port) and health_ok,
              f"port={port} health={health_ok}（临时数据目录 {data_dir.name}）")
        if not (port and health_ok):
            for name in ("D2 真实窗口进 UI", "D3 UI 投影不伪造", "D4 DOM identity（S2）",
                         "D5 关窗后投影消失", "D6 停 core 显示未连接"):
                check(name, False, "NOT RUN — core 启动失败（代码接线验证 ≠ 真实运行时验证）")
            return

        # ---- 静态代理服务 + Edge
        srv = base.QuietServer(("127.0.0.1", port_srv), ProxyHandler)
        import threading
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        edge = subprocess.Popen(
            [base.find_edge(), "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", f"--user-data-dir={profile}",
             f"--remote-debugging-port={dbg_port}", "--remote-allow-origins=*",
             "--window-size=1600,1000", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg_port}/json/list", timeout=2) as resp:
                    pages = [t for t in json.loads(resp.read().decode()) if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.3)
        if not ws_url:
            for name in ("D2 真实窗口进 UI", "D3 UI 投影不伪造", "D4 DOM identity（S2）",
                         "D5 关窗后投影消失", "D6 停 core 显示未连接"):
                check(name, False, "NOT RUN — Edge CDP 连不上")
            return
        ws = base.CDPWebSocket(ws_url)
        ws.call("Page.enable")
        base_url = f"http://127.0.0.1:{port_srv}"
        ws.call("Page.navigate", {"url": f"{base_url}/run"}, timeout=15)
        base.wait_for(ws, "!!document.querySelector('[data-pw=\"run-stage\"]')", timeout=25)

        # ---- D2：真实软件 → core → adapter → UI
        # Win11 的 notepad.exe 是 Store stub（Popen pid 立即退出且常无窗口），
        # 依次尝试候选软件，用「启动前后 core 窗口集合的差集」反查真实 pid 与 title。
        candidates = [
            ("notepad.exe", ("记事本", "Notepad", "Text Editor")),
            ("charmap.exe", ("字符映射表", "Character Map")),
            ("winver.exe", ("关于 Windows", "About Windows")),
        ]
        before_pids = {w.get("pid") for w in core_windows(port)}
        np_title = np_pid = None
        notepad = None
        for exe, kws in candidates:
            notepad = subprocess.Popen([exe])
            deadline = time.time() + 12
            while time.time() < deadline and np_title is None:
                try:
                    for w in core_windows(port):
                        if w.get("pid") in before_pids:
                            continue
                        if any(k in (w.get("title") or "") for k in kws):
                            np_title, np_pid = w["title"], w["pid"]
                            break
                except (OSError, urllib.error.URLError):
                    pass
                time.sleep(0.5)
            if np_title:
                break
            # 候选失败：清掉 stub，试下一个
            subprocess.run(["taskkill", "/PID", str(notepad.pid), "/F"], capture_output=True, timeout=10)
        # 就绪门 = DOM 条件：UI 投影里出现该窗口的 title（2s 轮询 ≤ 3 周期）
        # 注意：Win11 notepad 的窗口标题有生命周期（初始 '记事本'，文档初始化后变成
        # '无标题 - Notepad' 等）——拿检测时刻的标题快照去匹配 UI 是竞态（单跑快、
        # 套件背靠背慢，偶发闪红）。所以每轮按 pid 实时重查 core 当前标题再匹配。
        ui_has_np = False
        if np_title:
            deadline = time.time() + 25  # 套件背靠背时冷启动/facts 轮询明显变慢（判据不变）
            while time.time() < deadline and not ui_has_np:
                cur = np_title
                try:
                    for w in core_windows(port):
                        if w.get("pid") == np_pid:
                            cur = w.get("title") or cur
                            break
                except (OSError, urllib.error.URLError):
                    pass
                lit = json.dumps(cur, ensure_ascii=False)
                ui_has_np = bool(base.ev(
                    ws,
                    f"[...document.querySelectorAll('[data-pw=\"run-stage\"] .run-win')]"
                    f".some(el => el.getAttribute('title') === {lit} || el.getAttribute('title')?.startsWith({lit}))"
                    + " || " + f"[...document.querySelectorAll('.run-win__bar')].some(el => el.textContent.includes({lit}))",
                    timeout=10,
                ))
                time.sleep(0.7)
        # 诊断增强：失败时把 UI 投影实际内容带出来（title 属性 + 卡片条文案），不再只有 ui=False
        diag_ui = ""
        if np_title and not ui_has_np:
            diag_ui = base.ev(
                ws,
                "JSON.stringify({titles: [...document.querySelectorAll('[data-pw=\"run-stage\"] .run-win')]"
                ".map(el => el.getAttribute('title')).slice(0, 16),"
                "bars: [...document.querySelectorAll('.run-win__bar')].map(el => (el.textContent||'').trim().slice(0,20)).slice(0, 16)})",
                timeout=10,
            ) or ""
        check("D2 真实窗口 → adapter → RunView 显示", bool(np_title) and ui_has_np,
              f"目标软件真实pid={np_pid} title={np_title!r} ui={ui_has_np} ui投影={diag_ui[:300]}")

        # ---- D3：UI 投影 ⊆ core 真实窗口（无伪造）
        wins = core_windows(port)
        real_titles = {w.get("title") for w in wins if w.get("title")}
        ui_titles = set(base.ev(
            ws,
            "[...document.querySelectorAll('[data-pw=\"run-stage\"] .run-win')].map(el => el.getAttribute('title').replace(' · 当前模式',''))",
            timeout=10,
        ) or [])
        forged = {t for t in ui_titles if t not in real_titles and not any(t and (t in rt or rt in t) for rt in real_titles)}
        check("D3 UI 投影不伪造（每条都能对上 core 真实窗口）", ui_titles <= real_titles or not forged,
              f"ui={len(ui_titles)} core={len(real_titles)} 伪造={sorted(forged) or '无'}")

        # ---- D4：facts 更新前后页面壳 DOM identity 保持（S2）
        probe = ("window.__t7c2 = {"
                 "stage: document.querySelector('[data-pw=\"run-stage\"]'),"
                 "appbar: document.querySelector('[data-pw=\"run-appbar\"]'),"
                 "mini: document.querySelector('[data-pw=\"run-minimap\"]'),"
                 "head: document.querySelector('.run-head')}; 'ok'")
        base.ev(ws, probe, timeout=10)
        time.sleep(5.0)  # 覆盖 ≥2 个 2s facts 轮询周期
        ident = base.ev(
            ws,
            "(() => { const p = window.__t7c2; return {"
            "stage: p.stage === document.querySelector('[data-pw=\"run-stage\"]'),"
            "appbar: p.appbar === document.querySelector('[data-pw=\"run-appbar\"]'),"
            "mini: p.mini === document.querySelector('[data-pw=\"run-minimap\"]'),"
            "head: p.head === document.querySelector('.run-head')}; })()",
            timeout=10,
        )
        check("D4 页面壳 DOM identity 保持（facts 更新不重建）",
              bool(ident) and all(ident.values()), json.dumps(ident or {}))

        # ---- D5：关闭 notepad → UI 投影同步消失（只杀我们启动的那个 pid）
        if np_pid:
            subprocess.run(["taskkill", "/PID", str(np_pid), "/F"], capture_output=True, timeout=10)
        gone = False
        deadline = time.time() + 10
        if np_title:
            lit = json.dumps(np_title, ensure_ascii=False)
            while time.time() < deadline and not gone:
                gone = not base.ev(
                    ws,
                    f"[...document.querySelectorAll('.run-win__bar')].some(el => el.textContent.includes({lit}))",
                    timeout=10,
                )
                time.sleep(0.7)
        check("D5 关闭真实窗口后 UI 投影消失（观察实时性）", gone, f"title={np_title!r}")

        # ---- D6：停 core → UI 如实显示未连接、不伪造窗口
        core_proc.terminate()
        core_proc.wait(timeout=15)
        core_proc = None
        # 实证 core 确实死了（HTTP 不再应答）—— 防止"杀了个寂寞"假跑
        core_dead = False
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
        except (OSError, urllib.error.URLError):
            core_dead = True
        time.sleep(8.0)  # ≥3 个轮询周期：facts 全失败 → offline
        # 两次采样判断 UI 是否仍在响应（冻结 = Vue 崩溃/轮询停摆的证据）
        s1 = base.ev(ws, "document.querySelectorAll('.run-win').length + '|' + (document.querySelector('.run-stage__hint')?.textContent ?? '')", timeout=10)
        time.sleep(2.3)
        s2 = base.ev(ws, "document.querySelectorAll('.run-win').length + '|' + (document.querySelector('.run-stage__hint')?.textContent ?? '')", timeout=10)
        offline = base.ev(
            ws,
            "(() => { const h = document.querySelector('.run-stage__hint');"
            "const wins = document.querySelectorAll('[data-pw=\"run-stage\"] .run-win').length;"
            "return { text: h ? h.textContent : '', wins }; })()",
            timeout=10,
        )
        ok6 = bool(offline) and "未连接" in (offline.get("text") or "") and offline.get("wins", 99) == 0
        frozen = s1 == s2
        check("D6 停 core 后 UI 显示未连接且不伪造窗口", ok6 and core_dead,
              f"coreDead={core_dead} frozen={frozen} s1={s1!r} " + json.dumps(offline or {}, ensure_ascii=False))
    finally:
        # 收尾零残留
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
        if notepad is not None and notepad.poll() is None:
            notepad.terminate()
        if np_pid:
            # 收尾零残留：杀真实窗口进程（历史泄漏源 —— 只杀 stub 导致桌面残留
            # 记事本窗口，污染后续验证轮次的窗口差集判据，D2 由此偶发闪红）
            subprocess.run(["taskkill", "/PID", str(np_pid), "/F"], capture_output=True, timeout=10)
        if np_pid:
            # 兜底清场：我们启动的记事本若仍存活则结束（只杀自己启动的 pid）
            subprocess.run(["taskkill", "/PID", str(np_pid), "/F"], capture_output=True, timeout=10)
        if srv is not None:
            srv.shutdown()
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


# ================================================================ main

def main() -> int:
    print("=" * 64)
    print("TECH-07-C Phase C2 验收（Observe 接线）")
    print("=" * 64)
    for fn in (a1_runview_boundary, a2_no_window_control, a3_no_new_tokens,
               a4_no_new_animation, a5_no_second_css, a6_projection_boundary,
               a7_no_local_fact_source):
        try:
            fn()
        except Exception:
            import traceback
            check(fn.__name__, False, "EXCEPTION: " + " | ".join(traceback.format_exc().strip().splitlines()[-3:]))
    try:
        r_regression()
    except Exception:
        import traceback
        check("R 回归", False, "EXCEPTION: " + " | ".join(traceback.format_exc().strip().splitlines()[-3:]))
    d_run()

    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print("-" * 64)
    print(f"{len(RESULTS) - failed}/{len(RESULTS)} 通过")
    if failed:
        print(f"红灯 {failed} 项 —— C2 验收不通过")
        return 1
    print("C2 验收全绿（含真实 core + 真实窗口运行时证据）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
