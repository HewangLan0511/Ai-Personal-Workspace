"""诊断 3：用 _force_app_verify 的 CDP 类逐步跑，定位断点。"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time

TOOLS = r"C:\Users\baiyu\Desktop\Personal Workspace\tools"
spec = importlib.util.spec_from_file_location("fav", os.path.join(TOOLS, "_force_app_verify.py"))
fav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fav)

EXE = r"C:\Users\baiyu\Desktop\Personal Workspace\core\target\release\personal-workspace-core.exe"
PORT = 9353
subprocess.run(["taskkill", "/F", "/IM", "personal-workspace-core.exe"], capture_output=True)
time.sleep(1.5)
env = dict(os.environ)
env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={PORT}"
env["PW_DATA_DIR"] = tempfile.mkdtemp(prefix="pw-diag3-")
p = subprocess.Popen([EXE], cwd=os.path.dirname(EXE), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    cdp = fav.CDP(PORT)
    print("connected:", cdp.target_url)
    steps = [
        ("Page.enable", lambda: cdp.call("Page.enable")),
        ("Runtime.enable", lambda: cdp.call("Runtime.enable")),
        ("small eval", lambda: cdp.js("location.href")),
        ("medium eval", lambda: cdp.js("document.title.length + ':' + document.readyState")),
        ("nav list eval", lambda: cdp.js("[...document.querySelectorAll('.app-nav a')].map(a=>a.getAttribute('href'))")),
        ("body text eval", lambda: cdp.js("(document.body.innerText||'').replace(/\\s+/g,' ').slice(0,200)")),
        ("screenshot", lambda: cdp.shot("diag3-shot")),
    ]
    for name, fn in steps:
        try:
            r = fn()
            print(f"OK   {name:18s} -> {str(r)[:220]}")
        except Exception as e:
            print(f"FAIL {name:18s} -> {type(e).__name__}: {e}")
            break
finally:
    p.terminate()
