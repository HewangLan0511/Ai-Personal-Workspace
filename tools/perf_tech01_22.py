#!/usr/bin/env python3
"""TECH-01 #22 · DevTools Performance 性能体检（Edge Headless + CDP）。

原则（白宇指令 §二/§四）：
- 只采真实浏览器数据：CDP Performance.getMetrics（Layout/RecalcStyle/Paint/
  TaskDuration 等 counter 增量）+ 页面内 PerformanceObserver('longtask') +
  MutationObserver（DOM 增删）+ rAF 帧间隔采样 + 强制读回探针（启发式）。
- 不编造 FPS；测不了就记录"无法可靠测量"。
- 每个场景独立 begin()/end() 窗口，动作全部走真实 UI 路径
  （真实锚点点击 / CDP Input 鼠标 / Emulation 真实视口 resize）。

覆盖场景（§一 10 项）：
  S1  Workspace Cinema（runtime 原语 + 探针元素）
  S2  Page Transition 连续导航 ×4
  S3a Drag（AI 侧栏宽度把手，CDP 真实鼠标）
  S3b Reorder（固件重排 ×10）
  S4  Settings 局部 diff（主题切换 ×6，真实按钮）
  S5  Plugins 页（空态打开 + 扫描动作）
  S6a Resize storm（真实视口变更 ×6）
  S6b Cinema 中断与收敛（Cinema 中真实 resize）
  S7  快速连续操作（连续导航 + 过滤 ×20）
  S8  Toast / 浮层（ModeView 真实 notify 路径）
  S9  AI Sidebar 展开/收起 ×3
  S10 Motion Guard 档位对比（standard/reduced/off × 固定动作）
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

# 复用 verify_tech01 的 CDP WebSocket 客户端 / Edge 查找 / SPA 静态服务
_spec = importlib.util.spec_from_file_location("vt01", ROOT / "tools" / "verify_tech01.py")
vt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vt)

METRIC_NAMES = ["LayoutCount", "RecalcStyleCount", "PaintCount", "TaskDuration", "ScriptDuration", "Nodes"]

PERF_PROBE = """
(() => {
  if (window.__perf) return;
  const st = { recording: false, t0: 0, longtasks: [], mutAdded: 0, mutRemoved: 0,
               reads: 0, rafGaps: 0, rafMaxGap: 0, rafFrames: 0, lastRaf: 0, maxNodes: 0 };
  try {
    new PerformanceObserver(l => { if (st.recording) for (const e of l.getEntries()) st.longtasks.push(e.duration); })
      .observe({ entryTypes: ['longtask'] });
  } catch (e) { st.longtaskUnsupported = true; }
  new MutationObserver(rs => { if (!st.recording) return;
    for (const r of rs) { st.mutAdded += r.addedNodes.length; st.mutRemoved += r.removedNodes.length; } })
    // 文档创建时刻 documentElement 尚为 null —— 以 document 兜底（Node 观察目标合法）
    .observe(document.documentElement || document, { childList: true, subtree: true });
  // 强制读回启发式探针：统计录制窗口内的几何读 API 调用次数
  for (const k of ['getBoundingClientRect', 'getClientRects']) {
    const o = Element.prototype[k];
    Element.prototype[k] = function (...a) { if (st.recording) st.reads++; return o.apply(this, a); };
  }
  for (const k of ['offsetWidth', 'offsetHeight', 'clientWidth', 'clientHeight', 'scrollTop']) {
    const d = Object.getOwnPropertyDescriptor(HTMLElement.prototype, k);
    if (d && d.get) Object.defineProperty(HTMLElement.prototype, k, { ...d,
      get() { if (st.recording) st.reads++; return d.get.call(this); } });
  }
  const loop = t => { if (st.recording && st.lastRaf) { const g = t - st.lastRaf; st.rafFrames++;
      if (g > 34) { st.rafGaps++; st.rafMaxGap = Math.max(st.rafMaxGap, g); } } st.lastRaf = t;
    requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  window.__perf = {
    begin() { st.longtasks = []; st.mutAdded = 0; st.mutRemoved = 0; st.reads = 0;
      st.rafGaps = 0; st.rafMaxGap = 0; st.rafFrames = 0; st.t0 = performance.now(); st.recording = true; },
    end() { st.recording = false;
      return { wallMs: Math.round(performance.now() - st.t0), longtasks: st.longtasks,
               mutAdded: st.mutAdded, mutRemoved: st.mutRemoved, geoReads: st.reads,
               rafGaps: st.rafGaps, rafMaxGap: Math.round(st.rafMaxGap), rafFrames: st.rafFrames }; },
  };
})();
"""


def metrics_snapshot(ws) -> dict:
    res = ws.call("Performance.getMetrics", {}, timeout=10)
    return {m["name"]: m["value"] for m in res.get("metrics", [])}


def metrics_delta(before: dict, after: dict) -> dict:
    d = {}
    for name in METRIC_NAMES:
        if name in before and name in after:
            d[name] = round(after[name] - before[name], 2)
    return d


class Perf:
    """一个场景 = begin → 动作 → end → 指标增量。"""

    def __init__(self, ws):
        self.ws = ws

    def begin(self):
        self.before = metrics_snapshot(self.ws)
        self.ws.call("Runtime.evaluate", {"expression": "window.__perf.begin()"}, timeout=8)

    def end(self, settle_s: float = 0.35):
        time.sleep(settle_s)
        r = self.ws.call("Runtime.evaluate",
                         {"expression": "window.__perf.end()", "returnByValue": True}, timeout=10)
        page = r.get("result", {}).get("value", {})
        after = metrics_snapshot(self.ws)
        return {"page": page, "cdp": metrics_delta(self.before, after)}


def run_scenario(ws, perf: Perf, sid: str, actions, settle: float = 0.4, setup=None) -> dict:
    """setup（如整页 goto）在 begin() **之前**执行：CDP 计数器随文档导航重置，
    跨导航测增量会出负值伪影 —— 导航不算动作，不进测量窗口。"""
    try:
        if setup:
            setup()
        perf.begin()
        detail = actions()
        m = perf.end(settle)
        row = {"id": sid, "detail": detail, "page": m["page"], "cdp": m["cdp"], "error": None}
    except Exception as e:  # 场景失败 ≠ 体检失败：如实记录
        try:
            ws.call("Runtime.evaluate", {"expression": "window.__perf.end()"}, timeout=5)
        except Exception:
            pass
        row = {"id": sid, "detail": None, "page": None, "cdp": None, "error": str(e)[:300]}
    print(f"[{sid}] {'ERR ' + row['error'] if row['error'] else json.dumps(row['cdp'], ensure_ascii=False)}")
    return row


def main() -> int:
    if not vt.DIST.exists():
        print("FATAL ui/dist 不存在（先 vite build）")
        return 2
    edge = vt.find_edge()
    port, srv = vt.start_server()
    base = f"http://127.0.0.1:{port}"
    dbg = vt.free_port()
    profile = tempfile.mkdtemp(prefix="pw-perf22-")
    proc = subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
         f"--user-data-dir={profile}", f"--remote-debugging-port={dbg}", "--remote-allow-origins=*",
         "--window-size=1440,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rows = []
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
        ws.call("Performance.enable")
        ws.call("Page.addScriptToEvaluateOnNewDocument", {"source": PERF_PROBE})
        ws.call("Page.addScriptToEvaluateOnNewDocument", {"source": vt.VT_SPY})
        ws.call("Page.navigate", {"url": base}, timeout=15)
        vt.wait_for(ws, "!!(window.__pwMotion && window.__perf && document.querySelector('#app .app-shell'))")
        # headless 默认 reduced-motion → 建标准档基线（同 verify_tech01 口径）
        ev = lambda js, t=15: vt.ev(ws, js, timeout=t)
        ev("window.__pwMotion.setLevel('standard')")
        perf = Perf(ws)
        sleep = lambda ms: ev(f"new Promise(r => setTimeout(r, {ms}))", 10)
        click_anchor = lambda href: ev(
            f"(() => {{ const a = document.querySelector(`.app-shell a[href=\"{href}\"]`);"
            f" if (!a) throw new Error('anchor {href} missing'); a.click(); return location.pathname }})()", 10)

        def goto(path: str, wait_js: str):
            """整页导航（dev-only 路由不在导航栏，无锚点可用）。
            PERF_PROBE 经 addScriptToEvaluateOnNewDocument 随新文档自动重注入。"""
            ws.call("Page.navigate", {"url": base + path}, timeout=15)
            vt.wait_for(ws, "!!(window.__pwMotion && window.__perf && document.querySelector('#app .app-shell'))", timeout=20)
            vt.wait_for(ws, wait_js, timeout=20)

        # ---- S1 Workspace Cinema ----
        def s1():
            return ev("""
(async () => {
  const M = window.__pwMotion;
  const host = document.createElement('div');
  host.style.cssText = 'position:fixed;inset:0;pointer-events:none;z-index:9999';
  document.body.appendChild(host);
  const targets = [];
  for (let i = 0; i < 4; i++) {
    const d = document.createElement('div');
    d.style.cssText = 'position:absolute;width:200px;height:120px;background:#fff;border-radius:8px';
    d.style.left = (100 + i * 60) + 'px'; d.style.top = (100 + i * 40) + 'px';
    host.appendChild(d); targets.push(d);
  }
  let layoutCalls = 0;
  const layout = () => { layoutCalls++;
    targets.forEach((d, i) => { d.style.left = (140 + i * 70) + 'px'; d.style.top = (80 + i * 50) + 'px'; }); };
  const h = M.startCinema({ layout });
  await h.whenInteractive;
  await h.stable;
  host.remove();
  return { layoutCalls, trace: h.trace.length, gate: h.whenInteractive ? 'resolved' : 'no' };
})()
""", 20)
        rows.append(run_scenario(ws, perf, "S1_cinema", s1, settle=0.3))

        # ---- S2 Page Transition ×4 连续 ----
        def s2():
            out = []
            for href in ["/software", "/life", "/plugins", "/device"]:
                out.append(click_anchor(href))
                sleep(40)
            sleep(1500)
            return {"navs": out, "pending": ev("window.__pwMotion.hasPendingPageAnims()", 8)}
        rows.append(run_scenario(ws, perf, "S2_page_transition_x4", s2, settle=0.2))

        # ---- S3a Drag（AI 侧栏把手，真实 CDP 鼠标）----
        def s3a():
            # 展开侧栏（如已折叠）
            ev("document.querySelector('.ai-rail')?.click(); !!document.querySelector('.ai-resizer') || document.querySelector('.ai-rail')?.click()")
            sleep(250)
            rect = ev("""
(() => { const r = document.querySelector('.ai-resizer').getBoundingClientRect();
  return { x: r.x + r.width / 2, y: r.y + r.height / 2, w: window.__pwMotion ? document.querySelector('.ai-sidebar').offsetWidth : 0 }; })()
""", 10)
            w0 = ev("document.querySelector('.ai-sidebar').offsetWidth", 8)
            x, y = rect["x"], rect["y"]
            ws.call("Input.dispatchMouseEvent", {"type": "mousePressed", "x": int(x), "y": int(y), "button": "left", "clickCount": 1}, timeout=8)
            for i in range(1, 13):  # 12 步 × 10px 向左拖 → 变宽
                ws.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": int(x - i * 10), "y": int(y), "button": "left"}, timeout=8)
                time.sleep(0.03)
            ws.call("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": int(x - 120), "y": int(y), "button": "left", "clickCount": 1}, timeout=8)
            sleep(300)
            w1 = ev("document.querySelector('.ai-sidebar').offsetWidth", 8)
            return {"width_before": w0, "width_after": w1, "drag_steps": 12}
        rows.append(run_scenario(ws, perf, "S3a_drag_ai_sidebar", s3a, settle=0.2))

        # ---- S3b Reorder ×10（固件；goto 是 setup，不进测量窗口）----
        def s3b():
            for _ in range(10):
                ev("document.querySelector('.dmh-reorder').click()", 8)
                sleep(60)
            return {"reorders": 10}
        rows.append(run_scenario(ws, perf, "S3b_reorder_x10", s3b, settle=0.3,
                                 setup=lambda: goto("/dev/motion", "!!document.querySelector('.dmh-reorder')")))

        # ---- S4 Settings 主题切换 ×6（真实按钮）----
        def s4():
            click_anchor("/settings")
            vt.wait_for(ws, "!![...document.querySelectorAll('.app-main button')].find(x => x.textContent.trim() === '深色')", timeout=20)
            out = []
            for theme in ["dark", "light", "dark", "light", "dark", "light"]:
                ev(f"(() => {{ const b = [...document.querySelectorAll('.app-main button')].find(x => x.textContent.trim() === '{'深色' if theme == 'dark' else '浅色'}');"
                   f" if (!b) throw new Error('theme button missing'); b.click(); }})()", 10)
                sleep(220)
                out.append(ev("document.documentElement.dataset.theme || 'none'", 8))
            return {"toggles": 6, "themes": out}
        rows.append(run_scenario(ws, perf, "S4_settings_theme_x6", s4, settle=0.3))

        # ---- S5 Plugins 空态打开 + 扫描动作 ----
        def s5():
            click_anchor("/plugins")
            sleep(400)
            has_table = ev("!!document.querySelector('.pw-table')", 8)
            installed_rows = ev("document.querySelectorAll('.pw-table tbody tr').length", 8) if has_table else 0
            # 点扫描（后端不在场 → 走降级/错误提示路径，同样是真实 UI 工作）
            ev("(() => { const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('扫描')); if (b) b.click(); return !!b })()", 10)
            sleep(400)
            return {"installed_rows": installed_rows, "note": "无后端，插件列表为空态"}
        rows.append(run_scenario(ws, perf, "S5_plugins_empty_state", s5, settle=0.3))

        # ---- S6a Resize storm（真实视口变更 ×6）----
        def s6a():
            click_anchor("/dashboard")
            sleep(300)
            for i, w in enumerate([1300, 1440, 1200, 1440, 1280, 1440]):
                ws.call("Emulation.setDeviceMetricsOverride",
                        {"width": w, "height": 900, "deviceScaleFactor": 1, "mobile": False}, timeout=8)
                sleep(150)
            return {"resizes": 6}
        rows.append(run_scenario(ws, perf, "S6a_resize_storm", s6a, settle=0.4))

        # ---- S6b Cinema 中断与收敛（真实 resize 打断）----
        def s6b():
            return ev("""
(async () => {
  const M = window.__pwMotion;
  let layoutCalls = 0;
  const h = M.startCinema({ layout: () => { layoutCalls++; } });
  await new Promise(r => setTimeout(r, 120));
  const t0 = performance.now();
  window.dispatchEvent(new Event('resize'));   // 真实 resize 事件（视口级另见 S6a）
  await h.stable;
  return { layoutCalls, convergeMs: Math.round(performance.now() - t0), phase: h.phase };
})()
""", 20)
        rows.append(run_scenario(ws, perf, "S6b_cinema_interrupt", s6b, settle=0.2))

        # ---- S7 快速连续操作（过滤 ×20 + SPA 连续导航 ×6）----
        def s7():
            # 侧栏锚点全路由可用：固件页过滤 ×20 后直接点侧栏做 SPA 连续导航
            for _ in range(20):
                ev("document.querySelector('.dmh-filter').click()", 8)
                sleep(30)
            for href in ["/software", "/dashboard", "/life", "/settings", "/device", "/dashboard"]:
                click_anchor(href)
                sleep(25)
            sleep(1500)
            return {"filter_toggles": 20, "navs": 6}
        rows.append(run_scenario(ws, perf, "S7_rapid_ops", s7, settle=0.2,
                                 setup=lambda: goto("/dev/motion", "!!document.querySelector('.dmh-filter')")))

        # ---- S8 Toast（ModeView 真实 notify 路径：捕获弹窗空名提交）----
        def s8():
            click_anchor("/mode")
            vt.wait_for(ws, "!![...document.querySelectorAll('.app-main button')].find(x => x.textContent.includes('保存当前环境为模式'))", timeout=20)
            ev("(() => { [...document.querySelectorAll('.app-main button')].find(x => x.textContent.includes('保存当前环境为模式')).click() })()", 8)
            vt.wait_for(ws, "!![...document.querySelectorAll('.mv-modal-mask button')].find(x => x.textContent.trim() === '记录当前环境')", timeout=20)
            ev("(() => { [...document.querySelectorAll('.mv-modal-mask button')].find(x => x.textContent.trim() === '记录当前环境').click() })()", 8)  # 空名 → notify
            sleep(250)
            toast = ev("(() => { const t = document.querySelector('.mv-toast');"
                       " return t ? t.textContent.trim() : null })()", 8)
            return {"toast": toast}
        rows.append(run_scenario(ws, perf, "S8_toast", s8, settle=0.3))

        # ---- S9 AI Sidebar 展开/收起 ×3 ----
        def s9():
            ev("document.querySelector('.ai-rail')?.click()")
            sleep(300)
            out = []
            for _ in range(3):
                ev("(() => { const c = [...document.querySelectorAll('.ai-sidebar button')].find(b => b.title === '收起侧栏'); if (c) c.click(); })()", 8)
                sleep(280)
                ev("document.querySelector('.ai-rail')?.click()", 8)
                sleep(280)
                out.append(True)
            return {"cycles": 3}
        rows.append(run_scenario(ws, perf, "S9_ai_sidebar_toggle", s9, settle=0.2))

        # ---- S10 Motion Guard 档位对比（goto 为 setup，窗口内只测档位下的动作）----
        s10 = {}
        for level in ["standard", "reduced", "off"]:
            def act(level=level):
                ev(f"window.__pwMotion.setLevel('{level}')")
                for _ in range(10):
                    ev("document.querySelector('.dmh-filter').click()", 8)
                    sleep(40)
                ev("window.__pwMotion.setLevel('standard')")
                return {"level": level, "toggles": 10}
            s10[level] = run_scenario(ws, perf, f"S10_{level}", act, settle=0.2,
                                      setup=lambda: goto("/dev/motion", "!!document.querySelector('.dmh-filter')"))
        rows.append({"id": "S10_guard_compare", "per_level": s10, "error": None})

        # ---- 汇总 ----
        def longtask_summary(r):
            if not r.get("page"):
                return None
            lt = r["page"].get("longtasks", [])
            return {"count": len(lt), "maxMs": round(max(lt), 1) if lt else 0}

        print("\n=== #22 采样汇总（全部真实测量）===")
        for r in rows:
            lt = longtask_summary(r) if "page" in r else None
            print(f"{r['id']:28s} longtask={lt} cdp={r.get('cdp')}")
        Path(ROOT / "tools" / "perf22-results.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print("results → tools/perf22-results.json")
        return 0
    finally:
        proc.terminate()
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
