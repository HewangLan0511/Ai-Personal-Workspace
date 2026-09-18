"""UI-FUSION-FULL 实测：设计稿组件层是否**真的生效**（不是"文件里有"）。

跑在**生产 dist**（= Tauri `beforeBuildCommand` 的产物，也就是被打进 exe 的那份）上，
用 Edge headless + CDP 读 computed style / DOM / 样式表，逐条判定。

证据分两类，缺一不可 ——
  · 规则级（作者意图）：样式表里这些选择器的声明是否就是设计稿取值；
  · 计算级（真的生效）：真实元素上的 computed style 是否等于设计稿取值。
只查其一都会漏："文件里有但没生效"，或"生效但值被别处改掉"。

  D1  .card / .card--lg 的圆角与内边距来自设计稿（--r-xl / --pad-card-lg）
      D1d/D1e 原语层别名一致性：`.pw-card` / `.pw-t-*` / `.pw-btn` 必须与设计稿同值
      （primitives.css 加载在 base.css 之后，会把设计值盖回去 —— 2026-09-18 实测 10 处漂移）
  D2  .life-grid 四列；.life-card.span2 真的横跨两列
  D3  .badge 为 inline-flex 且高 22px
  D4  .btn 几何来自设计稿（inline-flex / 32px）；.btn--primary 用 --brand-500
  D5  .switch 36×20，::after 为 16px 圆点
  D6  .progress 6px / .progress.thin 4px
  D7  .metric .v 字号 19px（设备页）
  D8  图标体系：.ico 是 <svg>、有子节点、stroke-width 1.6
  D9  设计稿变量全部解析（--space-* / --app-tint-* / 细粒度 --mt-dur-*）
  D10 设计稿新增的 13 组 keyframes 已注册
  D11 暗色：.card 底色跟随 token（不是写死的白）
  D12 零未解析变量（base.css 用到的 var() 在页面上都有值）
  D13 各页 .page-head 存在
  D14 组件层规则覆盖度（抽样 ≥55 条真的在样式表里）

用法：$VENV tools/_force_design_check.py
产物：tools/_force_design_check.json
"""

from __future__ import annotations

import functools
import http.server
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
DIST = ROOT / "ui" / "dist"
BASE_CSS = ROOT / "ui" / "src" / "styles" / "base.css"

_spec = importlib.util.spec_from_file_location("fav", str(TOOLS / "_force_app_verify.py"))
fav = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fav)  # type: ignore[union-attr]


def find_edge() -> str | None:
    for var in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432", "LOCALAPPDATA"):
        base = os.environ.get(var)
        if not base:
            continue
        p = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
        if p.exists():
            return str(p)
    return shutil.which("msedge")


# 每个选择器只在"保证它有值"的那一页上量：无 core 时列表类数据为空，
# 所以只用不依赖数据的结构性元素。
PAGE_SELECTORS: dict[str, list[str]] = {
    "/life": [".btn", ".life-grid", ".life-card", ".life-card.span2", ".pw-ico", ".page-head"],
    "/device": [".card", ".card.card--lg", ".badge", ".metric", ".metric .v",
                ".progress.thin", ".progress.thin > i", ".pw-ico"],
    "/plugins": [".switch", ".tile", ".row-item", ".pw-ico", ".page-head"],
    # 首页的设计稿头部是 .greet（首页不用 page-head，而是问候行 + 分区）
    # `.nowplaying` = 设计稿 `fn:nowPlaying` 的音乐条（第五批归位；无会话时是 `.idle` 态，恒在 DOM）
    "/dashboard": [".greet", ".sec", ".nowplaying"],
    # 工作模式页：`.new-card`（设计稿 `page:workspaces` 末尾的新建虚线卡）恒在列表视图里
    "/mode": [".new-card"],
    # 下面是原语层的**精确**选择器（排除变体，否则量到的是同族里另一个元素的取值）：
    # `.pw-card` 在 /models 上第一个命中项就是带 `--lg` 的当前模型卡；`.pw-btn` 第一个命中的
    # 是头部返回按钮 `--icon`（30×30）。用变体去量基类 == 假红。
    "/models": [".pw-card:not(.pw-card--lg)", ".pw-card--lg",
                ".pw-t-page", ".pw-t-section", ".pw-t-card", ".pw-t-label",
                ".pw-btn:not(.pw-btn--icon):not(.pw-btn--sm):not(.pw-btn--lg)",
                # button 重置复位（第四批）：这三个在 /models 上**必然存在** ——
                # `.pw-btn--icon` = 页头返回按钮；`.icon-btn` = AI 侧栏收起键（壳层常驻）；
                # `.seg button` = AI 侧栏模式切换（壳层常驻）。
                ".pw-btn--icon", ".icon-btn", ".seg button"],
    # AI 页：设计稿的下划线式 `.tabs` 只在这里消费（tab 恒存在，不依赖数据）。
    "/ai": [".tabs", ".tabs button", ".ai-grid"],
}

RULE_SELECTORS = [
    ".card", ".card--lg", ".btn", ".btn--primary", ".badge", ".badge--brand",
    ".switch", ".switch::after", ".tabs", ".seg", ".checkbox", ".radio",
    ".progress", ".progress > i", ".skel", ".spinner", ".empty", ".error",
    ".tile", ".row-item", ".ctx-menu", ".arrange-row", ".wizard", ".pick",
    ".timeline", ".tl-item", ".life-grid", ".life-card", ".metric", ".metric .v",
    ".spark", ".app", ".minimap", ".stat", ".rsh", ".drop-target", ".dragging",
    ".hover-only", ".sr-only", ".launching", ".progress-fill", ".modal", ".toast",
    ".tip", ".ws-card", ".ws-grid", ".new-card", ".hero", ".greet", ".nowplaying",
    # 原语层别名（primitives.css 加载在后，必须逐条等于设计稿取值）
    ".pw-card", ".pw-card--lg", ".pw-card--hoverable:hover", ".pw-btn", ".pw-t-section",
    ".widget-col", ".wcard", ".widget-add", ".app-square", ".app-row", ".app-pick",
    ".icon-btn", ".search", ".select", ".field", ".avatar", ".chip", ".chip--brand",
    ".drawer", ".scrim", ".live", ".sort-hint",
]

PROBE = """(() => {
  const sel = __SELS__;
  const root = getComputedStyle(document.documentElement);
  const tok = n => root.getPropertyValue(n).trim();
  const probe = {};
  for (const q of sel) {
    const e = document.querySelector(q);
    if (!e) { probe[q] = null; continue; }
    const c = getComputedStyle(e);
    const r = e.getBoundingClientRect();
    probe[q] = {
      tag: e.tagName, display: c.display, radius: c.borderRadius, pad: c.paddingTop,
      borderW: c.borderWidth,
      width: c.width, height: c.height, rectH: Math.round(r.height), rectW: Math.round(r.width),
      transDur: c.transitionDuration,
      fontSize: c.fontSize, strokeWidth: c.strokeWidth,
      gridCols: c.gridTemplateColumns.split(' ').length, gridColumn: c.gridColumn,
      gap: c.gap, children: e.children.length,
      textTransform: c.textTransform, letterSpacing: c.letterSpacing,
      afterW: getComputedStyle(e, '::after').width,
    };
  }
  const kf = [...document.styleSheets]
    .flatMap(s => { try { return [...s.cssRules]; } catch (e) { return []; } })
    .filter(r => r.type === 7).map(r => r.name);
  return {
    path: location.pathname, probe, kf,
    tokens: {
      space4: tok('--space-4'), space12: tok('--space-12'), space16: tok('--space-16'),
      tint4: tok('--app-tint-4'), borderFocus: tok('--border-focus'),
      mtDurPress: tok('--mt-dur-press'), mtDurHover: tok('--mt-dur-hover'),
      mtDurDrawer: tok('--mt-dur-drawer'), mtEaseOut: tok('--mt-ease-out'),
      mtDistPanel: tok('--mt-dist-panel'), mtScalePress: tok('--mt-scale-press'),
      brand500: tok('--brand-500'), surface1: tok('--surface-1'),
      padCard: tok('--pad-card'), padCardLg: tok('--pad-card-lg'), rXl: tok('--r-xl'),
    },
    lifeCards: [...document.querySelectorAll('.life-card')].map(e => getComputedStyle(e).gridColumn),
    iconCount: document.querySelectorAll('svg.pw-ico').length,
  };
})()"""

RULE_PROBE = """(() => {
  const sels = __SELS__;
  const out = {};
  // 坑：新版 Chrome 的 CSSStyleRule 也带 cssRules（嵌套 CSS 支持），
  // 且空列表是**真值对象** —— 先判 cssRules 会把每条规则都当容器跳过，
  // 结果恒为空。故先取 selectorText，再按需递归。
  const walk = rules => { for (const r of rules) {
    if (r.selectorText && r.style) {
      for (const q of sels) {
        if (r.selectorText.split(',').map(x => x.trim()).indexOf(q) >= 0) {
          out[q] = (out[q] || '') + r.style.cssText + ';';
        }
      }
    }
    if (r.cssRules && r.cssRules.length) walk(r.cssRules);
  } };
  for (const sh of document.styleSheets) { try { walk(sh.cssRules); } catch (e) {} }
  return out;
})()"""

DARK = """(() => {
  const card = document.querySelector('.card');
  const c = card ? getComputedStyle(card) : null;
  return {
    cardBg: c ? c.backgroundColor : null,
    tokenSurface1: getComputedStyle(document.documentElement).getPropertyValue('--surface-1').trim(),
  };
})()"""


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        p = Path(self.translate_path(self.path))
        if (not p.exists() or p.is_dir()) and "." not in p.name:
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, *a):
        pass


def vars_used() -> list[str]:
    css = BASE_CSS.read_text(encoding="utf-8")
    return sorted(set(re.findall(r"var\(\s*(--[A-Za-z0-9_-]+)", css)))


def flat(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def main() -> int:
    edge = find_edge()
    if edge is None:
        print("未找到 Edge，无法渲染")
        return 1

    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 4977), functools.partial(SPAHandler, directory=str(DIST)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    port = fav.free_port()
    prof = tempfile.mkdtemp(prefix="pw-design-")
    proc = subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
         "--window-size=1280,900", "--force-device-scale-factor=1",
         f"--user-data-dir={prof}", f"--remote-debugging-port={port}",
         "http://127.0.0.1:4977/life"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    out: dict = {"pages": {}, "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        cdp = fav.CDP(port, want="127.0.0.1")
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        cdp.call("Emulation.setDeviceMetricsOverride",
                 {"width": 1280, "height": 900, "deviceScaleFactor": 1, "mobile": False})

        for route, sels in PAGE_SELECTORS.items():
            cdp.call("Page.navigate", {"url": f"http://127.0.0.1:4977{route}"})
            time.sleep(2.6)
            r = cdp.js(PROBE.replace('__SELS__', json.dumps(sels))) or {}
            r["route"] = route
            out["pages"][route] = r
            heights = {k: (v or {}).get("rectH") for k, v in (r.get("probe") or {}).items()}
            print(f"{route:12s} icons={r.get('iconCount')} kf={len(r.get('kf') or [])} rectH={heights}")

        out["rules"] = cdp.js(RULE_PROBE.replace('__SELS__', json.dumps(RULE_SELECTORS))) or {}

        cdp.call("Page.navigate", {"url": "http://127.0.0.1:4977/device"})
        time.sleep(2.4)
        cdp.js("document.documentElement.setAttribute('data-theme','dark')")
        time.sleep(0.7)
        out["dark"] = cdp.js(DARK)
        cdp.js("document.documentElement.removeAttribute('data-theme')")
        time.sleep(0.4)

        names = vars_used()
        js = ("(() => { const r = getComputedStyle(document.documentElement); const out = {};"
              " const names = " + json.dumps(names) + ";"
              " for (const n of names) out[n] = r.getPropertyValue(n).trim(); return out; })()")
        vals = cdp.js(js) or {}
        out["unresolved_vars"] = sorted(k for k, v in vals.items() if not str(v).strip())
        out["vars_checked"] = len(names)
    finally:
        proc.terminate()
        srv.shutdown()

    life = out["pages"].get("/life", {})
    dev = out["pages"].get("/device", {})
    plg = out["pages"].get("/plugins", {})
    lp = life.get("probe") or {}
    dp = dev.get("probe") or {}
    pp = plg.get("probe") or {}
    mp = (out["pages"].get("/models", {}).get("probe")) or {}
    ap = (out["pages"].get("/ai", {}).get("probe")) or {}
    PW_BTN = ".pw-btn:not(.pw-btn--icon):not(.pw-btn--sm):not(.pw-btn--lg)"
    tokens = life.get("tokens") or {}
    rules = out.get("rules") or {}
    kfs = set(dev.get("kf") or [])
    life_cards = [str(c) for c in (life.get("lifeCards") or [])]

    need_kf = {"toastIn", "fadeIn", "modalIn", "drawerIn", "skel", "swapFlash", "ctxIn",
               "okFlash", "errShake", "rshArm", "rshCrest", "swapIn", "pulse"}
    rule_hits = [k for k, v in rules.items() if v]

    # 页头：/dashboard 的设计稿头部是 .greet（首页不用 page-head），其余页用 .page-head
    head_ok = all(
        (p.get("probe") or {}).get(".page-head") is not None
        for p in out["pages"].values()
        if ".page-head" in PAGE_SELECTORS.get(p.get("route"), []))
    greet_ok = (out["pages"].get("/dashboard", {}).get("probe") or {}).get(".greet") is not None

    checks = {
        # --- 规则级（作者意图）：设计稿取值确实写在样式表里 ---
        "D1_rules_card": "border-radius:var(--r-xl)" in flat(rules.get(".card")),
        "D1b_rules_card_lg": "padding:var(--pad-card-lg)" in flat(rules.get(".card--lg")),
        "D4b_rules_btn_primary": "brand-500" in flat(rules.get(".btn--primary")),
        "D5_rules_switch": "width:36px" in flat(rules.get(".switch"))
            and "height:20px" in flat(rules.get(".switch")),
        "D6_rules_progress": "height:6px" in flat(rules.get(".progress")),
        "D9_rules_motion_vocab": "col-resize" in flat(rules.get(".rsh"))
            and "width:9px" in flat(rules.get(".rsh")),
        # --- 计算级（真的生效） ---
        # 注意：computed display 会被父级 flex 上下文"块化"（inline-flex → flex），
        # 所以判据接受两者；这本身也证明元素确实处在设计稿的 flex 排版里。
        "D1c_applied_card_radius": (dp.get(".card") or {}).get("radius") == "16px",
        # 原语层别名一致性：`.pw-card` 必须真的消费设计稿 token（--pad-card / --pad-card-lg / --r-xl）。
        # main.ts 里 primitives.css 在 base.css **之后** ⇒ `.pw-card` 会盖住设计稿 `.card`；
        # 只量设计类看不见这个漂移（2026-09-18 实测曾差 4px：16px vs 20px）。
        # 原语层别名一致性：`.pw-card` 必须**字面**消费设计稿 token（--pad-card / --pad-card-lg / --r-xl）。
        # main.ts 里 primitives.css 在 base.css **之后** ⇒ `.pw-card` 会盖住设计稿 `.card`；
        # 只量设计类看不见这个漂移（2026-09-18 实测曾差 4px：16px vs 20px）。
        # 基类用**规则级**判据：DOM 里第一个 `.pw-card` 常是页面自己加过 padding 的变体
        # （/models 的空态卡 `.mv-empty` 覆写成 32px）——拿它量基类会假红。
        # 计算级只留 `.pw-card--lg`（/models 上 = 当前模型卡，无页面覆写）证明"确实生效"。
        "D1d_applied_pw_card_matches_design": (
            "padding:var(--pad-card)" in flat(rules.get(".pw-card"))
            and "border-radius:var(--r-xl)" in flat(rules.get(".pw-card"))
            and "padding:var(--pad-card-lg)" in flat(rules.get(".pw-card--lg"))
            and "translateY(-1px)" in flat(rules.get(".pw-card--hoverable:hover"))
            and "shadow-md" in flat(rules.get(".pw-card--hoverable:hover"))
            and (mp.get(".pw-card--lg") or {}).get("pad") == tokens.get("padCardLg")
        ),
        # 原语层排版别名：设计稿档位 = page 20 / section 15 / card 14 / label 11+uppercase。
        # 只量设计 `.t-*` 看不见原语层——曾实测 `.pw-t-section` 16px（设计 15px）、
        # `.pw-t-card` 15px（设计 14px）、`.pw-t-label` 缺 `text-transform`。
        "D1e_applied_pw_typography_matches_design": (
            (mp.get(".pw-t-page") or {}).get("fontSize") == "20px"
            and (mp.get(".pw-t-section") or {}).get("fontSize") == "15px"
            and (mp.get(".pw-t-card") or {}).get("fontSize") == "14px"
            and (mp.get(".pw-t-label") or {}).get("textTransform") == "uppercase"
            and (mp.get(PW_BTN) or {}).get("height") == "34px"
        ),
        # button 重置复位（第四批）：设计稿的基础重置 `button{background:none;border:0}` 在并入时被
        # 整组排除，而工程版重置带一个**可见盒子**（`background:--panel` + `border:1px --border`）。
        # 于是所有假设"裸 button"的设计稿类都被硬塞了一圈灰边（`.icon-btn` 30×30 应透明、
        # `.seg button` 段间不该有竖线、`.tabs button`、`.btn`/`.pw-btn` 设计上**无边框**、
        # `--primary` 尤其明显）。修法是"只对设计稿类名精确复位"，不改工程重置本身
        # （工程期还有大量 `class="primary"` 裸按钮靠它活着）。
        # 判据必须是**计算级**：只量设计类的产出值看不见"被别处重置污染"这一类漂移。
        "D1f_applied_button_border_reset": (
            (mp.get(".pw-btn--icon") or {}).get("borderW") == "0px"
            and (mp.get(".icon-btn") or {}).get("borderW") == "0px"
            and (mp.get(".seg button") or {}).get("borderW") == "0px"
            and (ap.get(".tabs button") or {}).get("borderW") == "0px"
        ),
        # 第五批「页面内部结构归位」的计算级守卫：设计稿类必须真的出现在对应页面的 DOM 上
        # （只改 CSS/类名不改元素 = 有规则无消费方，这一条会红）。
        # 选的都是**恒在**的选择器，避免依赖数据（模式列表/软件列表为空时也不假红）。
        "D1g_fifth_batch_page_bindings": (
            (out["pages"].get("/dashboard", {}).get("probe") or {}).get(".nowplaying") is not None
            and (out["pages"].get("/mode", {}).get("probe") or {}).get(".new-card") is not None
        ),
        "D2_applied_life_grid_4col": (lp.get(".life-grid") or {}).get("gridCols") == 4,
        "D2b_applied_span2": any(c.startswith("span 2") for c in life_cards),
        "D3_applied_badge": (dp.get(".badge") or {}).get("display") in ("inline-flex", "flex")
            and (dp.get(".badge") or {}).get("height") == "22px",
        "D4_applied_btn": (lp.get(".btn") or {}).get("display") in ("inline-flex", "flex")
            and (lp.get(".btn") or {}).get("rectH") in (28, 32),
        "D5b_applied_switch_knob": (pp.get(".switch") or {}).get("afterW") == "16px",
        "D6b_applied_progress_thin": (dp.get(".progress.thin") or {}).get("rectH") == 4,
        "D7_applied_metric_v": (dp.get(".metric .v") or {}).get("fontSize") == "19px",
        "D8_applied_icons": (life.get("iconCount") or 0) >= 5
            and (lp.get(".pw-ico") or {}).get("tag") == "svg"
            and (lp.get(".pw-ico") or {}).get("children", 0) >= 1
            and (lp.get(".pw-ico") or {}).get("strokeWidth") == "1.6px",
        # 设计稿字面 token 必须精确解析
        "D9b_tokens_literal": tokens.get("space4") == "16px" and tokens.get("space12") == "48px"
            and tokens.get("space16") == "64px" and (tokens.get("tint4") or "").lower() == "#f3edfb"
            and (tokens.get("borderFocus") or "").lower() == "#6e8be6",
        # 派生时长必须是 calc 表达式（挂在 Skin 通道上），而不是另立字面值。
        # 浏览器会把 var() 代入后返回 calc(.12s * 2 / 3) —— 出现 calc( 即证明是派生的。
        "D9c_tokens_derived_wired": all(
            "calc(" in (tokens.get(k) or "") for k in ("mtDurPress", "mtDurHover", "mtDistPanel")),
        # 端到端：设计稿 --dur-* 桥接真的落在了元素的 transition 上
        # （.switch 用 --dur-fast=160ms；.row-item 用 --dur-micro=120ms）
        "D9d_duration_end_to_end": (pp.get(".switch") or {}).get("transDur") == "0.16s"
            and (pp.get(".row-item") or {}).get("transDur") == "0.12s",
        "D10_keyframes_registered": need_kf.issubset(kfs),
        "D11_dark_card_tokenised": (out.get("dark") or {}).get("cardBg") not in (None, "rgb(255, 255, 255)"),
        "D12_zero_unresolved_vars": not out.get("unresolved_vars"),
        "D13_page_head_present": head_ok and greet_ok,
        "D14_rule_coverage": len(rule_hits) >= 55,
    }

    out["checks"] = checks
    (TOOLS / "_force_design_check.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    for k, v in checks.items():
        print(("  PASS  " if v else "  FAIL  ") + k)
    print("\nrules found:", len(rule_hits), "/", len(RULE_SELECTORS))
    print("rules missing:", [k for k in RULE_SELECTORS if not rules.get(k)])
    print("unresolved vars:", out.get("unresolved_vars"))
    print("dark:", json.dumps(out.get("dark"), ensure_ascii=False))
    print("ALL OK:", all(checks.values()))
    return 0 if all(checks.values()) else 3


if __name__ == "__main__":
    raise SystemExit(main())
