"""快速 DOM 取证：真实 App 启动后，在 WebView2 调试端口存活窗口期内读页面 DOM。

判定要点（新 UI vs 旧 UI）：
  * `.nav-foot` 存在（新 NavSide 的"设置 + 设备"底栏）/ `.nav-group-title` 分组标题
  * `document.title` = `<页面> · Personal Workspace`（新 router.afterEach）
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
TAG = "installed" if EXE[:2].upper() == "D:" else "built"

PROBE = """(() => ({
  h: location.href,
  t: document.title,
  foot: !!document.querySelector('.nav-foot'),
  groups: [...document.querySelectorAll('.nav-group-title')].map(e => e.textContent.trim()),
  links: [...document.querySelectorAll('.app-nav a')].map(a => a.getAttribute('href')),
  settingsEntry: !!document.querySelector('.app-nav a[href="/settings"]'),
  pageHead: !!document.querySelector('.page-head'),
  hero: !!document.querySelector('.home-hero, .hero'),
  tauri: typeof window.__TAURI_INTERNALS__ !== 'undefined',
  txt: (document.body.innerText || '').replace(/\\s+/g, ' ').slice(0, 220)
}))()"""

subprocess.run(["taskkill", "/F", "/IM", "personal-workspace-core.exe"], capture_output=True)
time.sleep(1.5)
port = fav.free_port()
env = dict(os.environ)
env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port}"
env["PW_DATA_DIR"] = tempfile.mkdtemp(prefix=f"pw-dom-{TAG}-")
p = subprocess.Popen([EXE], cwd=str(Path(EXE).parent), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
t0 = time.time()
cdp = None
while time.time() - t0 < 15 and cdp is None:
    try:
        cdp = fav.CDP(port, wait=3)
    except Exception:
        time.sleep(0.3)

out = {"exe": EXE, "tag": TAG, "port": port, "attached_at": round(time.time() - t0, 1), "probes": []}
if cdp is None:
    out["error"] = "CDP 未连上"
else:
    for i in range(14):
        try:
            r = cdp.js(PROBE, timeout=4)
            out["probes"].append({"i": i, "t": round(time.time() - t0, 1), "r": r})
            if isinstance(r, dict) and str(r.get("h", "")).startswith("http") and r.get("links"):
                break
        except Exception as e:  # noqa: BLE001
            out["probes"].append({"i": i, "error": f"{type(e).__name__}: {str(e)[:90]}"})
            break
        time.sleep(0.4)
p.terminate()

(TOOLS / f"_force_dom_{TAG}.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(out, ensure_ascii=False, indent=2)[:2500])
