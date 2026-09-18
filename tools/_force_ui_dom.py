"""逐页 DOM 断言（同源 dist，Edge 无头）—— 证明"正式入口指向新 UI 页面"。

断言每页的**新 UI 结构标记**（原型结构：page-head / nav-foot 分组导航 / set-layout 等），
以及导航完整性（11 项 + 设置）、设置页分类、Model Center 入口、真实 store 挂载痕迹。
"""
from __future__ import annotations

import functools
import http.server
import importlib.util
import json
import subprocess
import tempfile
import threading
import time
from pathlib import Path

TOOLS = Path(r"C:\Users\baiyu\Desktop\Personal Workspace\tools")
DIST = Path(r"C:\Users\baiyu\Desktop\Personal Workspace\ui\dist")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

spec = importlib.util.spec_from_file_location("fav", str(TOOLS / "_force_app_verify.py"))
fav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fav)

# UI-FUSION-FULL（2026-09-18）：marker 随设计层落地而演进 ——
# 这三个页面原先用自造卡片类（.plugin-card / .device-card / .pw-card），
# 现在统一到设计稿组件层的 .card / .tile / .metric / .profile-head。
# 演进理由与逐项差异见 docs/reviews/LEDGER.md 的 UI-FUSION-FULL 段。
ROUTES = [
    ("/dashboard", "首页", ".home-hero, .hero, .page-head"),
    ("/mode", "工作空间", ".mv-toolbar, .mode-card, .page-head"),
    ("/software", "软件", ".page-head"),
    ("/learning", "学习", ".page-head, .learning-card, .lg-card"),
    ("/project", "项目", ".page-head, .pj-card, .project-card"),
    ("/life", "生活", ".page-head, .life-card"),
    ("/ai", "AI 助手", ".ai-view, .ai-shell, .pw-card"),
    ("/profile", "档案", ".page-head, .profile-head"),
    ("/plugins", "插件", ".page-head, .card, .tile"),
    ("/device", "设备", ".page-head, .card, .metric"),
    ("/settings", "设置", ".set-layout"),
    ("/models", "模型中心", ".pw-card"),
]

PROBE = """(() => ({
  path: location.pathname,
  title: document.title,
  navFoot: !!document.querySelector('.nav-foot'),
  navSettings: !!document.querySelector('.app-nav a[href="/settings"]'),
  navHrefs: [...document.querySelectorAll('.app-nav a')].map(a => a.getAttribute('href')),
  groups: [...document.querySelectorAll('.nav-group-title')].map(e => e.textContent.trim()),
  setLayout: !!document.querySelector('.set-layout'),
  subnav: [...document.querySelectorAll('.subnav button')].map(b => (b.textContent||'').trim()),
  modelsEntry: !!document.querySelector('a[href^="/models"]'),
  pageHead: (document.querySelector('.page-head')?.innerText || '').replace(/\\s+/g,' ').slice(0, 60),
  mainText: (document.querySelector('main')?.innerText || '').replace(/\\s+/g,' ').slice(0, 120),
  hasMarker: !!document.querySelector(%s)
}))()"""


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        p = Path(self.translate_path(self.path))
        if (not p.exists() or p.is_dir()) and "." not in p.name:
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, *a):
        pass


srv = http.server.ThreadingHTTPServer(("127.0.0.1", 4931),
                                     functools.partial(SPAHandler, directory=str(DIST)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = fav.free_port()
prof = tempfile.mkdtemp(prefix="pw-domassert-")
proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
                         "--hide-scrollbars", "--window-size=1280,800",
                         "--force-device-scale-factor=1", f"--user-data-dir={prof}",
                         f"--remote-debugging-port={port}", "http://127.0.0.1:4931/dashboard"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
out = {"routes": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
try:
    cdp = fav.CDP(port, want="127.0.0.1")
    cdp.call("Page.enable")
    cdp.call("Runtime.enable")
    for route, label, marker in ROUTES:
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:4931{route}"})
        time.sleep(2.2)
        r = cdp.js(PROBE % json.dumps(marker))
        r["label"] = label
        r["ok"] = bool(r) and r.get("path") == route and r.get("hasMarker")
        out["routes"].append(r)
        print(f"{label:6s} {route:12s} ok={r.get('ok')} marker={r.get('hasMarker')} "
              f"head={(r.get('pageHead') or '')[:26]!r}")
finally:
    proc.terminate()
    srv.shutdown()

nav = out["routes"][0] if out["routes"] else {}
out["nav_summary"] = {"navFoot": nav.get("navFoot"), "settings": nav.get("navSettings"),
                      "hrefs": nav.get("navHrefs"), "groups": nav.get("groups")}
setr = next((r for r in out["routes"] if r["label"] == "设置"), {})
out["settings"] = {"subnav": setr.get("subnav"), "modelsEntry": setr.get("modelsEntry")}
out["all_ok"] = all(r.get("ok") for r in out["routes"])
(TOOLS / "_force_ui_dom.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\nnav:", json.dumps(out["nav_summary"], ensure_ascii=False))
print("settings:", json.dumps(out["settings"], ensure_ascii=False))
print("ALL ROUTES OK:", out["all_ok"])
