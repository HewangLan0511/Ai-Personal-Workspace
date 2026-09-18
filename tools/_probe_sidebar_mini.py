#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性探针：验证「侧边栏折叠态」的连续性修复**真的生效**（不是只写在 CSS 里）。

背景
----
base.css 段前那块「壳层折叠动画的连续性补齐」最初把选择器写成 `.app-shell.mini .nav-item`
＝ (0,3,0)，而设计稿并入段里也有一条 `.shell.mini .nav-item{justify-content:center;padding:0;gap:0}`
**同为 (0,3,0)** 且更靠后 —— 按 CSS 层叠规则，平局由源序判定，设计稿赢，
于是 `padding-left` 居中修复**整条被 `padding:0` 覆盖**（静默失效：文件里有、规则也"看起来"在，
但计算值不生效）。已改为 `.shell.app-shell.mini …` = (0,4,0)。

为什么必须用浏览器量
--------------------
"选择器写在文件里" ≠ "计算值生效"。这类同权重平局错误，静态读文件、typecheck、
甚至 grep 都看不出来 —— 只有 `getComputedStyle` 给出的**计算值**能证伪。

判据
----
  展开态 `.nav-item` padding-left = 12px（--space-3）
  折叠态 `.nav-item` padding-left = 15px（= (64 − 8×2 − 18) / 2）
  折叠态若为 0px ⇒ 修复失效（被设计稿 `padding:0` 压过）
  两态的 transition-property 都必须含 padding（否则数值对了也不会平滑过渡）

用法：python tools/_probe_sidebar_mini.py
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

import verify_tech02_workspace as base  # noqa: E402  （复用 CDPWebSocket / find_edge / start_server / ev）

UI = ROOT / "ui"
DIST = UI / "dist"
SRC = UI / "src"

ROWS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    ROWS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


# 展开态读一次，`.mini` 加上后再读一次；两次都在同一页面里取计算值。
PROBE = r"""
(() => {
  const shell = document.querySelector('.app-shell');
  const item = shell && shell.querySelector('.nav-item');
  const dev = shell && shell.querySelector('.device-line');
  if (!shell || !item) return { error: 'missing .app-shell / .nav-item' };
  const read = el => {
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { paddingLeft: cs.paddingLeft, justify: cs.justifyContent,
             trans: cs.transitionProperty };
  };
  const expanded = { nav: read(item), dev: read(dev) };
  shell.classList.add('mini');
  return { expanded, added: true };
})()
"""

AFTER = r"""
(() => {
  const shell = document.querySelector('.app-shell');
  const item = shell && shell.querySelector('.nav-item');
  const dev = shell && shell.querySelector('.device-line');
  const read = el => {
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { paddingLeft: cs.paddingLeft, justify: cs.justifyContent,
             trans: cs.transitionProperty };
  };
  const r = { nav: read(item), dev: read(dev), mini: shell.classList.contains('mini') };
  shell.classList.remove('mini');   // 复原，别把状态留给后续探针
  return r;
})()
"""


def main() -> int:
    if not (DIST / "index.html").exists():
        print(f"FATAL ui/dist 不存在：{DIST}")
        return 2
    newest_src = max((p.stat().st_mtime for p in SRC.rglob("*") if p.is_file()), default=0)
    if (DIST / "index.html").stat().st_mtime < newest_src:
        print("FATAL ui/dist 早于 ui/src —— 先构建（tools/_fusion_build.py，VITE_CORE_BASE='' 同源）")
        return 2

    edge = base.find_edge()
    port, srv = base.start_server()
    base_url = f"http://127.0.0.1:{port}"
    dbg_port = base.free_port()
    profile = tempfile.mkdtemp(prefix="pw-mini-probe-")
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
        base.wait_for(ws, "!!(document.querySelector('.app-shell .nav-item'))")

        # base.ev() 直接返回 Runtime.evaluate 的值（已是 returnByValue 的对象）
        exp_data = base.ev(ws, PROBE)
        if not isinstance(exp_data, dict) or exp_data.get("error"):
            check("浏览器探针取到 .app-shell / .nav-item", False, str(exp_data))
            return 1
        expanded = exp_data["expanded"]

        # 等过渡跑完（--mt-dur-nav-out 200ms，留足余量）
        time.sleep(0.45)
        mini = base.ev(ws, AFTER)
        if not isinstance(mini, dict):
            check("浏览器探针取到折叠态计算值", False, str(mini))
            return 1

        nav_exp, nav_min = expanded["nav"], mini["nav"]
        dev_exp, dev_min = expanded.get("dev"), mini.get("dev")

        check("展开态 .nav-item padding-left = 12px（--space-3）",
              nav_exp and nav_exp["paddingLeft"] == "12px",
              f"实得 {nav_exp and nav_exp['paddingLeft']}")

        check("折叠态 .nav-item padding-left = 15px（修复未被设计稿 padding:0 覆盖）",
              nav_min and nav_min["paddingLeft"] == "15px",
              f"实得 {nav_min and nav_min['paddingLeft']}"
              + ("" if nav_min and nav_min["paddingLeft"] == "15px"
                 else " ← 若为 0px 即同权重平局被源序反超"))

        check("折叠态 .nav-item transition-property 含 padding（数值对了还要能过渡）",
              bool(nav_min and "padding" in nav_min["trans"]),
              f"实得 {nav_min and nav_min['trans']}")

        check("折叠态 .nav-item justify-content 为 flex-start（图标位置由 padding 承担）",
              bool(nav_min and nav_min["justify"] == "flex-start"),
              f"实得 {nav_min and nav_min['justify']}")

        if dev_exp and dev_min:
            # 设计稿**没有** `.device-line{…}` 基础规则（只有 `.device-line .txt`），
            # 所以展开态 padding-left 就是 0 —— 别把它当 8px（--space-2 是 .sidebar 自己的
            # 内边距，不是这行的）。折叠态的 17px 正是为了在 mini 宽度里把它居中。
            check("展开态 .device-line padding-left = 0px（设计稿无基础内边距）",
                  dev_exp["paddingLeft"] == "0px", f"实得 {dev_exp['paddingLeft']}")
            check("展开态 .device-line transition-property 含 padding（0 → 17px 要能过渡）",
                  "padding" in dev_exp["trans"], f"实得 {dev_exp['trans']}")
            check("折叠态 .device-line padding-left = 17px（= (64−8×2−14)/2，图标居中于 32px）",
                  dev_min["paddingLeft"] == "17px", f"实得 {dev_min['paddingLeft']}")
            check("折叠态 .device-line transition-property 含 padding",
                  "padding" in dev_min["trans"], f"实得 {dev_min['trans']}")
        else:
            check("页面存在 .device-line（设备行）", False, "未取到 .device-line 计算值")
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

    bad = [n for n, ok, _ in ROWS if not ok]
    print(f"\n=== 汇总 {len(ROWS) - len(bad)}/{len(ROWS)} ===")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
