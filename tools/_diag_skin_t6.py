#!/usr/bin/env python3
"""一次性诊断：verify_skin_engine T6 的「非 root 属性变更」到底是谁写的。

T6 在页面入场动画（`data-enter` / `.enter-up`）落地后开始报
`class/style` 变更落在 .greet/.grid/.hero/.sec 上。本脚本把**带旧值**的
MutationRecord 原样打出来，并同时报告入场动画此刻的状态，
用来区分「入场收尾的摘类/清内联」与「别的东西在切 skin 时改这些节点」。

只为排查，不进验收链。
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location("vt01", ROOT / "tools" / "verify_tech01.py")
vt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vt)  # type: ignore[union-attr]

OBS = r"""
(() => {
  const recs = [];
  const mo = new MutationObserver(rs => {
    for (const r of rs) {
      const t = r.target;
      if (t === document.documentElement) continue;
      const desc = t.nodeName + '#' + (t.id || '') + '.' +
        (typeof t.className === 'string' ? t.className : '');
      if (r.type === 'attributes') {
        recs.push({ ms: Math.round(performance.now()), k: 'attr', a: r.attributeName,
                    node: desc, old: r.oldValue, now: t.getAttribute(r.attributeName) });
      } else {
        recs.push({ ms: Math.round(performance.now()), k: 'child',
                    node: desc, add: r.addedNodes.length, rm: r.removedNodes.length });
      }
    }
  });
  window.__diag = {
    start() { recs.length = 0; mo.observe(document.documentElement,
              { attributes: true, attributeOldValue: true, childList: true, subtree: true }); },
    stop() { mo.disconnect(); return JSON.parse(JSON.stringify(recs)); },
  };
})()
"""

STATE = r"""
(() => {
  const els = [...document.querySelectorAll('[data-enter]')];
  return {
    path: location.pathname,
    enterCount: els.length,
    enterUp: els.filter(e => e.classList.contains('enter-up')).length,
    inlineStyled: els.filter(e => e.style.animationDuration || e.style.animationDelay).length,
    perEl: els.map(e => ({ cls: e.className, dur: e.style.animationDuration, delay: e.style.animationDelay })),
    tokEntrance: getComputedStyle(document.documentElement).getPropertyValue('--mt-dur-entrance').trim(),
    tokEntrance2: getComputedStyle(document.documentElement).getPropertyValue('--mt-dur-entrance-2').trim(),
    tokEntranceWs: getComputedStyle(document.documentElement).getPropertyValue('--mt-dur-entrance-ws').trim(),
  };
})()
"""


def main() -> int:
    if not vt.DIST.exists():
        print("FATAL ui/dist 不存在")
        return 2
    edge = vt.find_edge()
    if edge is None:
        print("FATAL 未找到 Edge")
        return 2
    port, srv = vt.start_server()
    base = f"http://127.0.0.1:{port}"
    dbg = vt.free_port()
    profile = tempfile.mkdtemp(prefix="pw-diag-")
    proc = subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         f"--user-data-dir={profile}", f"--remote-debugging-port={dbg}", "--remote-allow-origins=*",
         "--window-size=1440,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        ws_url = None
        for _ in range(50):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg}/json/list", timeout=2) as resp:
                    pages = [t for t in json.loads(resp.read().decode()) if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except Exception:
                pass
            time.sleep(0.2)
        if not ws_url:
            print("FATAL CDP 连接失败")
            return 2
        ws = vt.CDPWebSocket(ws_url)
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        ws.call("Page.addScriptToEvaluateOnNewDocument", {"source": OBS})
        ws.call("Page.navigate", {"url": base}, timeout=15)
        vt.wait_for(ws, "!!(window.__pwMotion && window.__diag)")
        ev = lambda js, t=20: vt.ev(ws, js, timeout=t)
        ev("window.__pwMotion.setLevel('standard')")

        print("=== 0.6s 后（入场进行中）===")
        time.sleep(0.6)
        print(json.dumps(ev(STATE), ensure_ascii=False, indent=1))

        print("=== 4s 后（页面静默）===")
        time.sleep(4.0)
        print(json.dumps(ev(STATE), ensure_ascii=False, indent=1))

        print("=== 对照组：空等 300ms ===")
        ev("window.__diag.start()")
        print(json.dumps(ev("new Promise(r => setTimeout(() => r(window.__diag.stop()), 300))", 15),
                         ensure_ascii=False, indent=1))

        print("=== 实验组：切 skin 后 300ms ===")
        ev("window.__diag.start()")
        ev("window.__pwMotion.skin.apply('calm')")
        print(json.dumps(ev("new Promise(r => setTimeout(() => r(window.__diag.stop()), 300))", 15),
                         ensure_ascii=False, indent=1))

        print("=== 实验组 2：重新导航 → 立刻切 skin（模拟探针时序）===")
        ws.call("Page.navigate", {"url": base}, timeout=15)
        vt.wait_for(ws, "!!(window.__pwMotion && window.__diag)")
        ev("window.__pwMotion.setLevel('standard')")
        ev("window.__diag.start()")
        ev("window.__pwMotion.skin.apply('calm')")
        print(json.dumps(ev("new Promise(r => setTimeout(() => r(window.__diag.stop()), 300))", 15),
                         ensure_ascii=False, indent=1))
    finally:
        proc.terminate()
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
