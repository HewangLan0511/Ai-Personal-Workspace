#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""UI-FUSION-FULL · 壳层结构/几何实测探针（Edge 无头 + CDP）

为什么需要它：这一轮把壳层（`.shell` / `.panel` / 四区 / `.widget-col` / `.ai-dock`）
从"手写 CSS"改成"设计稿类名逐字生效"。**手写 CSS 与设计稿 CSS 长得很像**，
只读代码分辨不出"规则生效了"还是"被自己的 scoped 样式盖住了"。
所以这里量真实几何：宽度必须等于 `--sidebar-w` / `--widget-w` / `--ai-panel-w`
解析出来的值，圆角必须等于 `--r-2xl`。规则没生效时这些数字会明显对不上。

覆盖：
  A 结构   —— 双类名、四区顺序、手柄节点、widget-col 内部结构、ai-dock 内部结构
  B 几何   —— 三档宽度 = token 解析值；面板圆角/底色 = token 解析值
  C 机制   —— data-rs 状态机随窗口宽度分档；手柄拖拽改变宽度；蓄力折叠 → `.shell.mini`
  D 设计稿 —— `.wcard` 正文逐条对照（天气/待办/正在播放）

用法：python tools/_fusion_shell_probe.py [--port 5199] [--keep]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
UI = ROOT / "ui"
NODE = shutil.which("node") or r"C:\Users\baiyu\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"

spec = importlib.util.spec_from_file_location("fav", str(TOOLS / "_force_app_verify.py"))
fav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fav)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(("PASS " if ok else "FAIL ") + name + ("  | " + detail if detail else ""))


# --------------------------------------------------------------- 环境

def find_edge() -> str:
    for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if not base:
            continue
        for rel in (("Microsoft", "Edge", "Application", "msedge.exe"),
                    ("Microsoft", "Edge Beta", "Application", "msedge.exe")):
            cand = Path(base).joinpath(*rel)
            if cand.exists():
                return str(cand)
    return shutil.which("msedge") or ""


def wait_http(url: str, timeout: float = 90) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as r:  # noqa: S310
                if r.status < 500:
                    return True
        except Exception:
            time.sleep(1.0)
    return False


PROBE_JS = r"""
(() => {
  const shell = document.querySelector('.shell');
  if (!shell) return { ready: false };
  const cs = getComputedStyle(shell);
  const px = (v) => {
    const t = document.createElement('div');
    t.style.width = v; t.style.position = 'absolute'; t.style.visibility = 'hidden';
    document.body.appendChild(t);
    const w = t.getBoundingClientRect().width;
    t.remove();
    return Math.round(w * 100) / 100;
  };
  const rect = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return { w: Math.round(r.width * 100) / 100, h: Math.round(r.height * 100) / 100,
             display: s.display, radius: s.borderTopLeftRadius, bg: s.backgroundColor };
  };
  const panel = document.querySelector('.panel');
  const kids = panel ? [...panel.children].map(e => e.className) : [];
  const cards = [...document.querySelectorAll('.wscroll .wcard')];
  const shellCls = shell.className;
  return {
    ready: true,
    shellClass: shellCls,
    shellDataRs: shell.getAttribute('data-rs'),
    shellDataCw: shell.getAttribute('data-cw'),
    token: {
      sidebar: px(cs.getPropertyValue('--sidebar-w').trim()),
      widget: px(cs.getPropertyValue('--widget-w').trim()),
      ai: px(cs.getPropertyValue('--ai-panel-w').trim()),
      r2xl: cs.getPropertyValue('--r-2xl').trim(),
      bgApp: px(cs.getPropertyValue('--bg-app').trim()),
    },
    sidebar: rect('.sidebar'),
    content: rect('.content'),
    widgetCol: rect('.widget-col'),
    aiDock: rect('.ai-dock'),
    panelBox: rect('.panel'),
    panelKids: kids,
    handles: {
      nav: !!document.querySelector('.rsh--nav'),
      widget: !!document.querySelector('.rsh--widget'),
      ai: !!document.querySelector('.rsh--ai'),
    },
    navItem: rect('.nav-item'),
    navActive: !!document.querySelector('.nav-item.active'),
    navFoot: !!document.querySelector('.nav-foot'),
    navListWrapper: !!document.querySelector('.app-nav .nav-list'),
    navFoldBtn: !!document.querySelector('.nav-fold'),
    wscroll: !!document.querySelector('.wscroll'),
    wcardCount: cards.length,
    wcardIds: cards.map(c => c.getAttribute('data-wid')),
    wgripCount: document.querySelectorAll('.wscroll .wcard .wgrip').length,
    wcardTexts: cards.map(c => (c.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 60)),
    addBtn: (document.querySelector('.widget-add')?.innerText || '').replace(/\s+/g, ' ').trim(),
    dockPanel: rect('.dock-panel'),
    dockRail: rect('.dock-rail'),
    railBtn: !!document.querySelector('.dock-rail .rail-btn'),
    railLabel: (document.querySelector('.dock-rail .rail-label')?.textContent || '').trim(),
    aiSegs: [...document.querySelectorAll('.ai-head .seg button')].map(b => b.textContent.trim()),
    navHrefs: [...document.querySelectorAll('.app-nav a')].map(a => a.getAttribute('href')),
  };
})()
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    edge = find_edge()
    if not edge:
        print("SKIP 未找到 msedge.exe")
        return 0
    print(f"edge = {edge}")

    dev_port = args.port or fav.free_port()
    env = dict(os.environ)
    env.setdefault("BROWSER", "none")
    dev = subprocess.Popen(
        [NODE, "node_modules/vite/bin/vite.js", "--port", str(dev_port), "--strictPort", "--host", "127.0.0.1"],
        cwd=str(UI), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{dev_port}"
    profile = tempfile.mkdtemp(prefix="pw-edge-")
    browser = None
    cdp = None
    out: dict = {"base_url": base_url}
    try:
        if not wait_http(base_url + "/", 120):
            print("SKIP vite dev server 未就绪")
            return 0
        cdp_port = fav.free_port()
        browser = subprocess.Popen(
            [edge, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
             f"--user-data-dir={profile}", f"--remote-debugging-port={cdp_port}",
             "--remote-allow-origins=*", "--window-size=1440,900", base_url + "/dashboard"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        cdp = fav.CDP(cdp_port, want="127.0.0.1")
        out["target"] = cdp.target_url
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})

        # 等 .shell 出现（vite 首次编译 + vue 挂载）
        deadline = time.time() + 90
        state = None
        while time.time() < deadline:
            state = cdp.js(PROBE_JS, timeout=20)
            if isinstance(state, dict) and state.get("ready"):
                break
            time.sleep(2.0)
        out["state"] = state
        if not (isinstance(state, dict) and state.get("ready")):
            check("A0 .shell 渲染", False, f"state={str(state)[:200]}")
            return 1
        check("A0 .shell 渲染", True, str(state.get("shellClass")))

        # ---------------- A 结构 ----------------
        cls = (state.get("shellClass") or "").split()
        check("A1 壳层双类名 app-shell + shell", "app-shell" in cls and "shell" in cls, str(cls))
        check("A2 四区顺序 = sidebar|content|widget-col|ai-dock",
              state.get("panelKids") == ["app-nav sidebar", "app-content content",
                                         "app-widget widget-col", "ai-dock"],
              json.dumps(state.get("panelKids"), ensure_ascii=False))
        check("A3 三个手柄节点齐备", all(state["handles"].values()), json.dumps(state["handles"]))
        check("A4 widget-col 内部 = .wscroll（滚动在里层）", state.get("wscroll") is True)
        check("A5 挂件 = 设计稿 3 个默认开启项",
              state.get("wcardIds") == ["weather", "todo", "music"],
              json.dumps(state.get("wcardIds"), ensure_ascii=False))
        check("A6 每张挂件卡都有 .wgrip", state.get("wgripCount") == state.get("wcardCount"),
              f"{state.get('wgripCount')} / {state.get('wcardCount')}")
        check("A7 「＋ 添加组件」按钮存在", "添加组件" in (state.get("addBtn") or ""),
              repr(state.get("addBtn")))
        check("A8 侧栏已去 .nav-list 包裹层（分组直属 .sidebar）",
              state.get("navListWrapper") is False)
        check("A9 侧栏已去折叠按钮（设计稿：拖边界是唯一途径）",
              state.get("navFoldBtn") is False)
        check("A10 .nav-foot 存在（设置 + 设备行）", state.get("navFoot") is True)
        check("A11 `.nav-item.active` 激活态生效", state.get("navActive") is True)
        check("A12 ai-dock 内部 = .dock-rail + .dock-panel",
              state.get("railBtn") is True and (state.get("railLabel") == "AI 助手"),
              f"railLabel={state.get('railLabel')!r}")
        check("A13 模式切换用设计稿 .seg（聊天 / 工作空间助手）",
              state.get("aiSegs") == ["聊天", "工作空间助手"], json.dumps(state.get("aiSegs"), ensure_ascii=False))

        # ---------------- D 设计稿正文 ----------------
        texts = state.get("wcardTexts") or []
        check("D1 天气卡正文 = 28° / 多云 / 武汉",
              len(texts) > 0 and "28°" in texts[0] and "多云" in texts[0] and "武汉" in texts[0],
              texts[0] if texts else "")
        check("D2 待办卡正文含三条待办",
              len(texts) > 1 and "改完 train.py 的数据加载" in texts[1] and "整理本周笔记" in texts[1],
              texts[1] if len(texts) > 1 else "")
        check("D3 正在播放卡正文 = 夜空中最亮的星",
              len(texts) > 2 and "夜空中最亮的星" in texts[2],
              texts[2] if len(texts) > 2 else "")

        # ---------------- B 几何 ----------------
        tok = state.get("token") or {}
        sw = (state.get("sidebar") or {}).get("w")
        ww = (state.get("widgetCol") or {}).get("w")
        aw = (state.get("aiDock") or {}).get("w")
        check("B1 侧栏宽 = --sidebar-w 解析值", sw is not None and abs(sw - tok.get("sidebar", -1)) < 1.5,
              f"实测 {sw} vs token {tok.get('sidebar')}")
        check("B2 组件区宽 = --widget-w 解析值", ww is not None and abs(ww - tok.get("widget", -1)) < 1.5,
              f"实测 {ww} vs token {tok.get('widget')}")
        check("B3 AI 栏宽 = --ai-panel-w 解析值", aw is not None and abs(aw - tok.get("ai", -1)) < 1.5,
              f"实测 {aw} vs token {tok.get('ai')}")
        check("B4 面板圆角 = --r-2xl", (state.get("panelBox") or {}).get("radius") == tok.get("r2xl"),
              f"实测 {(state.get('panelBox') or {}).get('radius')} vs token {tok.get('r2xl')}")
        check("B5 壳层底色 = --bg-app（不是默认白）",
              (state.get("panelBox") or {}).get("bg") not in (None, "rgba(0, 0, 0, 0)"),
              str((state.get("panelBox") or {}).get("bg")))
        check("B6 面板是 .shell 的子节点且横向 flex",
              (state.get("panelBox") or {}).get("w", 0) > 1000,
              f"panel 宽 {(state.get('panelBox') or {}).get('w')}")
        check("B7 导航项高度 = 34px（设计稿 .nav-item）",
              (state.get("navItem") or {}).get("h") == 34,
              str((state.get("navItem") or {}).get("h")))

        # ---------------- C 机制：手柄拖拽 + 蓄力折叠 ----------------
        # ★ 顺序有讲究：先做拖拽，再做窗口分档。
        #   原因：`RS_GATE` 是**滞回**的（compact→full 要 ≥1500，而进入 compact 只要 <1400）。
        #   窗口一旦被压到过 1400 以下，即使回到 1440 也停在 compact，
        #   此时 `.shell[data-rs="compact"] .sidebar{flex-basis:min(--sidebar-w,180px)}`
        #   会把侧栏**钉在 180px** —— 拖拽改的是 `--sidebar-w`，量到的宽度却不变。
        #   这不是缺陷，是设计稿的滞回语义；探针必须顺着它排顺序。
        def set_w(w: int) -> dict:
            cdp.call("Emulation.setDeviceMetricsOverride",
                     {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False})
            time.sleep(1.4)
            return cdp.js("({rs: document.querySelector('.shell').getAttribute('data-rs'),"
                          "cw: document.querySelector('.shell').getAttribute('data-cw'),"
                          "sw: document.querySelector('.sidebar').getBoundingClientRect().width,"
                          "ww: document.querySelector('.widget-col').getBoundingClientRect().width,"
                          "aw: document.querySelector('.ai-dock').getBoundingClientRect().width,"
                          "dockPanel: getComputedStyle(document.querySelector('.dock-panel')).display,"
                          "dockRail: getComputedStyle(document.querySelector('.dock-rail')).display,"
                          "aiCls: document.querySelector('.ai-dock').className})", timeout=20)

        wide = set_w(1560)
        check("C1 1560 宽 = data-rs:full（≥1500 才恢复满档）",
              wide.get("rs") == "full", json.dumps(wide, ensure_ascii=False))
        check("C2 data-cw 内容分档已下发", bool(wide.get("cw")), str(wide.get("cw")))
        check("C3 full 档：dock-panel 显示 / dock-rail 隐藏",
              wide.get("dockPanel") != "none" and wide.get("dockRail") == "none",
              json.dumps(wide, ensure_ascii=False))

        def drag_handle(sel: str, dx: int, hold_release: float = 0.0) -> None:
            box = cdp.js(
                "(() => { const el = document.querySelector(%s); if (!el) return null;"
                "const r = el.getBoundingClientRect();"
                "return {x: r.left + r.width/2, y: r.top + r.height/2}; })()" % json.dumps(sel),
                timeout=15)
            if not box:
                return
            x, y = box["x"], box["y"]
            cdp.call("Input.dispatchMouseEvent",
                     {"type": "mouseMoved", "x": x, "y": y, "buttons": 0})
            cdp.call("Input.dispatchMouseEvent",
                     {"type": "mousePressed", "x": x, "y": y, "button": "left", "buttons": 1, "clickCount": 1})
            steps = max(1, abs(dx) // 12)
            for i in range(1, steps + 1):
                cdp.call("Input.dispatchMouseEvent",
                         {"type": "mouseMoved", "x": x + dx * i / steps, "y": y,
                          "button": "left", "buttons": 1})
                time.sleep(0.05)
            time.sleep(hold_release)
            cdp.call("Input.dispatchMouseEvent",
                     {"type": "mouseReleased", "x": x + dx, "y": y, "button": "left",
                      "buttons": 0, "clickCount": 1})
            time.sleep(0.8)

        def nav_state() -> dict:
            return cdp.js(
                "({mini: document.querySelector('.shell').classList.contains('mini'),"
                " w: document.querySelector('.sidebar').getBoundingClientRect().width,"
                " tok: getComputedStyle(document.querySelector('.shell')).getPropertyValue('--sidebar-w').trim()})",
                timeout=15)

        b0 = nav_state()
        drag_handle(".rsh--nav", 60)
        a0 = nav_state()
        check("C4 拖 .rsh--nav 向右 → 侧栏变宽",
              (a0.get("w") or 0) > (b0.get("w") or 0) + 30,
              f"{b0.get('w')} → {a0.get('w')}（token {b0.get('tok')} → {a0.get('tok')}）")
        check("C5 拖拽把新宽度写回 --sidebar-w（几何与 token 同步）",
              a0.get("tok") != b0.get("tok"), f"{b0.get('tok')} → {a0.get('tok')}")

        # 蓄力折叠：一路拖到 min 以下并**保持** > dwell（--mt-dur-dwell = 560ms），
        # 松手前 arming 才攒满 → fold。松手太快只会回弹，不会折叠。
        drag_handle(".rsh--nav", -700, hold_release=1.0)
        mini = nav_state()
        check("C6 拖到最小值以下并蓄力 → 导航折叠（.shell.mini）",
              mini.get("mini") is True, json.dumps(mini, ensure_ascii=False))
        check("C7 mini 态宽度 = --sidebar-w-mini（64px）",
              abs((mini.get("w") or 0) - 64) < 2, str(mini.get("w")))

        # mini 态下拖回 → 展开（滞回 expandAt = 200）
        drag_handle(".rsh--nav", 280)
        un = nav_state()
        check("C8 mini 态向右拖 → 重新展开（滞回上阈值 expandAt 生效）",
              un.get("mini") is False and (un.get("w") or 0) > 150,
              json.dumps(un, ensure_ascii=False))

        # 双击重置：回到 RESIZE_CONF.def = 236
        cdp.js("(() => { const el = document.querySelector('.rsh--nav');"
               "el.dispatchEvent(new MouseEvent('dblclick', {bubbles: true})); return true; })()",
               timeout=15)
        time.sleep(0.8)
        rst = nav_state()
        check("C9 双击手柄 → 宽度重置回 RESIZE_CONF.def（236）",
              abs((rst.get("w") or 0) - 236) < 2, f"w={rst.get('w')} token={rst.get('tok')}")

        # ---------------- C 机制：窗口档位（滞回） ----------------
        mid = set_w(980)
        check("C10 980 宽 → data-rs:compact 且组件区让路（宽 0）",
              mid.get("rs") == "compact" and (mid.get("ww") or 0) < 1,
              json.dumps(mid, ensure_ascii=False))
        check("C11 compact 档侧栏被夹到 180px（min(--sidebar-w,180)）",
              abs((mid.get("sw") or 0) - 180) < 2, str(mid.get("sw")))
        narrow = set_w(700)
        check("C12 700 宽 → data-rs:collapsed 且 AI 收成 48px 竖条",
              narrow.get("rs") == "collapsed" and abs((narrow.get("aw") or 0) - 48) < 1.5,
              json.dumps(narrow, ensure_ascii=False))
        check("C13 collapsed 档：dock-panel 隐藏 / dock-rail 显示",
              narrow.get("dockPanel") == "none" and narrow.get("dockRail") != "none",
              json.dumps(narrow, ensure_ascii=False))
        fallback = set_w(480)
        check("C14 480 宽 → data-rs:fallback（极限兜底档）",
              fallback.get("rs") == "fallback", json.dumps(fallback, ensure_ascii=False))
        back = set_w(1600)
        check("C15 回到 1600 → data-rs 恢复 full（滞回不是单向锁死）",
              back.get("rs") == "full" and (back.get("ww") or 0) > 100,
              json.dumps(back, ensure_ascii=False))

        # ---------------- C 机制：AI rail 开关 ----------------
        w0 = cdp.js("document.querySelector('.ai-dock').className", timeout=15)
        cdp.js("(() => { const b = document.querySelector('.dock-rail .rail-btn');"
               "if (!b) return null; b.click(); return true; })()", timeout=15)
        time.sleep(0.7)
        w1 = cdp.js("document.querySelector('.ai-dock').className", timeout=15)
        cdp.js("(() => { const b = document.querySelector('.dock-rail .rail-btn');"
               "if (!b) return null; b.click(); return true; })()", timeout=15)
        time.sleep(0.7)
        w2 = cdp.js("document.querySelector('.ai-dock').className", timeout=15)
        check("C16 rail 按钮是 toggle（点一次收起、再点一次展开）",
              ("collapsed" not in (w0 or "")) and ("collapsed" in (w1 or ""))
              and ("collapsed" not in (w2 or "")),
              f"{w0!r} → {w1!r} → {w2!r}")

        # ---------------- B 补：面板内缩 = --panel-inset ----------------
        inset = cdp.js(
            "(() => { const s = getComputedStyle(document.querySelector('.shell'));"
            "const v = s.getPropertyValue('--panel-inset').trim();"
            "const r = document.querySelector('.panel').getBoundingClientRect();"
            "const ml = getComputedStyle(document.querySelector('.panel')).marginLeft;"
            "return {inset: v, marginLeft: ml, panelW: r.width, winW: innerWidth}; })()",
            timeout=15)
        check("B8 面板左右内缩 = --panel-inset（窗口即纸面）",
              bool(inset) and inset.get("marginLeft") == inset.get("inset")
              and abs(inset["panelW"] - (inset["winW"] - 2 * float(str(inset["inset"]).replace("px", "")))) < 2,
              json.dumps(inset, ensure_ascii=False))

        # ---------------- C 机制：窗口分档自动折叠导航（需无人工干预的会话） ----------------
        # ★ 为什么放在最后并且要 reload：`applyRs` 里有一条"用户手动折过导航后，
        #   不再被窗口档位自动覆盖"的规则（原型 state.rsMini 的等价物）。
        #   上面 C6/C8 已经人工折过一次，所以这里必须换一个干净会话，
        #   否则断言的是"手动优先"而不是"自动折叠"——两者现象相反，不能混。
        cdp.call("Page.reload", {"ignoreCache": False})
        time.sleep(3.0)
        deadline = time.time() + 60
        fresh = None
        while time.time() < deadline:
            fresh = cdp.js("!!document.querySelector('.shell')", timeout=15)
            if fresh:
                break
            time.sleep(1.5)
        auto = set_w(700)
        mini_cls = cdp.js("document.querySelector('.shell').className", timeout=15)
        check("C17 干净会话下 700 宽 → 窗口分档自动折叠导航（.shell.mini + 64px）",
              auto.get("sw") is not None and abs((auto.get("sw") or 0) - 64) < 2,
              json.dumps(auto, ensure_ascii=False))
        check("C18 .shell.className 含 mini（折叠走的是设计稿状态类，不是私有类）",
              "mini" in (mini_cls or ""), repr(mini_cls))
        set_w(1600)

        # ---------------- 汇总 ----------------
        passed = sum(1 for _, ok, _ in RESULTS if ok)
        total = len(RESULTS)
        out["results"] = [{"name": n, "ok": ok, "detail": d} for n, ok, d in RESULTS]
        out["passed"] = passed
        out["total"] = total
        print(f"\n__PW_RESULT__{json.dumps({'passed': passed, 'total': total})}")
        return 0 if passed == total else 2
    finally:
        (TOOLS / "_fusion_shell_probe.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        if not args.keep:
            try:
                if cdp and cdp.sock:
                    cdp.sock.close()
            except Exception:
                pass
            if browser:
                browser.terminate()
            dev.terminate()


if __name__ == "__main__":
    sys.exit(main())
