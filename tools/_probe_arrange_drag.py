#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性探针：首页「组件管理」列表的拖拽排序（需求 3）在**真实产物**里通不通。

为什么要有它
------------
本轮给 `.arrange-row` 补上了 `draggable="true"` + `useAutoSort`（此前只存在于数据层：
store 有 `lockLayout` 但没有任何拖拽入口）。这类"文件在、接线丢"的问题，静态读代码
和 typecheck 都抓不住 —— 必须让事件真的走一遍 `useListSort` 的 handler。

本探针**在做什么、不做什么**（别把结论说过头）
  ✔ 走真实链路：合成 `DragEvent` → `useListSort` 的 dragstart/dragover/drop handler
    → `flip` + `insertBefore` 真换位 → `flash()` 落位高亮 → `onReorder` 回调 → store 写入。
  ✘ 不含浏览器**原生拖拽手势**（鼠标按下并阈值移动才由内核发起 drag）。
    所以它证明的是"接线与索引计算正确"，不是"内核一定肯发起 dragstart"。
    —— 后者靠 `draggable="true"` 声明（设计稿原文即如此）+ 已验收的 `.wcard` 同款路径兜底。

判据
----
   1) 折叠面板可打开，`.arrange-row` ≥ 3 行
  1b) 面板打开后顺序**稳定**（store 水合完成再拖 —— 水合中途换引用会让拖拽变空操作）
  2) dragstart 后：源行有 `.dragging`、body 有 `.is-dragging`（拖拽态视觉）
  3) dragover 邻居后：DOM 顺序立刻让位（move 模式 = 实时让位，不等落点）
  4) drop 后：DOM 顺序 = 原顺序左移一位（首项落到末位）
  5) drop 后：被拖行带 `.just-swap`（落位高亮 460ms）
  6) drop 后：`#pw-live-region` 收到 `组件顺序已调整` 播报（= onReorder 真的被调用）
  7) dragend 后：`.dragging` 与 body 的 `.is-dragging` 都已清除

用法：python tools/_probe_arrange_drag.py

⚠️ 副作用：`drop` 会走真实 `onReorder` → `widgetStore.reorderWidget()` → **持久化**组件顺序
   并把 `layoutLocked` 置为 true（这正是"手动调序后布局固定"的产品语义）。也就是说
   跑一次探针会把当前开发环境的首页组件顺序按(0 → 2)改一次。要复原：首页点
   「恢复自动布局」，或在「组件管理」里再拖回来。
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
DIST = UI / "dist"
SRC = UI / "src"

ROWS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    ROWS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


OPEN_PANEL = r"""
(() => {
  const btn = [...document.querySelectorAll('button')]
    .find(b => (b.textContent || '').includes('组件管理'));
  if (!btn) return { error: '找不到「组件管理」按钮' };
  btn.click();
  return { clicked: true, label: btn.textContent.trim() };
})()
"""

READ_ORDER = r"""
(() => {
  const rows = [...document.querySelectorAll('.widget-manage .arrange-row')];
  return { n: rows.length, order: rows.map(r => r.dataset.wid) };
})()
"""

BEGIN_DRAG = r"""
(() => {
  const rows = [...document.querySelectorAll('.widget-manage .arrange-row')];
  if (rows.length < 3) return { error: `arrange-row 只有 ${rows.length} 行，需要 ≥3` };
  window.__pwProbe = { dt: new DataTransfer() };
  const A = rows[0];
  window.__pwProbe.src = A;
  A.dispatchEvent(new DragEvent('dragstart',
    { bubbles: true, cancelable: true, dataTransfer: window.__pwProbe.dt }));
  return {
    n: rows.length,
    order: rows.map(r => r.dataset.wid),
    dragging: A.classList.contains('dragging'),
    bodyDragging: document.body.classList.contains('is-dragging'),
  };
})()
"""

DRAG_OVER = r"""
(() => {
  const p = window.__pwProbe;
  const rows = [...document.querySelectorAll('.widget-manage .arrange-row')];
  const C = rows[2];
  p.target = C;
  C.dispatchEvent(new DragEvent('dragover',
    { bubbles: true, cancelable: true, dataTransfer: p.dt }));
  return { order: [...document.querySelectorAll('.widget-manage .arrange-row')].map(r => r.dataset.wid) };
})()
"""

DROP = r"""
(() => {
  const p = window.__pwProbe;
  p.target.dispatchEvent(new DragEvent('drop',
    { bubbles: true, cancelable: true, dataTransfer: p.dt }));
  const rows = [...document.querySelectorAll('.widget-manage .arrange-row')];
  return {
    order: rows.map(r => r.dataset.wid),
    flashed: rows.filter(r => r.classList.contains('just-swap')).map(r => r.dataset.wid),
  };
})()
"""

# `onReorder` → `shell.announce()` 写的是 Vue 状态，DOM 要等下一个 tick 才更新；
# 与 drop 在同一个 evaluate 里读只会读到旧值（探针第一版就是这么误报的）。
READ_LIVE = r"""
(() => ({
  live: (document.querySelector('#pw-live-region') || {}).textContent || '',
}))()
"""

END_DRAG = r"""
(() => {
  const p = window.__pwProbe;
  p.src.dispatchEvent(new DragEvent('dragend',
    { bubbles: true, cancelable: true, dataTransfer: p.dt }));
  const rows = [...document.querySelectorAll('.widget-manage .arrange-row')];
  return {
    draggingLeft: rows.filter(r => r.classList.contains('dragging')).length,
    bodyDragging: document.body.classList.contains('is-dragging'),
    orderAfter: rows.map(r => r.dataset.wid),
  };
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
    profile = tempfile.mkdtemp(prefix="pw-arrange-probe-")
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

        opened = base.ev(ws, OPEN_PANEL)
        if not isinstance(opened, dict) or opened.get("error"):
            check("首页「组件管理」面板可打开", False, str(opened))
            return 1
        try:
            base.wait_for(ws, "document.querySelectorAll('.widget-manage .arrange-row').length >= 2", timeout=8)
        except Exception:
            pass

        # --- 1b 顺序稳定性：store 水合（widgets/usage/layoutLocked）是异步的，
        # 水合完成瞬间 Vue 会用新的 `widgetStore.all` 重刷列表 —— 若在那一刻开始拖，
        # 拖拽源节点会被 Vue 的 patch 换掉，拖拽整段变成空操作（探针第一次跑就踩到了：
        # dragover 让位与 drop 回调全被这次重排吃掉）。先等到两次读数一致再动手。 */
        prev_order = None
        stable = False
        for _ in range(12):
            cur = base.ev(ws, READ_ORDER)
            if isinstance(cur, dict) and cur.get("order") and cur["order"] == prev_order:
                stable = True
                break
            prev_order = cur.get("order") if isinstance(cur, dict) else None
            time.sleep(0.4)
        check("面板打开后顺序稳定（store 水合已结束，拖拽源不会被异步重排换掉）",
              stable, f"稳定顺序={prev_order}" if stable else f"12 轮内始终在变，最后={prev_order}")

        started = base.ev(ws, BEGIN_DRAG)
        if not isinstance(started, dict) or started.get("error"):
            check("取到 ≥3 个 `.arrange-row`（可拖拽行）", False, str(started))
            return 1
        order0 = started["order"]
        check("取到 ≥3 个 `.arrange-row`（可拖拽行）", len(order0) >= 3, f"行数 {len(order0)}")
        check("dragstart 后：源行带 `.dragging`", started["dragging"],
              f".dragging={started['dragging']}")
        check("dragstart 后：body 带 `.is-dragging`（hover 让位给 drag）", started["bodyDragging"],
              f"body.is-dragging={started['bodyDragging']}")

        over = base.ev(ws, DRAG_OVER)
        over_order = over.get("order") if isinstance(over, dict) else None
        # move 模式的语义（useListSort.onDragOver）：`ref = from < to ? list[to].nextSibling : list[to]`
        # → `insertBefore(src, ref)` 把 src 放到 **index `to`**，不是"甩到末尾"。
        # 源 = 第 0 行，落点 = 第 2 行 ⇒ 结果应为「摘掉首项，再插回下标 2」。
        rest = order0[1:]
        want = rest[:2] + [order0[0]] + rest[2:]
        check("dragover 邻居后：DOM 立刻让位（move 模式实时让位，不等落点）",
              over_order == want, f"over={over_order} 期望={want}")

        time.sleep(0.35)  # 让 flip 的 busy 窗口（--mt-dur-reorder 160ms）过去，再落点

        dropped = base.ev(ws, DROP)
        if not isinstance(dropped, dict):
            check("drop 后取回顺序", False, str(dropped))
            return 1
        check("drop 后：DOM 顺序 = 首项落到原第 3 行位置", dropped["order"] == want,
              f"实得={dropped['order']} 期望={want}")
        check("drop 后：被拖行带 `.just-swap`（落位高亮）", order0[0] in dropped["flashed"],
              f"带高亮的行={dropped['flashed']}")

        time.sleep(0.2)  # onReorder → announce 是 Vue 状态，等下一个 tick 再读
        live = base.ev(ws, READ_LIVE)
        live_text = live.get("live") if isinstance(live, dict) else ""
        check("drop 后：`#pw-live-region` 收到「组件顺序已调整」（onReorder 真被调用）",
              "组件顺序已调整" in (live_text or ""), f"live={live_text!r}")

        ended = base.ev(ws, END_DRAG)
        if isinstance(ended, dict):
            check("dragend 后：`.dragging` 已清除", ended["draggingLeft"] == 0,
                  f"残留 {ended['draggingLeft']} 行")
            check("dragend 后：body `.is-dragging` 已清除", not ended["bodyDragging"],
                  f"body.is-dragging={ended['bodyDragging']}")
            check("dragend 后：顺序保持（数据层与 DOM 一致，没有被回退）",
                  ended["orderAfter"] == want,
                  f"实得={ended['orderAfter']}")
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
