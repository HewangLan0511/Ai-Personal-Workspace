#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性诊断：首页「组件管理」列表的顺序为何在拖拽前自己变。

`_probe_arrange_drag.py` 观察到：面板打开后两次轻量读数（只读 DOM，不发任何事件）
之间的 `.arrange-row` 顺序会变化，导致 dragstart 抓到的行与 dragover/drop 命中的行
不是同一批 —— 拖拽因此静默失效。本脚本只做观测（不打事件、不写状态）：
  · MutationObserver 记录 `<ul>` 的 childList 变动次数与时间
  · 每 250ms 采样一次：DOM 顺序 + 是否显示「已按手动布局固定」（= store.layoutLocked）
  · 记录每次顺序变化的 diff

用法：python tools/_diag_arrange_order.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import verify_tech02_workspace as base  # noqa: E402

UI = ROOT / "ui"

INSTALL = r"""
(() => {
  const btn = [...document.querySelectorAll('button')]
    .find(b => (b.textContent || '').includes('组件管理'));
  if (btn) btn.click();
  return { clicked: !!btn };
})()
"""

# 面板出现后再装观察器
OBSERVE = r"""
(() => {
  const ul = document.querySelector('.widget-manage ul');
  if (!ul) return { error: 'no .widget-manage ul' };
  window.__obs = { child: 0, attr: 0, log: [] };
  const ob = new MutationObserver((recs) => {
    for (const r of recs) {
      if (r.type === 'childList') {
        window.__obs.child += 1;
        window.__obs.log.push(['child', Math.round(performance.now()),
          [...ul.querySelectorAll('.arrange-row')].map(x => x.dataset.wid).join('|')]);
      }
    }
  });
  ob.observe(ul, { childList: true, subtree: false });
  window.__obsTarget = ul;
  return { ok: true, initial: [...ul.querySelectorAll('.arrange-row')].map(x => x.dataset.wid) };
})()
"""

SAMPLE = r"""
(() => {
  const ul = document.querySelector('.widget-manage ul');
  const rows = ul ? [...ul.querySelectorAll('.arrange-row')] : [];
  return {
    t: Math.round(performance.now()),
    order: rows.map(r => r.dataset.wid),
    lockedNote: !![...document.querySelectorAll('.widget-manage .stage-note, .stage-note')]
      .find(n => (n.textContent || '').includes('已按手动布局固定')),
    child: window.__obs ? window.__obs.child : -1,
    grid: [...document.querySelectorAll('.widget-grid > *')]
      .map(c => (c.textContent || '').trim().slice(0, 8)),
  };
})()
"""


def main() -> int:
    edge = base.find_edge()
    port, srv = base.start_server()
    base_url = f"http://127.0.0.1:{port}"
    dbg_port = base.free_port()
    profile = tempfile.mkdtemp(prefix="pw-arrange-diag-")
    proc = subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--user-data-dir={profile}",
         f"--remote-debugging-port={dbg_port}", "--remote-allow-origins=*",
         "--window-size=1600,1000", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    ws = None
    try:
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg_port}/json/list", timeout=2) as resp:
                    pages = [t for t in json.loads(resp.read().decode()) if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.2)
        if not ws_url:
            print("FATAL 连不上 CDP")
            return 2
        ws = base.CDPWebSocket(ws_url)
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": f"{base_url}/dashboard"}, timeout=15)
        base.wait_for(ws, "!!(document.querySelector('.widget-grid, .widget-manage'))")

        print("打开面板:", json.dumps(base.ev(ws, INSTALL), ensure_ascii=False))
        base.wait_for(ws, "!!document.querySelector('.widget-manage ul')", timeout=8)
        print("装观察器:", json.dumps(base.ev(ws, OBSERVE), ensure_ascii=False))

        prev = None
        for i in range(20):
            s = base.ev(ws, SAMPLE)
            if not isinstance(s, dict):
                print("采样失败", s)
                break
            mark = ""
            if prev is not None and s["order"] != prev:
                mark = "   <<< 顺序变了"
            print(f"[{i:02d}] t={s['t']:>6}ms childMuts={s['child']:>3} locked={int(s['lockedNote'])}"
                  f" order={s['order']}{mark}")
            prev = s["order"]
            time.sleep(0.25)
    finally:
        try:
            if ws:
                ws.close()
        except Exception:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        srv.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
