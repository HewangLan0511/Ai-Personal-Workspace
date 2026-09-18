"""消息级实机验证：不依赖 z-order/前台，直接把点击消息投递给 App 的 WebView2 窗口。

背景：本机桌面被用户其他窗口（WorkBuddy / 音乐播放器）占满，真实鼠标点击会落到别的窗口上，
Win32 抢前台在 Windows 上又不可靠 —— 因此改用「向 App 的 webview 窗口投递 WM_LBUTTON* 消息」。

判据（外部可读、与页面渲染强相关）：
  1. `ui.theme` 配置键（点「设置 → 外观 → 深色」后应变 dark）—— 证明设置页真实存在且可操作
  2. 窗口标题（新 UI 的 router.afterEach 会写成 `<页面> · Personal Workspace`）—— 证明路由跳转
"""
from __future__ import annotations

import ctypes
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path

TOOLS = Path(r"C:\Users\baiyu\Desktop\Personal Workspace\tools")
spec = importlib.util.spec_from_file_location("f", str(TOOLS / "_force_app_click.py"))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
u32 = f.u32

EXE = sys.argv[1] if len(sys.argv) > 1 else str(
    Path(r"C:\Users\baiyu\Desktop\Personal Workspace\core\target\release\personal-workspace-core.exe"))
TAG = "installed" if EXE[:2].upper() == "D:" else "built"

WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202

CHILDPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def children(hwnd):
    out = []

    def cb(h, _):
        cls = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(h, cls, 256)
        r = wintypes.RECT()
        u32.GetWindowRect(h, ctypes.byref(r))
        out.append({"hwnd": h, "cls": cls.value,
                    "rect": [r.left, r.top, r.right, r.bottom]})
        return True

    u32.EnumChildWindows(hwnd, CHILDPROC(cb), 0)
    return out


def find_webview(hwnd):
    """App 的 webview 是 Tauri 窗口的**子窗口**（本机实测：顶层找不到 Chrome_*，
    因为那是别的应用）。递归枚举子窗口，挑覆盖客户区的 render widget。"""
    rect = wintypes.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(rect))
    cw, ch = rect.right, rect.bottom
    best = []
    stack = [hwnd]
    seen = []
    while stack and len(seen) < 200:
        cur = stack.pop()
        for k in children(cur):
            seen.append(k)
            stack.append(k["hwnd"])
            r = k["rect"]
            w, h = r[2] - r[0], r[3] - r[1]
            if w >= cw * 0.9 and h >= ch * 0.9:
                best.append(k)
    prio = {"Chrome_RenderWidgetHostHWND": 0, "Chrome_WidgetWin_0": 1, "Chrome_WidgetWin_1": 2}
    best.sort(key=lambda k: prio.get(k["cls"], 9))
    return (best[0]["hwnd"] if best else None), seen[:10]


def msg_click(target, cx_dom, cy_dom, dpr=1.25):
    x, y = int(cx_dom * dpr), int(cy_dom * dpr)
    lp = (y << 16) | (x & 0xFFFF)
    u32.SendMessageW(target, WM_MOUSEMOVE, 0, lp)
    u32.SendMessageW(target, WM_LBUTTONDOWN, 1, lp)
    time.sleep(0.06)
    u32.SendMessageW(target, WM_LBUTTONUP, 0, lp)
    time.sleep(1.0)


def read_config(data_dir: str):
    db = Path(data_dir) / "data.db"
    if not db.exists():
        cands = list(Path(data_dir).glob("*.db"))
        if not cands:
            return {}
        db = cands[0]
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute("select key, value from config").fetchall()
        con.close()
        return {k: v for k, v in rows}
    except Exception as e:  # noqa: BLE001
        return {"__error__": str(e)}


def main():
    out = {"exe": EXE, "tag": TAG, "steps": []}
    subprocess.run(["taskkill", "/F", "/IM", "personal-workspace-core.exe"], capture_output=True)
    time.sleep(1.5)
    data_dir = tempfile.mkdtemp(prefix=f"pw-msg-{TAG}-")
    env = dict(os.environ)
    env["PW_DATA_DIR"] = data_dir
    proc = subprocess.Popen([EXE], cwd=str(Path(EXE).parent), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    win = None
    t0 = time.time()
    while time.time() - t0 < 60 and not win:
        time.sleep(1)
        win, _ = f.find_main_window(proc.pid)
    if not win:
        out["error"] = "未找到主窗口"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return
    hwnd = win[0]
    time.sleep(6)
    out["title_initial"] = f.title_of(hwnd)
    target, kids = find_webview(hwnd)
    out["webview_target"] = target
    out["webview_children"] = kids[:6]
    if not target:
        out["error"] = "未找到 App 的 webview 窗口"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    rects = f.dom_rects(1280, 800)
    nav = rects["nav"]
    # 1) 点侧栏「设置」
    it = nav.get("/settings")
    msg_click(target, it["x"], it["y"])
    out["steps"].append({"click": "侧栏 设置", "title_after": f.title_of(hwnd)})
    # 2) 点「外观」分类 → 「深色」
    sub = rects["settings"].get("subnav") or []
    ap = next((s for s in sub if "外观" in s["t"]), None)
    if ap:
        msg_click(target, ap["x"], ap["y"])
        out["steps"].append({"click": "设置 → 外观", "title_after": f.title_of(hwnd)})
    # 主题按钮坐标：直接在 dist 上量
    theme_xy = f.dom_rects(1280, 800)  # 占位（下方用独立小函数取）
    dark = None
    try:
        dark = measure_dark_button()
    except Exception as e:  # noqa: BLE001
        out["theme_measure_error"] = f"{type(e).__name__}: {e}"
    out["dark_button"] = dark
    if dark:
        msg_click(target, dark["x"], dark["y"])
        out["steps"].append({"click": "外观 → 深色", "title_after": f.title_of(hwnd)})
    time.sleep(1.5)
    cfg = read_config(data_dir)
    out["config_ui_theme"] = cfg.get("ui.theme")
    out["config_keys_sample"] = sorted(cfg.keys())[:12]
    out["title_final"] = f.title_of(hwnd)
    proc.terminate()
    (TOOLS / f"_force_msgclick_{TAG}.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))


def measure_dark_button():
    """在无头 Edge 上量出「设置 → 深色」按钮的 DOM 坐标（同源 dist、同视口）。"""
    import functools
    import http.server
    import threading
    spec2 = importlib.util.spec_from_file_location("fav", str(TOOLS / "_force_app_verify.py"))
    fav = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(fav)

    class SPAHandler(http.server.SimpleHTTPRequestHandler):
        def send_head(self):
            p = Path(self.translate_path(self.path))
            if (not p.exists() or p.is_dir()) and "." not in p.name:
                self.path = "/index.html"
            return super().send_head()

        def log_message(self, *a):
            pass

    dist = Path(r"C:\Users\baiyu\Desktop\Personal Workspace\ui\dist")
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 4921),
                                         functools.partial(SPAHandler, directory=str(dist)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = fav.free_port()
    prof = tempfile.mkdtemp(prefix="pw-measure-")
    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    p = subprocess.Popen([edge, "--headless=new", "--disable-gpu", "--no-first-run",
                          "--window-size=1280,800", "--force-device-scale-factor=1",
                          f"--user-data-dir={prof}", f"--remote-debugging-port={port}",
                          "http://127.0.0.1:4921/settings"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        cdp = fav.CDP(port, want="127.0.0.1")
        cdp.call("Page.enable")
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(3)
        return cdp.js("(() => { const b = [...document.querySelectorAll('.set-body button')]"
                      ".find(x => (x.textContent||'').trim() === '深色');"
                      " if (!b) return null; const r = b.getBoundingClientRect();"
                      " return {x: r.left + r.width/2, y: r.top + r.height/2}; })()")
    finally:
        p.terminate()
        srv.shutdown()


if __name__ == "__main__":
    main()
