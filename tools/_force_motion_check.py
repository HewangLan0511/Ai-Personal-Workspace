"""原型骨架 + 动效层实测（同源 dist，Edge 无头）。

判据：
  1) .page-skeleton 不再是 640px 居中窄卡（整页宽 + 左对齐 + 透明底）
  2) 页面/卡片真带动画（computed animation-name 命中原型 keyframes）
  3) 交互元素真带 transition（computed transition-duration != 0s）
  4) 壳层收编（.app-topbar 高 = --appbar-h；.app-status 用 surface-2）
  5) Motion Guard 生效：data-motion=off → 时长归零
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


class H(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        p = Path(self.translate_path(self.path))
        if (not p.exists() or p.is_dir()) and "." not in p.name:
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, *a):
        pass


PROBE = """(() => {
  const cs = el => el ? getComputedStyle(el) : null;
  const ps = document.querySelector('.page-skeleton');
  const card = document.querySelector('.card, .metric, .pw-card, .app-card, .goal-card, .plugin-cards > *');
  const head = document.querySelector('.page-head, .page-skeleton > h2, .page-bar, .aiv-head, .mv-head');
  const top = document.querySelector('.app-topbar');
  const status = document.querySelector('.app-status');
  return {
    path: location.pathname,
    ps: ps ? {w: Math.round(ps.getBoundingClientRect().width), maxW: cs(ps).maxWidth,
              margin: cs(ps).marginTop + '/' + cs(ps).marginLeft, bg: cs(ps).backgroundColor,
              align: cs(ps).textAlign} : null,
    headAnim: head ? cs(head).animationName : null,
    cardAnim: card ? {name: cs(card).animationName, dur: cs(card).animationDuration,
                      trans: cs(card).transitionDuration} : null,
    topbarH: top ? Math.round(top.getBoundingClientRect().height) : null,
    statusBg: status ? cs(status).backgroundColor : null,
    kf: [...document.styleSheets].flatMap(s => { try { return [...s.cssRules] } catch (e) { return [] } })
         .filter(r => r.type === 7).map(r => r.name)
  };
})()"""

MOTION_OFF = """(() => {
  document.documentElement.setAttribute('data-motion', 'off');
  const card = document.querySelector('.card, .metric, .pw-card, .app-card, .goal-card');
  const head = document.querySelector('.page-head, .page-skeleton > h2, .page-bar');
  const c = card ? getComputedStyle(card) : null;
  const h = head ? getComputedStyle(head) : null;
  return {cardTrans: c ? c.transitionDuration : null, cardAnim: c ? c.animationDuration : null,
          headAnim: h ? h.animationDuration : null};
})()"""

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 4951), functools.partial(H, directory=str(DIST)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = fav.free_port()
prof = tempfile.mkdtemp(prefix="pw-motion-")
proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                         "--window-size=1280,800", "--force-device-scale-factor=1",
                         f"--user-data-dir={prof}", f"--remote-debugging-port={port}",
                         "http://127.0.0.1:4951/life"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
out = {"pages": []}
try:
    cdp = fav.CDP(port, want="127.0.0.1")
    cdp.call("Page.enable")
    cdp.call("Runtime.enable")
    cdp.call("Emulation.setDeviceMetricsOverride",
             {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False})
    res = {}
    for route in ["/life", "/device", "/plugins", "/learning", "/project", "/software", "/settings", "/dashboard"]:
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:4951{route}"})
        time.sleep(2.6)
        r = cdp.js(PROBE)
        r["route"] = route
        out["pages"].append(r)
        print(f"{route:12s} ps={r.get('ps') and (r['ps']['w'], r['ps']['maxW'], r['ps']['align'])} "
              f"headAnim={r.get('headAnim')} cardAnim={r.get('cardAnim') and r['cardAnim']['name']} "
              f"trans={r.get('cardAnim') and r['cardAnim']['trans']} topbarH={r.get('topbarH')}")
    out["keyframes"] = out["pages"][-1].get("kf")
    cdp.call("Page.navigate", {"url": "http://127.0.0.1:4951/device"})
    time.sleep(2.5)
    out["motion_off"] = cdp.js(MOTION_OFF)
    print("motion=off:", json.dumps(out["motion_off"], ensure_ascii=False))
finally:
    proc.terminate()
    srv.shutdown()
(TOOLS / "_force_motion_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("\npage keyframes:", out.get("keyframes"))
