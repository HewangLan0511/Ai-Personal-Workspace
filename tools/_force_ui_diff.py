"""判定：正式 exe 首屏到底是"新 UI"还是"旧 UI"。

方法（不依赖 CDP，不依赖权限）：
  1. 截真实 App 首屏（Win32 屏幕抓取，已实测可用）
  2. 用 `git archive HEAD ui` 还原**旧 UI 源码**到临时目录（HEAD 里的 ui/ 即融合前的版本），
     建 node_modules junction 后 vite build → 旧 UI 静态构建
  3. 同一份当前 dist 也构建/渲染一次（新 UI 静态构建）
  4. 两者都渲染 /dashboard 到 1280x800，与 App 首屏（1600x1000）同尺度灰度比对（皮尔逊相关）
  结论判据：App 首屏与"新 UI 渲染"显著更相关 → 正式 exe 已是新 UI。
"""
from __future__ import annotations

import functools
import http.server
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from PIL import Image

ROOT = Path(r"C:\Users\baiyu\Desktop\Personal Workspace")
UI = ROOT / "ui"
TOOLS = ROOT / "tools"
OUT = TOOLS / "_force_shots"
OUT.mkdir(parents=True, exist_ok=True)
NODE = r"C:\Users\baiyu\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
VITE = str(UI / "node_modules" / "vite" / "bin" / "vite.js")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

spec = importlib.util.spec_from_file_location("fav", str(TOOLS / "_force_app_verify.py"))
fav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fav)


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        p = Path(self.translate_path(self.path))
        if (not p.exists() or p.is_dir()) and "." not in p.name:
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, *a):
        pass


def render(dist: Path, port: int, route: str, out_png: Path, css_w=1280, css_h=800):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port),
                                         functools.partial(SPAHandler, directory=str(dist)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    cport = fav.free_port()
    prof = tempfile.mkdtemp(prefix="pw-render-")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
         f"--window-size={css_w},{css_h}", "--force-device-scale-factor=1",
         f"--user-data-dir={prof}", f"--remote-debugging-port={cport}",
         f"http://127.0.0.1:{port}{route}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        cdp = fav.CDP(cport, want="127.0.0.1")
        cdp.call("Page.enable")
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": css_w, "height": css_h, "deviceScaleFactor": 1, "mobile": False})
        time.sleep(4)
        import base64
        r = cdp.call("Page.captureScreenshot", {"format": "png"})
        out_png.write_bytes(base64.b64decode(r["data"]))
        return True
    except Exception as e:  # noqa: BLE001
        print("render fail", route, e)
        return False
    finally:
        proc.terminate()
        srv.shutdown()


def build_old_dist() -> Path | None:
    """`git archive HEAD ui` → 临时目录 → junction node_modules → vite build。"""
    tmp = Path(tempfile.mkdtemp(prefix="pw-oldui-"))
    tar = subprocess.run(["git", "archive", "HEAD", "ui"], cwd=str(ROOT), capture_output=True)
    if tar.returncode != 0:
        print("git archive failed", tar.stderr[:200])
        return None
    ex = subprocess.run(["tar", "-x", "-C", str(tmp)], input=tar.stdout, capture_output=True)
    if ex.returncode != 0:
        print("tar failed", ex.stderr[:200])
        return None
    ui_tmp = tmp / "ui"
    nm = ui_tmp / "node_modules"
    j = subprocess.run(["cmd", "/c", "mklink", "/J", str(nm), str(UI / "node_modules")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print("junction:", (j.stdout or j.stderr or "").strip()[:120])
    env = dict(os.environ)
    env["VITE_CORE_BASE"] = ""
    r = subprocess.run([NODE, VITE, "build", "--outDir", "dist-old", "--emptyOutDir"],
                       cwd=str(ui_tmp), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    print("old build exit", r.returncode, (r.stdout or "").strip().splitlines()[-2:])
    dist_old = ui_tmp / "dist-old"
    return dist_old if dist_old.exists() else None


def corr(a: Image.Image, b: Image.Image) -> float:
    g1 = list(a.convert("L").resize((64, 40)).getdata())
    g2 = list(b.convert("L").resize((64, 40)).getdata())
    n = len(g1)
    m1, m2 = sum(g1) / n, sum(g2) / n
    num = sum((x - m1) * (y - m2) for x, y in zip(g1, g2))
    d1 = math.sqrt(sum((x - m1) ** 2 for x in g1))
    d2 = math.sqrt(sum((y - m2) ** 2 for y in g2))
    return num / (d1 * d2) if d1 and d2 else 0.0


def capture_app(exe: str) -> Path | None:
    """启动正式 App 并在其前台状态下截首屏（不改 z-order，避免把窗口弄丢）。"""
    sys.path.insert(0, str(TOOLS))
    import importlib
    c = importlib.import_module("_force_app_click")
    subprocess.run(["taskkill", "/F", "/IM", "personal-workspace-core.exe"], capture_output=True)
    time.sleep(1.5)
    env = dict(os.environ)
    env["PW_DATA_DIR"] = tempfile.mkdtemp(prefix="pw-appcap-")
    proc = subprocess.Popen([exe], cwd=str(Path(exe).parent), env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    win = None
    t0 = time.time()
    while time.time() - t0 < 60 and not win:
        time.sleep(1)
        win, _ = c.find_main_window(proc.pid)
    if not win:
        return None
    hwnd = win[0]
    time.sleep(6)  # 等首屏渲染完
    path = OUT / "force-app-first-screen.png"
    img, method = c.capture(hwnd, path, retries=8)
    print("app capture", method, "stdev", round(c._stdev(img), 2), "size", img.size)
    proc.terminate()
    return path


if __name__ == "__main__":
    exe = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "core" / "target" / "release" / "personal-workspace-core.exe")
    tag = "installed" if exe[:2].upper() == "D:" else "built"
    report = {"exe": exe, "tag": tag}

    app_png = capture_app(exe)
    report["app_shot"] = str(app_png) if app_png else None
    new_png = OUT / "render-new-home.png"
    render(UI / "dist", 4911, "/dashboard", new_png)
    old_dist = build_old_dist()
    old_png = OUT / "render-old-home.png"
    if old_dist:
        render(old_dist, 4912, "/dashboard", old_png)

    if app_png:
        app = Image.open(app_png)
        rep = {}
        for name, png in (("new", new_png), ("old", old_png)):
            if png.exists():
                rep[name] = round(corr(app, Image.open(png)), 4)
        report["correlation"] = rep
        # 若三张图同尺度并存，再给出目录级证据
    (TOOLS / f"_force_ui_diff_{tag}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
