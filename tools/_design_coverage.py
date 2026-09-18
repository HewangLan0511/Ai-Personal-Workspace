"""设计稿覆盖度审计（静态）：原型**实际渲染用到的 class** vs 本工程引用情况。

只回答一个问题：**设计稿里的东西，本工程到底接了多少。**

口径（避免自欺）：
  · "原型用到的类" = 出现在 index.html 的 `<style>` **之外**（即模板/HTML 结构里）的 class 名。
    只出现在 CSS 里的类（比如 `:hover` 附加态、JS 运行时才加的瞬态类）不算"内容"，
    但会单独列出来，因为它们同样需要被实现（否则交互态就丢了）。
  · "已接" = 该 class 字面量出现在 ui/src 下任意 .vue/.ts/.css 里。
    这一条只能证明"接线在"，不能证明"生效" —— 生效由 CDP 探针（_force_*.py）负责。
  · 覆盖度按**原型 markup 出现次数**加权：出现越多 = 视觉越重，优先补。

⚠️ **松口径的已知虚高（2026-09-18 补）**：`ui/src/styles/base.css` 含设计稿组件层**全部**规则，
  所以任何设计类名都能在 base.css 里"字面命中" ⇒ 默认口径会把"规则在、但没有任何 .vue 在用"
  的类算作已接。用 `--strict` 排除 CSS，只在 **.vue 的模板/脚本**里找 —— 那才是
  "内容真的接了没有"的口径。两个数都要看：
    · 默认（含 CSS）= 设计稿有没有被"接进代码库"
    · `--strict`（仅 .vue）= 页面有没有真的在用它
  两者之差 = **有规则、无消费方**（含 base.css 里的全部设计类，属正常；生产页前缀类则是真缺口）。

用法：python tools/_design_coverage.py [--json out.json] [--strict] [--top N]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROTO = ROOT / "personal-workspace-ui" / "index.html"
SRC = ROOT / "ui" / "src"

# 瞬态/运行时类（JS 里 classList.add/remove 加的），单独成组核对
TRANSIENT = {
    "scene-in", "scene-out", "enter-up", "swap-in", "just-swap", "ok-flash",
    "err-shake", "cinema-entering", "cinema-stabilizing", "cinema", "mini",
    "dragging", "armed", "shown", "open", "on", "active", "is-active",
    "is-grab", "is-managed", "is-live", "manual", "noscroll", "collapsed",
}

# 通用/工具类：设计稿与工程侧共用，不算"内容缺失"
UTILITY = {"page", "view", "shell", "panel", "content", "sidebar", "sr-only", "grow"}


def extract_styles(html: str) -> tuple[str, str]:
    """返回 (style_blocks, markup_without_style)。"""
    blocks = re.findall(r"<style[^>]*>(.*?)</style>", html, flags=re.S)
    markup = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.S)
    return "\n".join(blocks), markup


CLASS_RE = re.compile(r'class\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|`([^`]*)`)')


def classes_in(text: str) -> Counter:
    c: Counter = Counter()
    for m in CLASS_RE.finditer(text):
        raw = m.group(1) or m.group(2) or m.group(3) or ""
        # 模板串里的 ${...} 会掺进来，先切掉
        raw = re.sub(r"\$\{[^}]*\}", " ", raw)
        for tok in raw.split():
            tok = tok.strip()
            if not tok or not re.fullmatch(r"[a-zA-Z][\w-]*", tok):
                continue
            c[tok] += 1
    return c


def css_selectors(css: str) -> set[str]:
    """CSS 里出现过的 class 选择器（不含声明块内容）。"""
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    body = re.sub(r"\{[^{}]*\}", "{}", body)  # 去掉声明，只留选择器
    return set(re.findall(r"\.([a-zA-Z][\w-]*)", body))


def referenced_in_src(name: str, blob: str) -> bool:
    return re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", blob) is not None


# 原型 JS 里的"块锚点"：ROUTES.<页> = / function <名>( / const <名> = [
# 用途：把每个缺口类归属到它真正出现在哪个原型页面（否则只知道"少了什么"，不知道"去哪补"）。
ANCHOR_RE = re.compile(
    r"ROUTES\.([A-Za-z0-9_]+)\s*="
    r"|(?:^|\n)function\s+([A-Za-z0-9_]+)\s*\("
    r"|(?:^|\n)const\s+([A-Za-z0-9_]+)\s*="
)


def block_spans(markup: str) -> list[tuple[str, int]]:
    """返回 [(label, start), ...]，按出现顺序排序；label 形如 `page:models` / `fn:modelCardHTML`。"""
    spans: list[tuple[str, int]] = []
    for m in ANCHOR_RE.finditer(markup):
        if m.group(1):
            label = f"page:{m.group(1)}"
        elif m.group(2):
            label = f"fn:{m.group(2)}"
        else:
            label = f"const:{m.group(3)}"
        spans.append((label, m.start()))
    spans.sort(key=lambda x: x[1])
    return spans


def label_at(spans: list[tuple[str, int]], idx: int) -> str:
    cur = "?"
    for label, start in spans:
        if start <= idx:
            cur = label
        else:
            break
    return cur


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None,
                    help="默认 _design_coverage.json（--strict 时为 _design_coverage.strict.json）")
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--strict", action="store_true",
                    help="只把 .vue（模板/脚本）当消费方 —— 排除 base.css 的'规则在但没人用'虚高")
    args = ap.parse_args()
    if args.json is None:
        args.json = str(ROOT / "tools" / (
            "_design_coverage.strict.json" if args.strict else "_design_coverage.json"))

    html = PROTO.read_text(encoding="utf-8")
    css, markup = extract_styles(html)

    used_in_markup = classes_in(markup)
    declared_in_css = css_selectors(css)

    # 工程侧全文：默认口径含 css（设计类只要在 base.css 的选择器里出现就算"已接入规则"）；
    # --strict 只收 .vue —— 那才是"页面真的在用它"。
    src_blob = ""
    if args.strict:
        for p in list(SRC.rglob("*.vue")):
            src_blob += p.read_text(encoding="utf-8") + "\n"
    else:
        for p in list(SRC.rglob("*.vue")) + list(SRC.rglob("*.ts")) + list(SRC.rglob("*.css")):
            src_blob += p.read_text(encoding="utf-8") + "\n"

    missing, landed = [], []
    for name, n in used_in_markup.most_common():
        if name in UTILITY:
            continue
        (landed if referenced_in_src(name, src_blob) else missing).append((name, n))

    # CSS-only 类：设计稿里存在的交互态，工程侧没提过 = 状态丢失风险
    css_only_missing = []
    for name in sorted(declared_in_css):
        if name in used_in_markup or name in UTILITY:
            continue
        if not referenced_in_src(name, src_blob):
            css_only_missing.append(name)

    total = len(landed) + len(missing)
    pct = (len(landed) / total * 100) if total else 100.0
    markup_total = sum(used_in_markup.values())
    markup_landed = sum(n for _, n in landed)

    # 开发态页面（不进产品导航）单独归类，避免把"故意不接"混进缺口
    DEV_PREFIX = ("skinlab", "spec-", "mt-", "mock-", "swatch", "demo", "comp-", "skin-")
    dev = [(n, k) for n, k in missing if n.startswith(DEV_PREFIX)]
    prod = [(n, k) for n, k in missing if not n.startswith(DEV_PREFIX)]

    mode = "STRICT（仅 .vue 消费方）" if args.strict else "默认（含 CSS：规则级接入）"
    print("=" * 66)
    print(f"设计稿覆盖度审计（静态）· {mode}")
    print("=" * 66)
    print(f"原型 markup 用到的 class 种类 : {total}")
    print(f"  已在本工程出现              : {len(landed)}  ({pct:.1f}%)")
    print(f"  未出现                      : {len(missing)}"
          f"（生产页 {len(prod)} / 开发页 {len(dev)}）")
    print(f"原型 markup 类引用总次数       : {markup_total}（已接 {markup_landed}，"
          f"{markup_landed / markup_total * 100 if markup_total else 100:.1f}%）")
    print(f"  未接引用次数                : {sum(k for _, k in missing)}"
          f"（生产页 {sum(k for _, k in prod)} / 开发页 {sum(k for _, k in dev)}）")
    print(f"CSS-only 且本工程未提及的类    : {len(css_only_missing)}")
    print()

    cap = args.top or 60
    if prod:
        print(f"--- 生产页缺口（按原型出现次数降序，前 {cap}）---")
        for name, n in prod[:cap]:
            print(f"  {n:4d}  .{name}")
        print()

    # 缺口 → 原型页面归属（"去哪补"）：只在原型 markup 里定位每个类的出现位置，
    # 取它落在哪个块（ROUTES.x= / function x() / const x=）内。
    spans = block_spans(markup)
    where: dict[str, list[str]] = {}
    for name, _ in prod:
        pat = re.compile(r'class\s*=\s*(?:"[^"]*\b' + re.escape(name) + r'\b[^"]*"'
                          r"|'[^']*\b" + re.escape(name) + r"\b[^']*'"
                          r"|`[^`]*\b" + re.escape(name) + r"\b[^`]*`)")
        seen: list[str] = []
        for m in pat.finditer(markup):
            lb = label_at(spans, m.start())
            if lb not in seen:
                seen.append(lb)
        where[name] = seen
    if where:
        print("--- 缺口 → 原型页面归属（同级按页分组）---")
        bypage: dict[str, list[str]] = {}
        for name, n in prod:
            for lb in where.get(name) or ["?"]:
                bypage.setdefault(lb, []).append(f".{name}({n})")
        for lb in sorted(bypage):
            print(f"  {lb:28s} {len(bypage[lb]):3d} 个: " + "  ".join(bypage[lb][:14]))
        print()
    if dev:
        print("--- 开发态页面缺口（不进产品导航，登记为'不接'）---")
        print("  " + "  ".join(f".{n}" for n, _ in dev))
        print()

    if css_only_missing:
        print("--- CSS-only 未提及（前 40）---")
        for i in range(0, min(len(css_only_missing), 40), 6):
            print("  " + "  ".join("." + x for x in css_only_missing[i:i + 6]))
        print()

    out = {
        "mode": "strict" if args.strict else "default",
        "markup_class_total": total,
        "landed": [n for n, _ in landed],
        "missing": [{"class": n, "count": c} for n, c in missing],
        "missing_prod": [{"class": n, "count": c} for n, c in prod],
        "missing_dev": [{"class": n, "count": c} for n, c in dev],
        "css_only_missing": css_only_missing,
        "coverage_pct": round(pct, 2),
        "markup_ref_coverage_pct": round(markup_landed / markup_total * 100, 2) if markup_total else 100.0,
    }
    Path(args.json).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
