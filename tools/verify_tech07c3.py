#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TECH-07-C3 验收 · Workspace Window Actuation（windows_place 真实摆位）
=====================================================================

三段式（与 C2 同源纪律）：

  A 段（静态）：RunView 边界 / 摆位语义在 adapter / 视觉基线冻结 / 零新动画 /
     无第二套 CSS / commit 边界唯一 / 归属判据冻结（禁止按 title/exe 猜 hwnd）
  R 段（回归）：verify_tech07c.py 16/16 + verify_tech07c2.py 25/25（基线随 C3 演进）
  D 段（动态，真实环境）：真实 core + 真实 charmap 窗口 + UI 真实拖拽：
     D1 core 启动（临时数据目录）
     D2 注册软件+模式 → mode_apply 真实拉起 charmap（流水线登记 pid = 归属证据）
     D3 UI 出现 is-managed 窗口（归属判据生效）
     D4 拖拽 → before/after 真实 rect：left/top 按比例变化且方向正确
     D5 se 缩放 → width/height 真实增加（换算比例正确）
     D6 非归属窗口只读（无 handle DOM、无 grab，UI 层即拒绝）
     D7 S2：observe→drag→place→observe 全程页面壳 DOM identity 保持
     D8 停 core → offline，不伪造

用法：python tools/verify_tech07c3.py
"""
from __future__ import annotations

import json
import re
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
import verify_tech07c2 as c2  # noqa: E402  (ProxyHandler / d_real_environment / FORBIDDEN_CMDS)

UI = ROOT / "ui"
SRC = UI / "src"
RUNTIME = SRC / "workspace" / "runtime"
RUNVIEW = SRC / "views" / "RunView.vue"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return "\n".join(ln for ln in src.splitlines() if not ln.strip().startswith(("*", "//")))


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ================================================================ A 段（静态）

def a1_runview_boundary() -> None:
    code = strip_comments(read(RUNVIEW))
    api_bad = re.findall(r"from\s+['\"]@/api[^'\"]*['\"]", code)
    tauri_bad = re.findall(r"from\s+['\"]@tauri-apps[^'\"]*['\"]", code)
    cmd_leak = sorted(
        c for c in c2.KNOWN_CMDS if re.search(rf"['\"]{c}['\"]", code)
    )
    check("A1a RunView 零 @/api import", not api_bad, str(api_bad or "无"))
    check("A1b RunView 零 tauri invoke", not tauri_bad, str(tauri_bad or "无"))
    check("A1c RunView 零 core command 名", not cmd_leak, str(cmd_leak or "无"))


def a2_actuation_semantics() -> None:
    """摆位语义必须在 adapter：段位/归属校验/坐标换算都在 runtime 内。"""
    acts = strip_comments(read(RUNTIME / "actions.ts"))
    ok_api = "export async function placeWindow" in acts
    ok_bound = "belongsToMode" in acts and "manageable" in acts and "'unbound'" in acts
    ok_clamp = "clamp(" in acts and "workArea" in acts
    check("A2a placeWindow 在 adapter（段位+归属+坐标换算）", ok_api and ok_bound and ok_clamp,
          f"api={ok_api} bound={ok_bound} coord={ok_clamp}")
    # 禁止按 title/exe 猜 hwnd（actions 代码零标题匹配/进程名匹配）
    guess = re.findall(r"title\.includes|toLowerCase\(\)\.contains|\.exe\b", acts)
    check("A2b 归属判据零猜测（无 title/exe 匹配路径）", not guess, str(guess or "无"))
    # commit 边界唯一：RunView 的 placeWindow 恰好 1 处（pointerup 提交）
    rv = strip_comments(read(RUNVIEW))
    place_calls = re.findall(r"placeWindow\(", rv)
    # closure audit 加固（不增加检查项，只加严判据）：
    # - 非 placed 必须把预览写回起始几何（禁止"请求几何"滞留成"已确认几何"）；
    # - 取消路径（pointercancel / lostpointercapture）只清理、不得提交摆位；
    # - 交互监听必须成对 detach（不留残留监听）。
    rollback = ("result.status !== 'placed'" in rv) and ("writeGeometry(it.el, it.start)" in rv)
    cancel_guard = ("'pointercancel'" in rv and "'lostpointercapture'" in rv
                    and "detachInteraction" in rv)
    check("A2c RunView commit 边界唯一（1 处 + 非 placed 回滚 + cancel 不提交）",
          len(place_calls) == 1 and rollback and cancel_guard,
          f"调用点={len(place_calls)} 回滚={rollback} cancel守卫={cancel_guard}")
    # 禁区：close / terminate / restore 零出现在 adapter 代码
    bans = ["windows_close", "apps_terminate", "mode_restore", "TerminateProcess"]
    leaks = [b for b in bans if re.search(rf"['\"]?{b}['\"]?", acts)]
    check("A2d 摆位禁区（close/terminate/restore 零路径）", not leaks, str(leaks or "无"))


def a3_visual_baseline() -> None:
    import hashlib
    rv = read(RUNVIEW)
    defined = re.findall(r"(--[\w-]+)\s*:", rv)
    check("A3a RunView 零私造 token 定义", not defined, str(defined[:5] or "无"))
    frozen = {
        "ui/src/styles/tokens.css": "4741eed584a8b589",
        "ui/src/styles/motion-tokens.css": "adee6b0380a7b04d",
        "ui/src/components/ui/primitives.css": "37a8ff2d375f61c4",
        # 2026-09-18 动效对接批次有意更新（121b562804633520 → ee7d92615121cd45 → 07e79a756e1657c1）：
        # ① resync 并入设计稿的 Press 反馈规则（原被 `^button` 前缀连带排除）；
        # ② 并入 `.mt-*` 动效规范层（/motion 为其产品消费方）；
        # ③ 段前新增「壳层折叠动画的连续性补齐」块（`.nav-item`/`.device-line`）；
        # ④ ③ 的更正：同权重平局会被源序反超，选择器补成 `.shell.app-shell.mini …`。
        # 视觉取值本身未改（①② 设计稿原文，③ 终点与设计稿逐像素一致），
        # 理由与逐项说明见 verify_tech07c2.py 的 A3b。
        "ui/src/styles/base.css": "07e79a756e1657c1",
    }
    bad = []
    for rel, want in frozen.items():
        got = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16]
        if got != want:
            bad.append(f"{rel}: {got} != 基线 {want}")
    check("A3b 视觉基线 CSS 零改动（hash 冻结）", not bad, str(bad or "四文件与基线一致"))


def a4_no_new_motion() -> None:
    rv = read(RUNVIEW)
    hits = re.findall(r"@keyframes|animation\s*:|transition\s*:", rv)
    check("A4 RunView 零动画声明（0 new motion 红线）", not hits, str(hits or "无"))


def a5_no_second_css() -> None:
    files = sorted(p.name for p in (SRC / "styles").glob("*.css"))
    extra = [f for f in files if f not in ("base.css", "motion-tokens.css", "tokens.css")]
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", strip_comments(read(RUNVIEW)))
    check("A5a styles 目录无新增文件", not extra, str(extra or "无"))
    check("A5b RunView 零硬编码色值", not hexes, str(hexes[:5] or "无"))


def a6_boundary_lists() -> None:
    boundary = read(RUNTIME / "boundary.ts")
    ok_allow = all(re.search(rf"['\"]{c}['\"]", boundary) for c in
                   ("windows_place", "apps_running", "apps_list", "windows_list"))
    ok_forbid = all(re.search(rf"['\"]{c}['\"]", boundary) for c in
                    ("windows_close", "apps_terminate", "windows_activate", "layout_apply"))
    ok_mode = "ADAPTER_MODE: AdapterMode = 'actuate'" in boundary
    check("A6a 白名单含 place/运行注册表（既有命令）", ok_allow, "boundary.ts")
    check("A6b 禁区清单含 close/terminate/activate", ok_forbid, "boundary.ts")
    check("A6c 段位 actuate（C3）", ok_mode, "boundary.ts")
    leaks = []
    for n in ("facts.ts", "actions.ts", "index.ts", "projection.ts"):
        code = strip_comments(read(RUNTIME / n))
        for c in ("windows_activate", "windows_find", "windows_rect", "layout_apply",
                  "mode_restore", "modes_capture_current", "apps_launch",
                  "windows_close", "apps_terminate"):
            if re.search(rf"['\"]{c}['\"]", code):
                leaks.append(f"{n}:{c}")
    check("A6d adapter 代码零禁区命令", not leaks, str(leaks or "无"))


def a7_ownership_frozen() -> None:
    proj = strip_comments(read(RUNTIME / "projection.ts"))
    ok = ("resolveModePids" in proj and "launchedAppIds" in proj and "runningMap" in proj)
    check("A7 归属判据冻结（slots pid ∪ 运行注册表 pid，代码零猜测路径）", ok, "projection.ts")


# ================================================================ R 段（回归）


def r_regression() -> None:
    for script, expect in (("verify_tech07c.py", "16"), ("verify_tech07c2.py", "25")):
        p = subprocess.run(
            [sys.executable, str(TOOLS / script)], cwd=ROOT, capture_output=True, text=True, timeout=900
        )
        # 取【最后一个】汇总行 —— 子脚本 R 段的 detail 里会嵌套打印内层套件的汇总
        sums = re.findall(r"(\d+)/(\d+)\s*通过", p.stdout) or re.findall(r"汇总\s*(\d+)/(\d+)", p.stdout)
        ok = p.returncode == 0 and sums and sums[-1][0] == sums[-1][1] == expect
        check(f"R {script} 回归", ok,
              f"exit={p.returncode} 汇总={sums[-1] if sums else '未解析'}(最后一个)")


# ================================================================ D 段（真实 actuation）

CHARMAP = r"C:\Windows\System32\charmap.exe"


def http_json(port: int, path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def core_primary_workarea(port: int) -> dict | None:
    """主显示器工作区（物理像素）—— 归一化位移 → 物理位移的换算基准。"""
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/monitors", timeout=8) as resp:
        mons = json.loads(resp.read().decode()).get("data") or []
    return next((m for m in mons if m.get("primary")), mons[0] if mons else None)


def wait_charmap_window(port: int, timeout: float = 30.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for w in c2.core_windows(port):
                if "字符映射表" in (w.get("title") or ""):
                    return w
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.5)
    return None


def d_run() -> None:
    ready, why = c2.d_real_environment()
    if not ready:
        for name in ("D1 core 启动", "D2 模式真实拉起窗口", "D3 UI 归属生效", "D4 拖拽真实移动",
                     "D5 缩放真实变化", "D6 非归属窗口只读", "D7 S2 DOM identity", "D8 停 core 未连接"):
            check(name, False, f"NOT RUN — {why}（代码接线验证 ≠ 真实运行时验证）")
        return

    data_dir = Path(tempfile.mkdtemp(prefix="pw-t7c3-core-"))
    profile = Path(tempfile.mkdtemp(prefix="pw-t7c3-edge-"))
    dbg_port = base.free_port()
    srv = None
    edge = core_proc = None
    ws = None
    mode_id = None
    charmap_pid = None
    try:
        # ---- D1：真实 core
        import os
        core_proc = subprocess.Popen(
            [str(c2.CORE_EXE)], cwd=str(ROOT),
            env=dict(os.environ, PW_DATA_DIR=str(data_dir)),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        port = c2.wait_core_port(data_dir / "workspace.db")
        health_ok = False
        if port:
            c2.ProxyHandler.core_port = port
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as r:
                    health_ok = json.loads(r.read().decode()).get("ok") is True
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
        check("D1 真实 core 启动 + /health", bool(port) and health_ok, f"port={port}")
        if not (port and health_ok):
            for name in ("D2 模式真实拉起窗口", "D3 UI 归属生效", "D4 拖拽真实移动",
                         "D5 缩放真实变化", "D6 非归属窗口只读", "D7 S2 DOM identity", "D8 停 core 未连接"):
                check(name, False, "NOT RUN — core 启动失败（代码接线验证 ≠ 真实运行时验证）")
            return

        # ---- D2：注册 app+模式 → mode_apply（真实流水线 → 归属 pid 登记）
        reg = http_json(port, "/api/v1/apps", "POST",
                        {"name": "charmap", "path": CHARMAP, "args": "", "icon": None,
                         "type": None, "category": None})
        app_id = (reg.get("data") or {}).get("id")
        mode_reg = http_json(port, "/api/v1/modes", "POST",
                             {"name": "C3摆位验证", "description": None, "icon": None,
                              "apps": ["charmap"], "openTargets": [], "layout": None,
                              "aiProfile": None, "autoApply": False, "switchPolicy": "additive"})
        mode_id = (mode_reg.get("data") or {}).get("id")
        applied = False
        if app_id and mode_id:
            try:
                http_json(port, f"/api/v1/modes/{mode_id}/apply", "POST")
                applied = True
            except (OSError, urllib.error.URLError) as e:
                check("D2 模式真实拉起窗口", False, f"apply 失败: {e}")
        win = wait_charmap_window(port) if applied else None
        charmap_pid = win.get("pid") if win else None
        running_ok = False
        if charmap_pid:
            running = http_json(port, "/api/v1/apps/running").get("data") or {}
            running_ok = str(app_id) in {str(k) for k in running} and any(
                v == charmap_pid for v in running.values())
        check("D2 模式真实拉起窗口（归属 pid 登记）",
              bool(applied and win and running_ok),
              f"appId={app_id} modeId={mode_id} pid={charmap_pid} runningReg={running_ok}")

        # ---- 静态代理 + Edge
        srv = base.QuietServer(("127.0.0.1", base.free_port()), c2.ProxyHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port_srv = srv.server_address[1]
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
            for name in ("D3 UI 归属生效", "D4 拖拽真实移动", "D5 缩放真实变化",
                         "D6 非归属窗口只读", "D7 S2 DOM identity", "D8 停 core 未连接"):
                check(name, False, "NOT RUN — Edge CDP 连不上")
            return
        ws = base.CDPWebSocket(ws_url)
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port_srv}/run"}, timeout=15)
        base.wait_for(ws, "!!document.querySelector('[data-pw=\"run-stage\"]')", timeout=25)

        # ---- D3：UI 归属生效（is-managed 投影出现 + 2s 轮询）
        managed = base.wait_for(
            ws,
            "!!document.querySelector('.run-win.is-managed')",
            timeout=15,
        )
        check("D3 UI 归属生效（charmap 投影 = is-managed）", bool(managed), "拖拽/缩放手势已挂载")

        # ---- D4：拖拽 → 真实 left/top 变化
        stage_w = base.ev(ws, "document.querySelector('[data-pw=\"run-stage\"]').getBoundingClientRect().width", timeout=10)
        stage_h = base.ev(ws, "document.querySelector('[data-pw=\"run-stage\"]').getBoundingClientRect().height", timeout=10)
        before = next((w for w in c2.core_windows(port) if w.get("pid") == charmap_pid), None)
        drag_js = """
(() => {
  // closure audit 加固：目标必须是「归属当前模式（is-managed）」且标题=本次真实拉起的
  // 软件 —— 只认第一个 is-managed 无法证明"控制到的正是被归属的那个窗口"。
  const bars = [...document.querySelectorAll('.run-win.is-managed .run-win__bar')];
  const bar = bars.find(b => (b.textContent || '').includes('字符映射表'));
  if (!bar) return 'no-managed-charmap';
  const r = bar.getBoundingClientRect();
  const x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
  const pe = (type, x, y) => new PointerEvent(type, {clientX:x, clientY:y, bubbles:true,
    cancelable:true, isPrimary:true, pointerId:7, pointerType:'mouse', buttons:1});
  bar.dispatchEvent(pe('pointerdown', x0, y0));
  window.dispatchEvent(pe('pointermove', x0 + %d, y0 + %d));
  window.dispatchEvent(pe('pointerup', x0 + %d, y0 + %d));
  return 'ok';
})()
""" % (40, 20, 40, 20)
        drag_ret = base.ev(ws, drag_js, timeout=10)
        after = None
        deadline = time.time() + 8
        while time.time() < deadline:
            w = next((w for w in c2.core_windows(port) if w.get("pid") == charmap_pid), None)
            if w and before and (w["rect"]["x"] != before["rect"]["x"] or w["rect"]["y"] != before["rect"]["y"]):
                after = w
                break
            time.sleep(0.5)
        # 归一化位移 → 物理位移的基准 = 主显示器**工作区**（与 adapter placeWindow 同一换算）
        mon = core_primary_workarea(port)
        work_w = mon["work_w"] if mon else 0
        work_h = mon["work_h"] if mon else 0
        dx_expected = 40 / stage_w * work_w if (before and stage_w and work_w) else 0
        dy_expected = 20 / stage_h * work_h if (before and stage_h and work_h) else 0
        moved = bool(after)
        dir_ok = False
        if moved:
            dx_real = after["rect"]["x"] - before["rect"]["x"]
            dy_real = after["rect"]["y"] - before["rect"]["y"]
            dir_ok = dx_real > 0 and dy_real > 0 and abs(dx_real - dx_expected) < 40 and abs(dy_real - dy_expected) < 40
        check("D4 拖拽 → 真实窗口 left/top 变化且方向正确", moved and dir_ok,
              f"target={drag_ret} before=({before['rect']['x']},{before['rect']['y']}) "
              f"after=({after['rect']['x'] if after else '?'},{after['rect']['y'] if after else '?'}) "
              f"期望≈({dx_expected:.0f},{dy_expected:.0f})")

        # ---- D5：se 缩放 → 真实 width/height 增加
        base_w = after["rect"]["w"] if after else (before["rect"]["w"] if before else 0)
        base_h = after["rect"]["h"] if after else (before["rect"]["h"] if before else 0)
        resize_js = """
(() => {
  const wins = [...document.querySelectorAll('.run-win.is-managed')];
  const win = wins.find(w => (w.querySelector('.run-win__bar')?.textContent || '').includes('字符映射表'));
  const h = win && win.querySelector('.run-win__rz--se');
  if (!h) return 'no-managed-charmap-handle';
  const r = h.getBoundingClientRect();
  const x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
  const pe = (type, x, y) => new PointerEvent(type, {clientX:x, clientY:y, bubbles:true,
    cancelable:true, isPrimary:true, pointerId:8, pointerType:'mouse', buttons:1});
  h.dispatchEvent(pe('pointerdown', x0, y0));
  window.dispatchEvent(pe('pointermove', x0 + %d, y0 + %d));
  window.dispatchEvent(pe('pointerup', x0 + %d, y0 + %d));
  return 'ok';
})()
""" % (80, 60, 80, 60)
        resize_ret = base.ev(ws, resize_js, timeout=10)
        grown = None
        deadline = time.time() + 8
        while time.time() < deadline:
            w = next((w for w in c2.core_windows(port) if w.get("pid") == charmap_pid), None)
            if w and (w["rect"]["w"] > base_w + 10 or w["rect"]["h"] > base_h + 10):
                grown = w
                break
            time.sleep(0.5)
        dw_exp = 80 / stage_w * work_w if (stage_w and work_w) else 0
        dh_exp = 60 / stage_h * work_h if (stage_h and work_h) else 0
        resized = bool(grown)
        size_ok = False
        if resized:
            dw = grown["rect"]["w"] - base_w
            dh = grown["rect"]["h"] - base_h
            size_ok = dw > 0 and dh > 0 and abs(dw - dw_exp) < 60 and abs(dh - dh_exp) < 60
        check("D5 缩放 → 真实窗口 width/height 增加", resized and size_ok,
              f"target={resize_ret} w:{base_w}->{grown['rect']['w'] if grown else '?'} "
              f"h:{base_h}->{grown['rect']['h'] if grown else '?'} 期望≈(+{dw_exp:.0f},+{dh_exp:.0f})")

        # ---- D6：非归属窗口只读（UI 层即拒绝：无 handle、无 grab）
        ro = base.ev(
            ws,
            "(() => { const other = document.querySelector('.run-win:not(.is-managed)');"
            " if (!other) return {other:false, handles:0, grab:false};"
            " return { other: true,"
            "  handles: other.querySelectorAll('.run-win__rz').length,"
            "  grab: !!other.querySelector('.run-win__bar.is-grab') }; })()",
            timeout=10,
        )
        check("D6 非归属窗口只读（零手势、UI 层即拒绝）",
              bool(ro) and (not ro.get("other") or (ro.get("handles") == 0 and not ro.get("grab"))),
              json.dumps(ro or {}, ensure_ascii=False))

        # ---- D7：S2 —— observe→drag→place→observe 全程 DOM identity
        probe = ("window.__t7c3 = {"
                 "stage: document.querySelector('[data-pw=\"run-stage\"]'),"
                 "head: document.querySelector('.run-head'),"
                 "appbar: document.querySelector('[data-pw=\"run-appbar\"]'),"
                 "mini: document.querySelector('[data-pw=\"run-minimap\"]')}; 'ok'")
        base.ev(ws, probe, timeout=10)
        time.sleep(4.0)  # ≥2 个 facts 轮询周期（覆盖 place 后 observe）
        ident = base.ev(
            ws,
            "(() => { const p = window.__t7c3; return {"
            "stage: p.stage === document.querySelector('[data-pw=\"run-stage\"]'),"
            "head: p.head === document.querySelector('.run-head'),"
            "appbar: p.appbar === document.querySelector('[data-pw=\"run-appbar\"]'),"
            "mini: p.mini === document.querySelector('[data-pw=\"run-minimap\"]')}; })()",
            timeout=10,
        )
        check("D7 S2 页面壳 DOM identity 保持（observe→drag→place→observe）",
              bool(ident) and all(ident.values()), json.dumps(ident or {}))

        # ---- D8：停 core → offline 且不伪造
        core_proc.terminate()
        core_proc.wait(timeout=15)
        core_proc = None
        # 实证 core 确实死了（HTTP 不再应答）—— 防止"杀了个寂寞"假跑（同 C2 D6 修复）
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
        ok8 = bool(offline) and "未连接" in (offline.get("text") or "") and offline.get("wins", 99) == 0
        check("D8 停 core 后 UI 显示未连接且不伪造窗口", ok8 and core_dead and s1 == s2,
              f"coreDead={core_dead} frozen={s1 == s2} s1={s1!r} " + json.dumps(offline or {}, ensure_ascii=False))
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
        if charmap_pid:
            subprocess.run(["taskkill", "/PID", str(charmap_pid), "/F"], capture_output=True, timeout=10)
        if srv is not None:
            srv.shutdown()
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


def main() -> int:
    print("=" * 64)
    print("TECH-07-C Phase C3 验收（Window Actuation · windows_place）")
    print("=" * 64)
    for fn in (a1_runview_boundary, a2_actuation_semantics, a3_visual_baseline,
               a4_no_new_motion, a5_no_second_css, a6_boundary_lists, a7_ownership_frozen):
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
        print(f"红灯 {failed} 项 —— C3 验收不通过")
        return 1
    print("C3 验收全绿（真实窗口摆位证据：before != after 且方向正确）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
