#!/usr/bin/env python3
"""Skin Engine Runtime 验收（Edge Headless + CDP，复用 verify_tech01 基础设施）。

用例（任务规格 §6）：
  T1  Default 无覆盖状态（无 data-skin、无 --mt-skin-* 内联、:root 表原值）
  T2  Calm/Lively 切换变量变化（intensity/drift/blur/stagger/duration/accent），
      且 Interactive Gate / instant 恒不被 skin 改动
  T3  非法 skin 拒绝（schemaVersion≠1 / 禁止键 gate·instant·typography /
      越界 intensity / 非法 accent），拒绝后当前 skin 状态不变；
      未知字段忽略并出 warning
  T4  reduced 覆盖 skin：lively intensity 1.35 在 reduced 下计算值 = 0.35
  T5  off 覆盖 skin：intensity/drift/blur = 0，按钮 transition 归零
  T6  切 skin 不触发 render：childList 变更 = 0，属性变更仅在 :root
      且 ⊆ {style, data-skin}
  T7  切 skin 不触发 motion scene：startViewTransition 调用数不变、
      hasPendingPageAnims=false、无 transform/opacity 类过渡或 CSS 动画新增
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
_spec.loader.exec_module(vt)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def approx(actual: str, expected: float, tol: float = 0.001) -> bool:
    try:
        return abs(float(actual.strip()) - expected) <= tol
    except (ValueError, AttributeError):
        return False


def dur_ms(actual: str, expected: float) -> bool:
    """getComputedStyle 归一化：120ms 可能返回 '0.12s' / '.12s'。"""
    a = (actual or "").strip().lower()
    try:
        if a.endswith("ms"):
            return abs(float(a[:-2]) - expected) <= 0.001
        if a.endswith("s"):
            return abs(float(a[:-1]) * 1000 - expected) <= 0.001
    except ValueError:
        return False
    return False


# 页内观察器：T6/T7 用
SKIN_OBSERVER = """
(() => {
  if (window.__skinObs) return;
  const st = { childAdd: 0, childRm: 0, attrs: [], targets: [],
               motionTrans: 0, colorTrans: 0, cssAnim: 0 };
  const mo = new MutationObserver(rs => {
    for (const r of rs) {
      if (r.type === 'childList') { st.childAdd += r.addedNodes.length; st.childRm += r.removedNodes.length; }
      else if (r.type === 'attributes') {
        st.attrs.push(r.attributeName);
        const t = r.target;
        const desc = t === document.documentElement ? ':root'
          : (t.nodeName + '#' + (t.id || '') + '.' + (typeof t.className === 'string' ? t.className.split(' ')[0] : ''));
        st.targets.push(desc);
      }
    }
  });
  const MOTION_PROPS = /transform|opacity|translate|scale|rotate|\\bfilter\\b|margin|padding|width|height|top|left/;
  try {
    new PerformanceObserver(l => { for (const e of l.getEntries()) {
      const p = (e.propertyName || '').toLowerCase();
      if (MOTION_PROPS.test(p)) st.motionTrans++; else st.colorTrans++;
    }}).observe({ type: 'transition', buffered: false });
  } catch (e) {}
  try {
    new PerformanceObserver(l => { st.cssAnim += l.getEntries().length; })
      .observe({ type: 'animation', buffered: false });
  } catch (e) {}
  window.__skinObs = {
    start() { st.childAdd = 0; st.childRm = 0; st.attrs = []; st.targets = [];
              st.motionTrans = 0; st.colorTrans = 0; st.cssAnim = 0;
              mo.observe(document.documentElement, { attributes: true, childList: true, subtree: true }); },
    stop() { mo.disconnect(); return JSON.parse(JSON.stringify(st)); },
  };
})();
"""


def main() -> int:
    if not vt.DIST.exists():
        print("FATAL ui/dist 不存在（先 vite build）")
        return 2
    edge = vt.find_edge()
    port, srv = vt.start_server()
    base = f"http://127.0.0.1:{port}"
    dbg = vt.free_port()
    profile = tempfile.mkdtemp(prefix="pw-skin-")
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
        ws.call("Page.addScriptToEvaluateOnNewDocument", {"source": vt.VT_SPY})
        ws.call("Page.addScriptToEvaluateOnNewDocument", {"source": SKIN_OBSERVER})
        ws.call("Page.navigate", {"url": base}, timeout=15)
        # skill 坑 6：不假设就绪；skin 命名空间必须存在
        vt.wait_for(ws, "!!(window.__pwMotion && window.__pwMotion.skin && window.__skinObs && document.querySelector('#app .app-shell'))")
        ev = lambda js, t=20: vt.ev(ws, js, timeout=t)

        # headless 默认上报 reduced-motion → 显式回 standard（同 verify_tech01 口径）
        ev("window.__pwMotion.setLevel('standard')")
        boot_level = ev("window.__pwMotion.getLevel()")
        check("boot", boot_level == "standard", f"Motion Guard 显式 standard（实际 {boot_level}）")

        css = lambda prop: ev(
            f"getComputedStyle(document.documentElement).getPropertyValue('{prop}').trim()")
        btn_dur = lambda: ev(
            "getComputedStyle(document.querySelector('#app button') || document.querySelector('button')).transitionDuration")

        # ---------------- T1 Default 无覆盖 ----------------
        active0 = ev("window.__pwMotion.skin.active()")
        has_attr = ev("document.documentElement.hasAttribute('data-skin')")
        inline = ev("document.documentElement.style.getPropertyValue('--mt-skin-intensity')")
        t1 = (active0 is None and not has_attr and inline == ""
              and approx(css("--mt-intensity"), 1) and approx(css("--mt-drift"), 1)
              and dur_ms(css("--mt-dur-quick"), 120) and dur_ms(css("--mt-interactive-gate"), 240)
              and dur_ms(css("--mt-dur-instant"), 0))
        check("T1 default-no-override", t1,
              f"active={active0} data-skin={has_attr} inline='{inline}' intensity={css('--mt-intensity')} "
              f"quick={css('--mt-dur-quick')} gate={css('--mt-interactive-gate')}")
        accent_baseline = css("--accent")

        # ---------------- T2 Calm/Lively 切换 ----------------
        r = ev("window.__pwMotion.skin.apply('calm')")
        t2a = (r.get("ok") and ev("window.__pwMotion.skin.active()") == "calm"
               and ev("document.documentElement.dataset.skin") == "calm"
               and approx(css("--mt-intensity"), 0.7) and approx(css("--mt-drift"), 0.4)
               and approx(css("--mt-blur"), 0.2) and dur_ms(css("--mt-stagger"), 18)
               and dur_ms(css("--mt-interactive-gate"), 240)      # gate 恒不被 skin 动
               and dur_ms(css("--mt-dur-instant"), 0)
               and css("--accent") != accent_baseline)
        check("T2a calm-apply", t2a,
              f"intensity={css('--mt-intensity')} drift={css('--mt-drift')} blur={css('--mt-blur')} "
              f"stagger={css('--mt-stagger')} accent={css('--accent')} gate={css('--mt-interactive-gate')}")

        r = ev("window.__pwMotion.skin.apply('lively')")
        t2b = (r.get("ok") and approx(css("--mt-intensity"), 1.35)
               and dur_ms(css("--mt-dur-quick"), 100) and dur_ms(css("--mt-dur-base"), 150)
               and dur_ms(css("--mt-dur-panel"), 240)
               and dur_ms(css("--mt-interactive-gate"), 240)
               and css("--accent") != accent_baseline)
        check("T2b lively-apply", t2b,
              f"intensity={css('--mt-intensity')} quick={css('--mt-dur-quick')} "
              f"base={css('--mt-dur-base')} accent={css('--accent')}")

        r = ev("window.__pwMotion.skin.clear()")
        t2c = (r.get("ok") and ev("window.__pwMotion.skin.active()") is None
               and not ev("document.documentElement.hasAttribute('data-skin')")
               and ev("document.documentElement.style.getPropertyValue('--mt-skin-intensity')") == ""
               and approx(css("--mt-intensity"), 1) and css("--accent") == accent_baseline)
        check("T2c clear-restore", t2c,
              f"intensity={css('--mt-intensity')} accent==baseline: {css('--accent') == accent_baseline}")

        # ---------------- T3 非法 skin 拒绝 ----------------
        ev("window.__pwMotion.skin.apply('lively')")
        bad_payloads = [
            ("schema-v2", json.dumps({"schemaVersion": 2, "id": "x1", "name": "X"})),
            ("forbidden-gate", json.dumps({"schemaVersion": 1, "id": "x2", "name": "X", "motion": {"gate": 100}})),
            ("forbidden-typography", json.dumps({"schemaVersion": 1, "id": "x3", "name": "X", "motion": {"typography": {"a": 1}}})),
            ("forbidden-duration-instant", json.dumps({"schemaVersion": 1, "id": "x4", "name": "X", "motion": {"duration": {"instant": 50}}})),
            ("range-intensity", json.dumps({"schemaVersion": 1, "id": "x5", "name": "X", "motion": {"intensity": 99}})),
            ("bad-accent", json.dumps({"schemaVersion": 1, "id": "x6", "name": "X", "color": {"accent": "expression(alert(1))"}})),
            ("bad-easing", json.dumps({"schemaVersion": 1, "id": "x7", "name": "X", "motion": {"easing": {"standard": "url(evil)"}}})),
        ]
        t3_all = True
        t3_detail = []
        for tag, payload in bad_payloads:
            r = ev(f"window.__pwMotion.skin.applyJson({payload})", 15)
            ok = (not r.get("ok")) and len(r.get("errors", [])) > 0
            t3_all = t3_all and ok
            t3_detail.append(f"{tag}:{'拒绝' if ok else '错误地接受'}")
        still_lively = (ev("window.__pwMotion.skin.active()") == "lively"
                        and approx(css("--mt-intensity"), 1.35))
        check("T3 illegal-rejected", t3_all and still_lively,
              f"{'; '.join(t3_detail)}；拒绝后仍为 lively(intensity={css('--mt-intensity')})")

        # 未知字段 → 忽略 + warning，合法部分生效
        warn_payload = json.dumps({"schemaVersion": 1, "id": "warnskin", "name": "W",
                                   "futureField": True, "motion": {"unknownThing": 1, "intensity": 0.9}})
        r = ev(f"window.__pwMotion.skin.applyJson({warn_payload})", 15)
        t3w = (r.get("ok") and len(r.get("warnings", [])) >= 2
               and approx(css("--mt-intensity"), 0.9))
        check("T3w unknown-ignored-warn", t3w,
              f"ok={r.get('ok')} warnings={r.get('warnings')} intensity={css('--mt-intensity')}")
        ev("window.__pwMotion.skin.clear()")

        # ---------------- T4 reduced 覆盖 skin intensity ----------------
        ev("window.__pwMotion.skin.apply('lively')")
        ev("window.__pwMotion.setLevel('reduced')")
        t4 = (ev("document.documentElement.dataset.motion") == "reduced"
              and approx(css("--mt-intensity"), 0.35, 0.001)
              and approx(css("--mt-drift"), 0.3) and approx(css("--mt-blur"), 0)
              and approx(css("--mt-scale-on"), 0.5)
              and ev("document.documentElement.dataset.skin") == "lively")
        check("T4 reduced-overrides-skin", t4,
              f"motion=reduced + skin=lively → intensity={css('--mt-intensity')} "
              f"drift={css('--mt-drift')} blur={css('--mt-blur')} scaleOn={css('--mt-scale-on')}")
        ev("window.__pwMotion.setLevel('standard')")
        t4b = approx(css("--mt-intensity"), 1.35)
        check("T4b standard-restores-skin", t4b, f"回 standard → intensity={css('--mt-intensity')}")

        # ---------------- T5 off 覆盖 skin ----------------
        ev("window.__pwMotion.setLevel('off')")
        t5 = (ev("document.documentElement.dataset.motion") == "off"
              and approx(css("--mt-intensity"), 0) and approx(css("--mt-drift"), 0)
              and approx(css("--mt-blur"), 0)
              and dur_ms(css("--mt-interactive-gate"), 240)
              and ("0s" in btn_dur() or "0ms" in btn_dur()))
        check("T5 off-overrides-skin", t5,
              f"intensity={css('--mt-intensity')} drift={css('--mt-drift')} blur={css('--mt-blur')} "
              f"gate={css('--mt-interactive-gate')} buttonTransition={btn_dur()}")
        ev("window.__pwMotion.setLevel('standard')")

        # ---------------- T6 切 skin 不触发 render ----------------
        # 对照组：不切 skin 空等同样时长 —— 页面自身异步写样式（如 widget
        # store 迟到落地）造成的属性噪声会在对照组同样出现，差分排除。
        ev("window.__skinObs.start()")
        ctrl = ev("new Promise(r => setTimeout(() => r(window.__skinObs.stop()), 250))", 15)
        ctrl_pairs = set(zip(ctrl["attrs"], ctrl["targets"]))
        ev("window.__skinObs.start()")
        ev("window.__pwMotion.skin.apply('calm')")
        st = ev("new Promise(r => setTimeout(() => r(window.__skinObs.stop()), 250))", 15)
        pairs = list(zip(st["attrs"], st["targets"]))
        root_attrs = {a for a, t in pairs if t == ":root"}
        other_pairs = {(a, t) for a, t in pairs if t != ":root"}
        t6 = (st["childAdd"] == 0 and st["childRm"] == 0
              and root_attrs <= {"style", "data-skin"}
              and other_pairs <= ctrl_pairs)
        check("T6 no-render-on-switch", t6,
              f"childAdd={st['childAdd']} childRm={st['childRm']} :root属性={sorted(root_attrs)} "
              f"非root变更={sorted(other_pairs)}（对照组同款噪声：{sorted(other_pairs & ctrl_pairs)}）")

        # ---------------- T7 切 skin 不触发 motion scene ----------------
        vt0 = ev("window.__vtSpy.calls")
        pending0 = ev("window.__pwMotion.hasPendingPageAnims()")
        ev("window.__skinObs.start()")
        ev("window.__pwMotion.skin.apply('lively')")
        st = ev("new Promise(r => setTimeout(() => r(window.__skinObs.stop()), 450))", 15)
        vt1 = ev("window.__vtSpy.calls")
        pending1 = ev("window.__pwMotion.hasPendingPageAnims()")
        t7 = (vt1 == vt0 and pending0 is False and pending1 is False
              and st["motionTrans"] == 0 and st["cssAnim"] == 0)
        check("T7 no-motion-scene", t7,
              f"vtCalls {vt0}→{vt1} pendingAnims={pending1} motionTransitions={st['motionTrans']} "
              f"cssAnimations={st['cssAnim']} colorTransitions={st['colorTrans']}（accent 颜色渐变属变量层传播，放行）")

        # 收尾：恢复 Default
        ev("window.__pwMotion.skin.clear()")

    finally:
        try:
            proc.kill()
        except Exception:
            pass
        try:
            srv.shutdown()
        except Exception:
            pass

    n_pass = sum(1 for _, ok, _ in RESULTS if ok)
    n_all = len(RESULTS)
    out = {"date": "2026-09-14", "tool": "verify_skin_engine.py", "pass": n_pass, "total": n_all,
           "cases": [{"name": n, "ok": ok, "detail": d} for n, ok, d in RESULTS]}
    (ROOT / "tools" / "skin-verify-results.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n== Skin Engine 验收：{n_pass}/{n_all} PASS ==")
    return 0 if n_pass == n_all else 1


if __name__ == "__main__":
    sys.exit(main())
