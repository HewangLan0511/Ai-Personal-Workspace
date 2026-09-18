"""UI-FUSION-FORCE 实机验收：真实 Tauri App + Win32 真实鼠标点击。

为什么不用 CDP：WebView2 的远程调试端点在首屏加载后即消失（浏览器进程被替换），
无法支撑一次完整的多页点击验收。改用 **Win32 真实点击 + 窗口标题判定路由**
（App 的窗口标题跟随当前页面：`<页面> · Personal Workspace`），并逐步截图存证。

用法：
    python tools/_force_app_click.py "D:\\Personal Workspace\\personal-workspace-core.exe"
"""
from __future__ import annotations

import ctypes
import functools
import http.server
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from ctypes import wintypes
from pathlib import Path

from PIL import Image

ROOT = Path(r"C:\Users\baiyu\Desktop\Personal Workspace")
OUT = ROOT / "tools" / "_force_shots"
OUT.mkdir(parents=True, exist_ok=True)
DIST = ROOT / "ui" / "dist"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

u32 = ctypes.WinDLL("user32", use_last_error=True)
g32 = ctypes.WinDLL("gdi32", use_last_error=True)

# 必须声明 DPI 感知：否则窗口客户区尺寸是"虚拟化"值、屏幕抓取用的是物理坐标，
# 两者不匹配会导致截图错位与点击坐标整体偏移（本项目实测踩过）。
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ---- 复用 _force_app_verify 的 CDP 客户端（取 DOM 坐标用，跑在 Edge 无头里）----
spec = importlib.util.spec_from_file_location("fav", str(ROOT / "tools" / "_force_app_verify.py"))
fav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fav)

NAV = [("/dashboard", "首页"), ("/mode", "工作空间"), ("/software", "软件"),
       ("/learning", "学习"), ("/project", "项目"), ("/life", "生活"),
       ("/ai", "AI助手"), ("/profile", "档案"), ("/plugins", "插件"),
       ("/device", "设备"), ("/settings", "设置")]


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        p = Path(self.translate_path(self.path))
        if (not p.exists() or p.is_dir()) and "." not in p.name:
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, *a):
        pass


def derive_dpr(client_w: int, client_h: int):
    """窗口逻辑尺寸 = tauri.conf 的 1280x800（每次验收都是新启动、未被人为缩放），
    物理客户区 / 逻辑尺寸 = 缩放比。像素测量（侧栏边界）不可靠时以本方法为准。"""
    raw = client_w / 1280.0
    for cand in (1.0, 1.25, 1.5, 1.75, 2.0):
        if abs(raw - cand) <= 0.02:
            if abs(client_h / cand - 800) <= 24:
                return cand, {"raw": round(raw, 3), "method": "config-1280x800"}
    return None, {"raw": round(raw, 3), "method": "unmatched"}


def detect_dpr(img: Image.Image):
    """（备用）用像素测侧栏物理宽度反推 DPR（侧栏宽度是固定 CSS 值 236px）。"""
    w, h = img.size
    px = img.load()
    y0, y1 = int(h * 0.18), int(h * 0.62)
    step = max(1, (y1 - y0) // 60)

    def col_avg(x):
        acc = [0, 0, 0]
        n = 0
        for y in range(y0, y1, step):
            c = px[x, y]
            acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]
            n += 1
        return [a / n for a in acc]

    ref = col_avg(8)
    best = None
    for x in range(40, min(w, 560)):
        cur = col_avg(x)
        d = sum(abs(a - b) for a, b in zip(cur, ref))
        if d > 6:
            # 稳定性：右移 30px 仍与 ref 明显不同
            nxt = col_avg(min(w - 1, x + 30))
            if sum(abs(a - b) for a, b in zip(nxt, ref)) > 6:
                best = (x, d)
                break
    if not best:
        return None, None, None
    raw = best[0] / 236.0
    for cand in (1.0, 1.25, 1.5, 1.75, 2.0):
        if abs(raw - cand) <= 0.06:
            return cand, best[0], best[1]
    return None, best[0], best[1]


def dom_rects(css_w: int, css_h: int):
    """用 Edge 无头同源加载 dist，按 App 的真实 CSS 视口取 DOM 坐标（CSS px）。"""
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 4901),
                                         functools.partial(SPAHandler, directory=str(DIST)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = fav.free_port()
    prof = tempfile.mkdtemp(prefix="pw-force-edge-")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         f"--window-size={css_w},{css_h}",
         "--force-device-scale-factor=1", f"--user-data-dir={prof}",
         f"--remote-debugging-port={port}", "http://127.0.0.1:4901/dashboard"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        cdp = fav.CDP(port, want="127.0.0.1")
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": css_w, "height": css_h, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(3)
        nav = cdp.js("(() => { const o = {};"
                     " for (const a of document.querySelectorAll('.app-nav a')) {"
                     "  const r = a.getBoundingClientRect();"
                     "  o[a.getAttribute('href')] = {x: r.left + r.width/2, y: r.top + r.height/2,"
                     "   w: r.width, h: r.height, t: (a.textContent||'').trim()}; } return o; })()")
        settings = cdp.js(
            "(async () => { const el = [...document.querySelectorAll('.app-nav a')]"
            ".find(a => a.getAttribute('href')==='/settings');"
            " if (el) el.click(); await new Promise(r => setTimeout(r, 1200));"
            " const out = {subnav: [], models: null, sidebar: null, viewport: null};"
            " out.viewport = [innerWidth, innerHeight];"
            " const r = document.querySelector('.app-nav')?.getBoundingClientRect();"
            " if (r) out.sidebar = {w: r.width};"
            " for (const b of document.querySelectorAll('.subnav button, .set-subnav button')) {"
            "  const rb = b.getBoundingClientRect();"
            "  out.subnav.push({t: (b.textContent||'').trim(), x: rb.left + rb.width/2, y: rb.top + rb.height/2}); }"
            " const m = document.querySelector('a[href^=\"/models\"]');"
            " if (m) { const rm = m.getBoundingClientRect(); out.models = {x: rm.left + rm.width/2, y: rm.top + rm.height/2, t: (m.textContent||'').trim()}; }"
            " return out; })()")
        return {"nav": nav, "settings": settings}
    finally:
        proc.terminate()
        srv.shutdown()


# ---------------- Win32 ----------------
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def list_windows(pid: int):
    """列出该进程的所有可见顶层窗口（含类名）—— Tauri 应用常同时有控制台窗口，
    必须靠类名/标题挑出真正的 WebView 主窗口（本项目实测踩过：误把控制台当主窗口）。"""
    out = []

    def cb(hwnd, _):
        p = wintypes.DWORD()
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(hwnd):
            n = u32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 2)
            u32.GetWindowTextW(hwnd, buf, n + 2)
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(hwnd, cls, 256)
            r = wintypes.RECT()
            u32.GetClientRect(hwnd, ctypes.byref(r))
            out.append({"hwnd": hwnd, "title": buf.value, "cls": cls.value,
                        "w": r.right - r.left, "h": r.bottom - r.top})
        return True

    u32.EnumWindows(WNDENUMPROC(cb), 0)
    return out


def find_main_window(pid: int):
    """挑真正的 App 主窗口：排除控制台类，优先 WebView 宿主窗口。"""
    cands = [w for w in list_windows(pid) if w["w"] > 400 and w["h"] > 300]
    if not cands:
        return None, []
    def score(w):
        s = 0
        cls = w["cls"].lower()
        if "consolewindow" in cls:
            return -1
        if "tauri" in cls or "webview" in cls or "chrome_widgetwin" in cls:
            s += 3
        if w["title"] == "Personal Workspace" or " · Personal Workspace" in w["title"]:
            s += 3
        s += min(w["w"] * w["h"] // 200000, 4)
        return s
    best = max(cands, key=score)
    if score(best) < 0:
        return None, cands
    return (best["hwnd"], best["title"], best["w"], best["h"]), cands


def title_of(hwnd) -> str:
    n = u32.GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 2)
    u32.GetWindowTextW(hwnd, buf, n + 2)
    return buf.value


def client_origin(hwnd):
    pt = wintypes.POINT(0, 0)
    u32.ClientToScreen(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


HWND_TOPMOST = ctypes.c_void_p(-1)
HWND_NOTOPMOST = ctypes.c_void_p(-2)
u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, ctypes.c_uint]
u32.SetWindowPos.restype = wintypes.BOOL


def ensure_top(hwnd, topmost=True):
    """把 App 窗口抬到最前。

    关键：HWND_TOPMOST 必须传指针型 -1（当 int 传会被截成 0xFFFFFFFF，调用直接失败，
    上一次实测就是因此"抬不起来"，导致截图抓到别的窗口、点击落点判空）。
    """
    u32.ShowWindow(hwnd, 9)  # SW_RESTORE
    u32.SetWindowPos(hwnd, HWND_TOPMOST if topmost else HWND_NOTOPMOST,
                     0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)  # NOSIZE|NOMOVE|SHOWWINDOW
    if topmost:
        if u32.GetForegroundWindow() != hwnd:
            u32.SetForegroundWindow(hwnd)
        if u32.GetForegroundWindow() != hwnd:
            u32.SwitchToThisWindow(hwnd, True)
    time.sleep(0.5)


def class_of(hwnd) -> str:
    cls = ctypes.create_unicode_buffer(256)
    u32.GetClassNameW(hwnd, cls, 256)
    return cls.value


def point_owner(hwnd, x, y, app_pid: int | None = None):
    """落点归属判定。

    注意：WebView2 的内容是**独立的顶层窗口**（类名 Chrome_WidgetWin_1，属主进程
    msedgewebview2.exe），不是 Tauri 窗口的子窗口 —— 所以 GA_ROOT 一定不等于
    我们的 hwnd。判据 = ①根窗口就是我们；或 ②落点是 WebView2 窗口，且它的矩形
    与我们客户区高度重合（即它就是我们这个 App 的 webview，而非别的 WebView2 应用）。
    """
    pt = wintypes.POINT(int(round(x)), int(round(y)))
    h = u32.WindowFromPoint(pt)
    if not h:
        return None
    root = u32.GetAncestor(h, 2)
    if root == hwnd:
        return "ours"
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(root, ctypes.byref(pid))
    if app_pid is not None and pid.value == app_pid:
        return "app-process"
    if class_of(h).startswith("Chrome_"):
        r = wintypes.RECT()
        u32.GetWindowRect(root, ctypes.byref(r))
        cx, cy = client_origin(hwnd)
        rect = wintypes.RECT()
        u32.GetClientRect(hwnd, ctypes.byref(rect))
        cw, ch = rect.right, rect.bottom
        if (abs(r.left - cx) < 60 and abs(r.top - cy) < 60
                and abs((r.right - r.left) - cw) < 120 and abs((r.bottom - r.top) - ch) < 120):
            return "webview"
    return None


def click(px: float, py: float, guard_hwnd=None, app_pid=None):
    """真实鼠标点击。guard_hwnd 非空时先确保落点属于该 App，避免误点到用户桌面。"""
    if guard_hwnd is not None:
        if u32.GetForegroundWindow() != guard_hwnd:
            u32.SetForegroundWindow(guard_hwnd)
            time.sleep(0.4)
        if not point_owner(guard_hwnd, px, py, app_pid):
            raise RuntimeError(f"落点 ({px:.0f},{py:.0f}) 不属于 App 窗口，已中止（防误点）")
    u32.SetCursorPos(int(round(px)), int(round(py)))
    time.sleep(0.2)
    u32.mouse_event(0x0002, 0, 0, 0, 0)   # LEFTDOWN
    time.sleep(0.08)
    u32.mouse_event(0x0004, 0, 0, 0, 0)   # LEFTUP
    time.sleep(0.9)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def _stdev(img: Image.Image) -> float:
    """中心区灰阶标准差 —— 用来判断"抓到的是不是空白面"。"""
    w, h = img.size
    box = (int(w * 0.1), int(h * 0.1), int(w * 0.9), int(h * 0.9))
    small = img.crop(box).convert("L").resize((32, 24))
    vals = list(small.getdata())
    mean = sum(vals) / len(vals)
    return (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5


def _printwindow(hwnd) -> Image.Image:
    src = wintypes.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(src))
    w, h = src.right - src.left, src.bottom - src.top
    hdc = u32.GetDC(hwnd)
    mem = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    g32.SelectObject(mem, bmp)
    u32.PrintWindow(hwnd, mem, 2)  # PW_RENDERFULLCONTENT
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0)
    img = Image.frombuffer("RGBA", (w, h), buf, "raw", "BGRA", 0, 1).convert("RGB")
    g32.DeleteObject(bmp)
    g32.DeleteDC(mem)
    u32.ReleaseDC(hwnd, hdc)
    return img


def capture(hwnd, path: Path, retries: int = 15):
    """截图。WebView2 是合成渲染：PrintWindow 实测只拿到白面 → 以屏幕抓取为主。"""
    from PIL import ImageGrab
    src = wintypes.RECT()
    last = None
    for i in range(retries):
        time.sleep(0.4)
        u32.GetClientRect(hwnd, ctypes.byref(src))
        w, h = src.right - src.left, src.bottom - src.top
        x, y = client_origin(hwnd)
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
        method = "screen-grab"
        if _stdev(img) < 3:
            alt = _printwindow(hwnd)
            if _stdev(alt) >= 3:
                img, method = alt, "PrintWindow"
        last = (img, method)
        if _stdev(img) >= 3:
            last[0].save(path)
            return last
        time.sleep(0.8)
    last[0].save(path)
    return last


def sig(img: Image.Image):
    return img.convert("L").resize((16, 12)).tobytes()


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "core" / "target" / "release" / "personal-workspace-core.exe")
    tag = "installed" if ("D:/Personal Workspace" in exe.replace("\\", "/")) else "built"
    report = {"exe": exe, "tag": tag, "steps": []}

    print("[1/4] 启动真实 App…")
    subprocess.run(["taskkill", "/F", "/IM", "personal-workspace-core.exe"], capture_output=True)
    time.sleep(1.5)
    data_dir = tempfile.mkdtemp(prefix=f"pw-force-click-{tag}-")
    env = dict(os.environ)
    env["PW_DATA_DIR"] = data_dir
    proc = subprocess.Popen([exe], cwd=str(Path(exe).parent), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    win = None
    t0 = time.time()
    while time.time() - t0 < 60 and win is None:
        time.sleep(1)
        if proc.poll() is not None:
            report["error"] = f"App 退出 code={proc.returncode}"
            break
        win, cand = find_main_window(proc.pid)
        report["window_candidates"] = [{k: v for k, v in c.items() if k != "hwnd"} for c in cand]
    if win is None:
        report["error"] = report.get("error", "未找到 App 主窗口")
        (ROOT / "tools" / f"_force_click_{tag}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    hwnd, title0, cw, ch = win
    report["window"] = {"hwnd": hwnd, "title": title0, "client": [cw, ch], "data_dir": data_dir}
    if u32.GetForegroundWindow() != hwnd:
        u32.SetForegroundWindow(hwnd)
    time.sleep(2)
    report["foreground"] = (u32.GetForegroundWindow() == hwnd)
    img0, method0 = capture(hwnd, OUT / f"force-{tag}-01-first-screen.png")
    report["capture_method"] = method0
    report["first_screen"] = {"title": title_of(hwnd), "shot": f"force-{tag}-01-first-screen.png"}

    dpr, how = derive_dpr(cw, ch)
    report["dpr_detect"] = dict(how, dpr=dpr)
    if not dpr:  # 兜底：像素测侧栏边界
        d2, boundary, jump = detect_dpr(img0)
        report["dpr_detect"].update({"pixel_dpr": d2, "sidebar_px": boundary, "color_jump": jump})
        dpr = d2
    if not dpr:
        report["error"] = f"DPR 检测失败（侧栏边界 {boundary}px）"
    else:
        css_w, css_h = int(cw / dpr), int(ch / dpr)
        report["css_viewport"] = [css_w, css_h]
        print(f"[2/4] DPR={dpr} ({how}) → CSS 视口 {css_w}x{css_h}；取 DOM 坐标…")
        rects = dom_rects(css_w, css_h)
        report["dom_viewport"] = (rects.get("settings") or {}).get("viewport")
        report["dom_sidebar"] = (rects.get("settings") or {}).get("sidebar")
        report["dom_nav"] = rects["nav"]
        report["dom_settings"] = rects["settings"]

        ox, oy = client_origin(hwnd)

        def click_at(item, label):
            click(ox + item["x"] * dpr, oy + item["y"] * dpr, hwnd, proc.pid)
            return title_of(hwnd)

        print("[3/4] 逐页真实点击…")
        prev = sig(img0)
        for href, label in NAV:
            item = rects["nav"].get(href)
            if not item:
                report["steps"].append({"step": label, "ok": False, "error": "DOM 未找到该导航项"})
                continue
            t = click_at(item, label)
            name = f"force-{tag}-nav{href.replace('/', '-')}"
            img, _m = capture(hwnd, OUT / f"{name}.png")
            changed = sig(img) != prev
            prev = sig(img)
            report["steps"].append({"step": label, "href": href, "title": t,
                                    "ok": t.startswith(label), "screen_changed": changed,
                                    "shot": f"{name}.png"})
            print(f"   {label:6s} → title={t!r} ok={t.startswith(label)} 画面变化={changed}")

        # ---- 设置 → AI 与模型 → Model Center ----
        st_item = rects["nav"].get("/settings")
        if st_item:
            click_at(st_item, "设置")
        before, _m = capture(hwnd, OUT / f"force-{tag}-settings-appearance.png")
        ai_tab = next((s for s in (rects["settings"]["subnav"] or [])
                       if "AI" in s["t"] or "模型" in s["t"]), None)
        if ai_tab:
            click(ox + ai_tab["x"] * dpr, oy + ai_tab["y"] * dpr, hwnd, proc.pid)
            after, _m = capture(hwnd, OUT / f"force-{tag}-settings-ai.png")
            report["steps"].append({"step": "设置 → AI 与模型", "tab": ai_tab["t"],
                                    "screen_changed": sig(before) != sig(after),
                                    "shot": f"force-{tag}-settings-ai.png"})
            print(f"   设置 → AI 与模型 ({ai_tab['t']}) 画面变化={sig(before) != sig(after)}")
        else:
            report["steps"].append({"step": "设置 → AI 与模型", "ok": False, "error": "DOM 未找到该分类"})
        m = rects["settings"].get("models")
        if m:
            click(ox + m["x"] * dpr, oy + m["y"] * dpr, hwnd, proc.pid)
            t = title_of(hwnd)
            capture(hwnd, OUT / f"force-{tag}-models.png")
            report["steps"].append({"step": "设置 → Model Center", "clicked": m.get("t"),
                                    "title": t, "ok": t.startswith("模型中心"),
                                    "shot": f"force-{tag}-models.png"})
            print(f"   Model Center → title={t!r} ok={t.startswith('模型中心')}")
        else:
            report["steps"].append({"step": "设置 → Model Center", "ok": False, "error": "DOM 未找到入口"})

    (ROOT / "tools" / f"_force_click_{tag}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("[4/4] 报告：" + str(ROOT / "tools" / f"_force_click_{tag}.json"))


if __name__ == "__main__":
    main()
