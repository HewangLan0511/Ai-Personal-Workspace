"""壳层 appbar 化实测（同源 dist，Edge 无头 + CDP）。

判据（UI 保真收口 · 第二批 ①）：
  1) 顶部壳层是**一条** appbar：`.mode-bar` 的几何完全落在 `.app-titlebar` 内，
     且页面顶部不存在第二条全宽横条（旧结构是 TopBar + ModeBar 两条叠放）
  2) 原型 .titlebar 形态到位：容器底 = --bg-app、无下边框、高 = --appbar-h；
     `.app-main` 底 = --bg-canvas（色阶分层）
  3) 模式栏就地收编生效：`.mode-bar` 计算值 = 透明底 / 零下边框 / min-height 0
     （证明 base.css 的 0,3,0 覆盖赢了 ModeBar.vue 的 scoped 0,2,0 —— 该文件零改动）
  4) 原型原子类到位：`.tb-title` / `.tb-btn` / `.tb-context` / 动作区三个控件
  5) 验收依赖未丢：顶栏 DOM 仍含「设置」「最小化」两串文本 + `a[href="/settings"]`
"""
from __future__ import annotations

import functools
import http.server
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# 路径全部由 __file__ 推导；Edge 用环境变量定位 —— 不写死盘符/用户名
# （门禁 A020/A021 对 tools/ 同样生效，本文件零命中）。
ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
DIST = ROOT / "ui" / "dist"

_EDGE_SUBPATHS = (
    ("Microsoft", "Edge", "Application", "msedge.exe"),
    ("Microsoft", "Edge Beta", "Application", "msedge.exe"),
    ("Microsoft", "Edge Dev", "Application", "msedge.exe"),
)


def find_edge() -> str | None:
    for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if not base:
            continue
        for rel in _EDGE_SUBPATHS:
            p = Path(base).joinpath(*rel)
            if p.exists():
                return str(p)
    return shutil.which("msedge")


EDGE = find_edge()
if EDGE is None:
    raise SystemExit("未找到 Edge，无法无头渲染")

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
  const rect = el => { if(!el) return null; const r = el.getBoundingClientRect();
    return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
            bottom: Math.round(r.bottom)}; };
  const tb = document.querySelector('.app-titlebar');
  const top = document.querySelector('.app-topbar');
  const mb = document.querySelector('.mode-bar');
  const main = document.querySelector('.app-main');
  const btn = document.querySelector('.tb-actions .tb-btn');
  const title = document.querySelector('.tb-title');
  const ctx = document.querySelector('.tb-context');
  const sel = document.querySelector('.mode-bar__select');
  const tbR = rect(tb), mbR = rect(mb), topR = rect(top);
  return {
    path: location.pathname,
    titlebar: tb ? {h: tbR.h, bg: cs(tb).backgroundColor, gap: cs(tb).gap,
                    borderBottom: cs(tb).borderBottomWidth, pad: cs(tb).padding, rect: tbR} : null,
    topbar: top ? {h: topR.h, bg: cs(top).backgroundColor, border: cs(top).borderBottomWidth,
                   rect: topR} : null,
    modebar: mb ? {h: mbR.h, y: mbR.y, bottom: mbR.bottom, bg: cs(mb).backgroundColor,
                   borderBottom: cs(mb).borderBottomWidth, minHeight: cs(mb).minHeight,
                   fontSize: cs(mb).fontSize,
                   scoped: [...mb.attributes].some(a => a.name.startsWith('data-v-')),
                   rect: mbR} : null,
    modebarSelectH: sel ? Math.round(sel.getBoundingClientRect().height) : null,
    mainBg: main ? cs(main).backgroundColor : null,
    tbTitle: title ? {fs: cs(title).fontSize, fw: cs(title).fontWeight, text: title.textContent.trim()} : null,
    tbContext: ctx ? ctx.textContent.replace(/\\s+/g,' ').trim() : null,
    tbBtn: btn ? {h: Math.round(btn.getBoundingClientRect().height), border: cs(btn).borderBottomWidth,
                  bg: cs(btn).backgroundColor} : null,
    actions: [...document.querySelectorAll('.tb-actions .tb-btn')].map(b => ({
      tag: b.tagName.toLowerCase(), text: b.textContent.trim(), href: b.getAttribute('href')})),
    topbarText: (top?.innerText || '').replace(/\\s+/g,' ').trim(),
    settingsLink: !!document.querySelector('.app-topbar a[href="/settings"]'),
    // 右缘对齐：spacer 必须有展开空间，且最后一个动作贴右缘（≤24px 内）
    spacerW: Math.round((document.querySelector('.tb-spacer')?.getBoundingClientRect().width) || 0),
    actionsRightGap: (() => {
      const a = [...document.querySelectorAll('.tb-actions .tb-btn')];
      if (!a.length) return null;
      return Math.round(window.innerWidth - a[a.length - 1].getBoundingClientRect().right);
    })(),
    // 单条判定：模式栏必须整体落在 appbar 的 y 区间内
    singleRow: !!(tbR && mbR && mbR.y >= tbR.y - 1 && mbR.bottom <= tbR.bottom + 1),
    // 页面顶部不得再有第二条同宽横条（旧 ModeBar 是独立全宽行）
    fullWidthBars: [...document.querySelectorAll('.app-shell > *')].map(e => ({
      cls: e.className, h: Math.round(e.getBoundingClientRect().height),
      w: Math.round(e.getBoundingClientRect().width)}))
  };
})()"""

# 窄窗（应用最小尺寸 1024×640）：appbar 必须不溢出、动作区仍可见
NARROW = """(() => {
  const tb = document.querySelector('.app-titlebar');
  const acts = [...document.querySelectorAll('.tb-actions .tb-btn')];
  const r = el => { const b = el.getBoundingClientRect();
    return {x: Math.round(b.x), right: Math.round(b.right), w: Math.round(b.width)}; };
  return {
    vw: window.innerWidth,
    titlebarClientW: tb ? tb.clientWidth : null,
    titlebarScrollW: tb ? tb.scrollWidth : null,
    overflow: tb ? tb.scrollWidth - tb.clientWidth : null,
    actions: acts.map(a => ({text: a.textContent.trim(), ...r(a)})),
    actionsInsideViewport: acts.every(a => r(a).right <= window.innerWidth + 1 && r(a).x >= 0),
    spacerW: Math.round((document.querySelector('.tb-spacer')?.getBoundingClientRect().width) || 0)
  };
})()"""

# 暗色主题：appbar/内容区必须跟随（证明取值走 token，不是写死的浅色）
DARK = """(() => {
  document.documentElement.setAttribute('data-theme', 'dark');
  const cs = el => el ? getComputedStyle(el) : null;
  return {
    titlebarBg: cs(document.querySelector('.app-titlebar'))?.backgroundColor,
    mainBg: cs(document.querySelector('.app-main'))?.backgroundColor,
    titleColor: cs(document.querySelector('.tb-title'))?.color,
    btnColor: cs(document.querySelector('.tb-actions .tb-btn'))?.color
  };
})()"""

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 4961), functools.partial(H, directory=str(DIST)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
port = fav.free_port()
prof = tempfile.mkdtemp(prefix="pw-appbar-")
proc = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                         "--window-size=1280,800", "--force-device-scale-factor=1",
                         f"--user-data-dir={prof}", f"--remote-debugging-port={port}",
                         "http://127.0.0.1:4961/dashboard"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
out = {"pages": [], "started": time.strftime("%Y-%m-%d %H:%M:%S")}
try:
    cdp = fav.CDP(port, want="127.0.0.1")
    cdp.call("Page.enable")
    cdp.call("Runtime.enable")
    cdp.call("Emulation.setDeviceMetricsOverride",
             {"width": 1280, "height": 800, "deviceScaleFactor": 1, "mobile": False})
    for route in ["/dashboard", "/life", "/settings"]:
        cdp.call("Page.navigate", {"url": f"http://127.0.0.1:4961{route}"})
        time.sleep(2.4)
        r = cdp.js(PROBE)
        r["route"] = route
        out["pages"].append(r)
        mb = r.get("modebar") or {}
        print(f"{route:11s} singleRow={r.get('singleRow')} appbarH={r.get('titlebar',{}).get('h')} "
              f"topbarH={r.get('topbar',{}).get('h')} modebar[h={mb.get('h')} bg={mb.get('bg')} "
              f"bb={mb.get('borderBottom')} minH={mb.get('minHeight')}] mainBg={r.get('mainBg')}")
        print(f"            actions={r.get('actions')} ctx={r.get('tbContext')!r} "
              f"textHas设置={'设置' in (r.get('topbarText') or '')} "
              f"textHas最小化={'最小化' in (r.get('topbarText') or '')}")
finally:
    proc.terminate()
    srv.shutdown()

# --- 窄窗复核（1024×640 = 应用最小尺寸）：appbar 不溢出、动作区不出界 ---
srv2 = http.server.ThreadingHTTPServer(("127.0.0.1", 4962), functools.partial(H, directory=str(DIST)))
threading.Thread(target=srv2.serve_forever, daemon=True).start()
port2 = fav.free_port()
prof2 = tempfile.mkdtemp(prefix="pw-appbar-narrow-")
proc2 = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
                          "--window-size=1024,640", "--force-device-scale-factor=1",
                          f"--user-data-dir={prof2}", f"--remote-debugging-port={port2}",
                          "http://127.0.0.1:4962/dashboard"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    cdp2 = fav.CDP(port2, want="127.0.0.1")
    cdp2.call("Page.enable")
    cdp2.call("Runtime.enable")
    cdp2.call("Emulation.setDeviceMetricsOverride",
              {"width": 1024, "height": 640, "deviceScaleFactor": 1, "mobile": False})
    cdp2.call("Page.navigate", {"url": "http://127.0.0.1:4962/dashboard"})
    time.sleep(2.4)
    out["narrow"] = cdp2.js(NARROW)
    out["dark"] = cdp2.js(DARK)
finally:
    proc2.terminate()
    srv2.shutdown()
print("narrow:", json.dumps(out.get("narrow"), ensure_ascii=False))
print("dark  :", json.dumps(out.get("dark"), ensure_ascii=False))

d = out["pages"][0] if out["pages"] else {}
nb, db = out.get("narrow") or {}, out.get("dark") or {}
out["checks"] = {
    "single_row_appbar": all(p.get("singleRow") for p in out["pages"]),
    "appbar_h_46": d.get("titlebar", {}).get("h") == 46,
    "modebar_override_transparent": (d.get("modebar") or {}).get("bg") in ("rgba(0, 0, 0, 0)", "transparent"),
    "modebar_override_no_border": (d.get("modebar") or {}).get("borderBottom") == "0px",
    "modebar_override_minheight0": (d.get("modebar") or {}).get("minHeight") == "0px",
    "main_canvas_bg": d.get("mainBg") not in (None, "rgba(0, 0, 0, 0)"),
    "has_settings_text": all("设置" in (p.get("topbarText") or "") for p in out["pages"]),
    "has_minimize_text": all("最小化" in (p.get("topbarText") or "") for p in out["pages"]),
    "settings_route_link": all(p.get("settingsLink") for p in out["pages"]),
    "three_actions": all(len(p.get("actions") or []) == 3 for p in out["pages"]),
    "actions_right_aligned": all((p.get("spacerW") or 0) > 0
                                 and (p.get("actionsRightGap") if p.get("actionsRightGap") is not None else 999) <= 24
                                 for p in out["pages"]),
    "narrow_no_overflow": nb.get("overflow") == 0,
    "narrow_actions_visible": bool(nb.get("actionsInsideViewport")),
    "dark_follows_token": (db.get("titlebarBg") not in (None, d.get("titlebar", {}).get("bg"))
                           and db.get("mainBg") not in (None, d.get("mainBg"))),
}
out["all_ok"] = all(out["checks"].values())
(TOOLS / "_force_appbar_check.json").write_text(json.dumps(out, ensure_ascii=False, indent=2),
                                                encoding="utf-8")
print("\nchecks:", json.dumps(out["checks"], ensure_ascii=False))
print("ALL OK:", out["all_ok"])
print("shell children:", json.dumps(d.get("fullWidthBars"), ensure_ascii=False))
