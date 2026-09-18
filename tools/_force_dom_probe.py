"""快速取证：在 WebView2 调试端点的存活窗口期（启动后 ~5s 内）读 App 内的 DOM。

用来判定"正式 exe 里到底嵌的是新 UI 还是旧 UI"：
  * 新 NavSide = `.nav-foot`（设置 + 设备行）+ `.nav-group-title`
  * 旧 NavSide = 平铺链接、无 `.nav-foot`
另外读 document.title（新 UI 的 router.afterEach 会写成 `<页面> · Personal Workspace`）。
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TOOLS = Path(r"C:\Users\baiyu\Desktop\Personal Workspace\tools")
spec = importlib.util.spec_from_file_location("fav", str(TOOLS / "_force_app_verify.py"))
fav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fav)

EXE = sys.argv[1] if len(sys.argv) > 1 else str(
    Path(r"C:\Users\baiyu\Desktop\Personal Workspace\core\target\release\personal-workspace-core.exe"))
TAG = "installed" if "D:" in EXE[:3] else "built"

subprocess.run(["taskkill", "/F", "/IM", "personal-workspace-core.exe"], capture_output=True)
time.sleep(1.5)
port = fav.free_port()
env = dict(os.environ)
env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port}"
env["PW_DATA_DIR"] = tempfile.mkdtemp(prefix=f"pw-dom-{TAG}-")
p = subprocess.Popen([EXE], cwd=str(Path(EXE).parent), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

PROBE = ("(() => ({"
         " href: location.href, title: document.title,"
         " navLinks: [...document.querySelectorAll('.app-nav a')].map(a => a.getAttribute('href')),"
         " navFoot: !!document.querySelector('.nav-foot'),"
         " navGroupTitles: [...document.querySelectorAll('.nav-group-title')].map(e => e.textContent.trim()),"
         " topbar: !!document.querySelector('.topbar, .app-topbar, header'),"
         " modebar: !!document.querySelector('.mode-bar, .mv-modebar'),"
         " pageHead: !!document.querySelector('.page-head'),"
         " hero: !!document.querySelector('.home-hero, .hero, .ws-hero'),"
         " tauri: typeof window.__TAURI_INTERNALS__ !== 'undefined',"
         " bodyText: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 260)"
         "}))()")

out = {"exe": EXE, "tag": TAG, "cdp_port": port, "probes": []}
try:
    cdp = fav.CDP(port)
    out["target"] = cdp.target_url
    for i in range(3):
        try:
            out["probes"].append({"t": i, "data": cdp.js(PROBE, timeout=8)})
        except Exception as e:  # noqa: BLE001
            out["probes"].append({"t": i, "error": f"{type(e).__name__}: {e}"})
        time.sleep(1.0)
except Exception as e:  # noqa: BLE001
    out["error"] = f"{type(e).__name__}: {e}"
finally:
    p.terminate()

(TOOLS / f"_force_dom_{TAG}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2))
