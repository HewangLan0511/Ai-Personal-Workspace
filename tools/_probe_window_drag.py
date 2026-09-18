#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性探针：RunView 的**窗口拖拽视觉反馈**（需求 4）在真实产物 + 真实窗口上通不通。

与既有脚本的分工（别重复劳动）
  · `verify_tech07c3` D7/S2 已用同一套 pointer 事件链证明：拖拽 → 真实窗口落位 → 壳 DOM identity 不变。
    它管的是**行为正确性**（真的调了一次 windows_place、坐标换算对）。
  · 本探针管**视觉反馈链路**：起手抬起 / 其余退后 / 尺寸 HUD / 落位缓动窗口 / 落位高亮，
    这些是本轮新接的设计稿行为（`.carried` `.carrying` `.win-size` `.just-swap` + 限时 transition）。
    之前它们只有静态接线复核 —— 而静态复核抓不住"类在 CSS 里、调用点丢"。

判据
  1) 起手：窗口加 `.carried`、舞台加 `.carrying`、出现 `.win-size` HUD（文案 = W × H）、body 光标 grabbing
  2) 跟随：窗口实际位移 ≈ 指针位移（±6px；设计稿红线 = 拖拽期 1:1 跟手，不允许缓动拖后腿）
  3) 松手：`.carried`/`.carrying` 撤掉、HUD 进 `.out` 淡出、窗口加 `.just-swap` 落位高亮
  4) 松手：窗口 inline `transition` 含 left/top 且是时长（落位缓动窗口开启）
  5) 缓动结束：inline `transition` 被清空（不把全局过渡留给下一次拖拽）
  6) 松手：body 光标复原

用法：python tools/_probe_window_drag.py
⚠️ 会临时拉起 charmap 与一个 core（临时数据目录），结束时清理；期间不要同时跑其它 D 段脚本。
"""
from __future__ import annotations

import json
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
import verify_tech07c4 as c4  # noqa: E402

UI = ROOT / "ui"
DIST = UI / "dist"
SRC = UI / "src"
CHARMAP = c4.CHARMAP
TITLE = c4.TITLE
DX, DY = 140, 90

ROWS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    ROWS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


PE = """
const pe = (type, x, y) => new PointerEvent(type, {
  bubbles: true, cancelable: true, composed: true, view: window,
  clientX: x, clientY: y, pointerId: 7, pointerType: 'mouse', isPrimary: true,
  buttons: type === 'pointerup' ? 0 : 1, button: 0,
});
"""

BEGIN = PE + r"""
(() => {
  const bar = [...document.querySelectorAll('.win.run-win .win-bar.run-win__bar')]
    .find(b => (b.textContent || '').includes(TITLE_PLACEHOLDER));
  if (!bar) return { error: '找不到该窗口的拖动条' };
  const win = bar.closest('.win.run-win');
  const stage = document.querySelector('[data-pw="run-stage"]');
  const r = bar.getBoundingClientRect();
  const p = { x0: Math.round(r.left + r.width / 2), y0: Math.round(r.top + r.height / 2) };
  window.__pd = { win, bar, stage, ...p };
  window.__rect0 = win.getBoundingClientRect();
  window.__style0 = { left: win.style.left, top: win.style.top };
  bar.dispatchEvent(pe('pointerdown', p.x0, p.y0));
  const hud = win.querySelector('.win-size');
  return {
    carried: win.classList.contains('carried'),
    carrying: stage.classList.contains('carrying'),
    hud: hud ? hud.textContent.trim() : null,
    hudHasOut: hud ? hud.classList.contains('out') : null,
    cursor: document.body.style.cursor,
    rect0: { left: window.__rect0.left, top: window.__rect0.top },
  };
})()
"""

MOVE = PE + r"""
(() => {
  const p = window.__pd;
  window.dispatchEvent(pe('pointermove', p.x0 + DX_PLACEHOLDER, p.y0 + DY_PLACEHOLDER));
  const r = p.win.getBoundingClientRect();
  const hud = p.win.querySelector('.win-size');
  return {
    dx: Math.round(r.left - window.__rect0.left),
    dy: Math.round(r.top - window.__rect0.top),
    hud: hud ? hud.textContent.trim() : null,
    carried: p.win.classList.contains('carried'),
    inlineLeft: p.win.style.left,
    transition: p.win.style.transition,
  };
})()
"""

UP = PE + r"""
(() => {
  const p = window.__pd;
  window.dispatchEvent(pe('pointerup', p.x0 + DX_PLACEHOLDER, p.y0 + DY_PLACEHOLDER));
  const hud = p.win.querySelector('.win-size');
  return {
    carried: p.win.classList.contains('carried'),
    carrying: p.stage.classList.contains('carrying'),
    flashed: p.win.classList.contains('just-swap'),
    hudOut: hud ? hud.classList.contains('out') : null,
    transition: p.win.style.transition,
    cursor: document.body.style.cursor,
    rect: (() => { const r = p.win.getBoundingClientRect(); return { left: Math.round(r.left), top: Math.round(r.top) }; })(),
  };
})()
"""

AFTER_SETTLE = r"""
(() => {
  const win = window.__pd.win;
  return {
    transition: win.style.transition,
    hudGone: !win.querySelector('.win-size'),
    carried: win.classList.contains('carried'),
  };
})()
"""


def main() -> int:
    if not (DIST / "index.html").exists():
        print(f"FATAL ui/dist 不存在：{DIST}")
        return 2
    newest_src = max((p.stat().st_mtime for p in SRC.rglob("*") if p.is_file()), default=0)
    if (DIST / "index.html").stat().st_mtime < newest_src:
        print("FATAL ui/dist 早于 ui/src —— 先构建（tools/_fusion_build.py，VITE_CORE_BASE='' 同源）")
        return 2

    data_dir = Path(tempfile.mkdtemp(prefix="pw-windrag-core-"))
    profile = Path(tempfile.mkdtemp(prefix="pw-windrag-edge-"))
    subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)
    time.sleep(1.0)
    core_proc = edge = ws = srv = None
    try:
        core_proc = c4.start_core(data_dir)
        port = c2.wait_core_port(data_dir / "workspace.db")
        if not port:
            check("临时 core 启动", False, "wait_core_port 超时")
            return 1
        c4.ProxyHandler.core_port = port
        c4.http_json(port, "/api/v1/apps", "POST",
                     {"name": "charmap", "path": CHARMAP, "args": "", "icon": None,
                      "type": None, "category": None})
        m = c4.http_json(port, "/api/v1/modes", "POST",
                         {"name": "拖拽探针", "description": None, "icon": None,
                          "apps": ["charmap"], "openTargets": [], "layout": None,
                          "aiProfile": None, "autoApply": False, "switchPolicy": "additive"})
        c4.http_json(port, f"/api/v1/modes/{(m.get('data') or {}).get('id')}/apply", "POST")
        win = None
        deadline = time.time() + 30
        while time.time() < deadline and win is None:
            for w in c4.core_windows(port):
                if TITLE in (w.get("title") or ""):
                    win = w
                    break
            time.sleep(0.5)
        if not win:
            check("真实 charmap 窗口拉起", False, "30s 内未出现")
            return 1
        check("真实 charmap 窗口拉起", True, f"hwnd={win['hwnd']} rect={win['rect']}")

        srv = base.QuietServer(("127.0.0.1", base.free_port()), c4.ProxyHandler)
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
            check("Edge CDP 连上", False, "60 次重试失败")
            return 1

        ws = base.CDPWebSocket(ws_url)
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port_srv}/run"}, timeout=15)
        base.wait_for(ws, "!!document.querySelector('[data-pw=\"run-stage\"]')", timeout=25)
        base.wait_for(
            ws,
            "[...document.querySelectorAll('.win.run-win .win-bar.run-win__bar')]"
            f".some(b => (b.textContent || '').includes({json.dumps(TITLE, ensure_ascii=False)}))",
            timeout=25)
        check("RunView 里出现该窗口的拖动条（受管窗口已投影）", True, TITLE)

        begun = base.ev(ws, BEGIN.replace("TITLE_PLACEHOLDER", json.dumps(TITLE, ensure_ascii=False)))
        if not isinstance(begun, dict) or begun.get("error"):
            check("起手 pointerdown 命中拖动条", False, str(begun))
            return 1
        check("起手：窗口加 `.carried`（抬起）", begun["carried"], f".carried={begun['carried']}")
        check("起手：舞台加 `.carrying`（其余退后）", begun["carrying"], f".carrying={begun['carrying']}")
        check("起手：出现 `.win-size` HUD 且文案为 W × H",
              bool(begun["hud"]) and "×" in (begun["hud"] or ""), f"HUD={begun['hud']!r}")
        check("起手：body 光标 = grabbing（按下反馈）", begun["cursor"] == "grabbing",
              f"cursor={begun['cursor']!r}")

        moved = base.ev(ws, MOVE.replace("DX_PLACEHOLDER", str(DX)).replace("DY_PLACEHOLDER", str(DY)))
        if not isinstance(moved, dict):
            check("拖动 pointermove 取回几何", False, str(moved))
            return 1
        ok_follow = abs(moved["dx"] - DX) <= 6 and abs(moved["dy"] - DY) <= 6
        check(f"跟随：窗口位移 ≈ 指针位移（{DX},{DY}，±6px；拖拽期 1:1 跟手）",
              ok_follow, f"实得 dx={moved['dx']} dy={moved['dy']} inlineLeft={moved['inlineLeft']!r}")
        check("拖动中：窗口仍带 `.carried`、HUD 仍是尺寸文案",
              moved["carried"] and "×" in (moved["hud"] or ""),
              f"carried={moved['carried']} HUD={moved['hud']!r}")

        up = base.ev(ws, UP.replace("DX_PLACEHOLDER", str(DX)).replace("DY_PLACEHOLDER", str(DY)))
        if not isinstance(up, dict):
            check("松手 pointerup 取回状态", False, str(up))
            return 1
        check("松手：`.carried` 与 `.carrying` 均已撤掉",
              (not up["carried"]) and (not up["carrying"]),
              f"carried={up['carried']} carrying={up['carrying']}")
        check("松手：`.win-size` HUD 进入 `.out` 淡出", up["hudOut"] is True, f"hud.out={up['hudOut']}")
        check("松手：窗口加 `.just-swap`（落位高亮）", up["flashed"], f"just-swap={up['flashed']}")
        tr = up["transition"] or ""
        check("松手：inline transition 含 left/top 且为时长（落位缓动窗口开启）",
              ("left" in tr and "top" in tr and "0ms" not in tr), f"transition={tr[:90]!r}")
        check("松手：body 光标复原（不再是 grabbing）", up["cursor"] != "grabbing",
              f"cursor={up['cursor']!r}")

        time.sleep(1.1)  # --mt-dur-window 560ms + 60ms 余量
        aft = base.ev(ws, AFTER_SETTLE)
        if isinstance(aft, dict):
            check("缓动结束：inline transition 已清空（不残留给下一次拖拽）",
                  not (aft["transition"] or ""), f"transition={aft['transition']!r}")
            check("缓动结束：HUD 已从 DOM 移除（220ms 后 remove）", aft["hudGone"],
                  f"hudGone={aft['hudGone']}")
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass
        subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)
        if edge:
            edge.terminate()
            try:
                edge.wait(timeout=10)
            except subprocess.TimeoutExpired:
                edge.kill()
        if core_proc:
            core_proc.terminate()
            try:
                core_proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                core_proc.kill()
        if srv:
            srv.shutdown()

    bad = [n for n, ok, _ in ROWS if not ok]
    print(f"\n=== 汇总 {len(ROWS) - len(bad)}/{len(ROWS)} ===")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
