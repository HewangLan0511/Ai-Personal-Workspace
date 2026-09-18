"""UI-FUSION-FULL：把设计稿（personal-workspace-ui/index.html）的组件层 / 页面层 CSS
逐字抽出来，生成可并入 ui/src/styles/base.css 的片段。

为什么用脚本而不是手抄：
  - 逐字抽取 = 零转写误差，视觉可与设计稿逐字对齐；
  - 排除表是显式的、可复核的（哪些块有意不并入，一眼能看见）。

排除项（有意不并入，理由见 CONTEXT-PACK / LEDGER）：
  · 基础重置：:root / html / body / button / input / select / textarea / ul / h1~h4 / p / a / svg /
    :focus-visible / ::selection —— 本工程的 base.css 已有自己的重置，并入会互相覆盖；
  · 开发态展示页：.spec-* / .swatch / .demo / .comp-* / .skinlab* / .skin-sandbox / .mock-*
    —— 原型里的 Design System 展示页 / 皮肤沙箱，不进产品导航。

★ 2026-09-18 晚，**动效规范展示层（`.mt-*` + 四个 mt keyframes + `.card.sel`）解除排除**：
  设计稿把"动效规范"的入口**明确放在 设置 · 外观**（`ROUTES.showcase` 页头注释原文：
  "只做展示与切换，不进主导航 —— 主 IA 不动，入口放在设置 · 外观"）。本工程据此新增
  `/motion`（`views/MotionSpecView.vue`，不进主导航），`.mt-stage/.mt-box/.mt-row`、
  `mtPress/mtHover/mtSlide/mtModal` 与 `.card.sel` 因此有了**产品级消费方**（不再是展台）。
  解除排除前先确认消费方唯一：`.mt-*` 只被 `/motion` 使用，不会外溢到别的页面。

★ 2026-09-18 起，**壳层 / AI 面板 / Run 页 / 模型中心 / 向导** 五组已**解除排除**：
  此前（第一批）它们被排除是因为"真实应用已有自己的实现或已被冻结验收"；本批用户要求
  "以设计稿为唯一标准，把所有未落地的都落地"，故这几组改为逐字并入。
  随之引入的**类名冲突**已逐个消解（不是靠"先并入看看"）：
    - `views/ProfileView.vue` 的分区容器原用 `.panel` → 已改名 `.profile-panel`
      （`.panel` 在设计稿里是**壳层工作台面板**，一个页面分区不该占这个名字）；
    - `.shell` / `.panel` / `.sidebar` / `.content` / `.view` / `.widget-col` / `.ai-dock`
      这几个设计稿类名，本工程**没有**占用 → 由根元素同时挂"工程名 + 设计稿名"
      （如 `class="app-shell shell"`）直接复用设计稿规则，无需转写。

用法：
    python tools/_fusion_css_import.py            # 只生成片段 + 报告
    python tools/_fusion_css_import.py --apply    # 追加到 ui/src/styles/base.css（幂等：已有标记则报错）
    python tools/_fusion_css_import.py --resync   # 就地替换 base.css 里 BEGIN..END 之间的片段
                                                  #（排除表变更后重同步用；只动标记之间，标记外一字不改）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTO = ROOT / "personal-workspace-ui" / "index.html"
BASE_CSS = ROOT / "ui" / "src" / "styles" / "base.css"
OUT = ROOT / "tools" / "_fusion_css_import.out.css"
MARK_BEGIN = "/* ==== UI-FUSION-FULL:BEGIN（设计稿组件层逐字并入 · 脚本生成 · 勿手改） ==== */"
MARK_END = "/* ==== UI-FUSION-FULL:END ==== */"

# 原型样式块边界（1-based，含端点；**不含** `<style>` / `</style>` 行本身）
STYLE_BLOCKS = [(8, 1078), (5135, 5532)]

# 排除的选择器前缀/模式（作用于规则的主选择器；@media 内的规则递归判定）
EXCLUDE = [
    r"^:root$",
    r"^:root:not",
    r"^\[data-theme",
    r"^\[data-motion",
    r"^\[data-perf",
    r"^\[data-skin",
    r"^\*",
    r"^html",
    r"^body$",
    r"^button$",
    r"^button,",
    r"^button",
    r"^input",
    r"^select",
    r"^textarea",
    r"^ul$",
    r"^h1",
    r"^h2",
    r"^h3",
    r"^h4",
    r"^p$",
    r"^a$",
    r"^svg$",
    r"^:focus-visible",
    r"^::selection",
    # ---- 开发态展示页（原型里的 Design System 展台，不进产品导航） ----
    r"^\.spec-",
    r"^\.swatch",
    r"^\.demo\b",
    r"^\.comp-",
    r"^\.skinlab",
    r"^\.skin-sandbox",
    r"^\.mock-",
]
EXCLUDE_RE = [re.compile(p) for p in EXCLUDE]

# 排除表**之上**的白名单：命中 EXCLUDE、但语义**不是重置**的动效规则仍然并入。
#
# 存在理由：原型把「元素重置」与「Press 反馈」写在了同一类选择器前缀下 ——
# `button:active,.nav-item:active,…{transform:scale(var(--mt-scale-press))…}`
# 的首选择器是 `button:active`，被 `^button` 前缀排除连带丢掉，于是整个应用
# **没有任何"按下反馈"**（需求「悬浮与点击反馈」因此缺一条）。
# 这里逐条**列全名**而不是放宽 `^button`：放宽会把 `button{…}` 重置一并并入，
# 与工程自己的重置互相覆盖 —— 那正是当初排除它的原因。
UNEXCLUDE = [
    # Motion System §Press：按下 60–90ms，scale ≈ .985，不回弹、不位移。
    # 幅度走 `--mt-scale-press`（含 `--mt-intensity`），off 档自动归零 → Guard 一致。
    r"^button:active$",
]
UNEXCLUDE_RE = [re.compile(p) for p in UNEXCLUDE]


# 排除的 @keyframes 名。
# 2026-09-18 晚：集合清空 —— 动效规范展台（`.mt-box` 的唯一消费方）已成为产品页
# `/motion`，四个 mt keyframes 不再是"无消费方的孤儿"。
KEEP_KF_EXCEPT: set[str] = set()


def read_proto_css() -> str:
    lines = PROTO.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    for a, b in STYLE_BLOCKS:
        out.extend(lines[a - 1 : b])
    text = "\n".join(out)
    # 去掉 CSS 注释：否则 `/* 说明 */ .foo{...}` 的选择器会被注释前缀污染，
    # 导致排除表失配（例如 :root 块被当成未知选择器整个并入 → 触发 T4a 违规）。
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def split_blocks(text: str) -> list[tuple[str, str, str]]:
    """把一个 CSS 片段切成顶层块。返回 [(head, body, raw)]。

    head = 选择器 / at-rule 前缀（如 '@media (max-width:900px)' 或 '.card'）；
    body = 花括号内的原文（不含最外层花括号）；raw = 含花括号与换行的完整原文。
    """
    blocks: list[tuple[str, str, str]] = []
    i = 0
    n = len(text)
    while i < n:
        j = text.find("{", i)
        if j < 0:
            tail = text[i:].strip()
            if tail:
                blocks.append((tail, "", tail))
            break
        head = text[i:j].strip()
        depth = 1
        k = j + 1
        while k < n and depth:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
            k += 1
        body = text[j + 1 : k - 1]
        raw = head + "{" + body + "}"
        blocks.append((head, body, raw))
        i = k
    return blocks


def primary_selector(head: str) -> str:
    """取 at-rule 之外的第一个选择器（用于排除判定）。"""
    part = head.split(",")[0].strip()
    return re.sub(r"\s+", "", part)


def is_excluded(head: str) -> bool:
    sel = primary_selector(head)
    if sel.startswith("@"):
        return False
    if any(rx.search(sel) for rx in UNEXCLUDE_RE):
        return False
    return any(rx.search(sel) for rx in EXCLUDE_RE)


def head_name(kf_head: str) -> str:
    m = re.match(r"@keyframes\s+([A-Za-z_][A-Za-z0-9_-]*)", kf_head)
    return m.group(1) if m else ""


def filter_media(head: str, body: str) -> str | None:
    """@media 容器：逐条过滤内部规则，空则整块丢弃。"""
    kept: list[str] = []
    for h, b, _raw in split_blocks(body):
        if h.startswith("@"):
            if h.startswith("@keyframes"):
                if head_name(h) in KEEP_KF_EXCEPT:
                    continue
                kept.append(h + "{" + b + "}")
            else:
                inner = filter_media(h, b)
                if inner:
                    kept.append(inner)
            continue
        if is_excluded(h):
            continue
        kept.append(h + "{" + b + "}")
    if not kept:
        return None
    return head + "{\n" + "\n".join(kept) + "\n}"


def build() -> tuple[str, dict]:
    css = read_proto_css()
    kept: list[str] = []
    dropped: list[str] = []
    kf_seen: set[str] = set()
    kf_kept: list[str] = []
    kf_dropped: list[str] = []
    media_kept: list[str] = []

    for head, body, _raw in split_blocks(css):
        if not head.strip():
            continue
        if head.startswith("@keyframes"):
            name = head_name(head)
            if name in KEEP_KF_EXCEPT:
                kf_dropped.append(name)
                continue
            if name in kf_seen:
                # 原型两个 style 块各自重复声明同一 keyframes（后者覆盖前者）；
                # 并入时去重，避免 base.css 里出现同名重复定义。
                kf_dropped.append(name + "(重复)")
                continue
            kf_seen.add(name)
            kf_kept.append(name)
            kept.append(head + "{" + body + "}")
            continue
        if head.startswith("@media"):
            if "prefers-reduced-motion" in head:
                dropped.append(head)
                continue
            block = filter_media(head, body)
            if block:
                media_kept.append(head)
                kept.append(block)
            else:
                dropped.append(head + " (全内部规则被排除)")
            continue
        if head.startswith("@"):
            dropped.append(head)
            continue
        if is_excluded(head):
            dropped.append(primary_selector(head))
            continue
        kept.append(head + "{" + body + "}")

    body_text = "\n\n".join(kept)

    # 安全校验（两条硬约束，破了会让既有验收变红）：
    #  ① verify_tech05c T4a：自定义属性声明只能出现在 tokens.css / motion-tokens.css；
    #  ② 本文件不得出现 @import（会把样式来源挪出 base.css）。
    decl = re.findall(r"(?m)^\s*(--[A-Za-z0-9_-]+)\s*:", body_text)
    if decl:
        raise SystemExit(f"ERROR: 片段里出现了自定义属性声明 {sorted(set(decl))[:10]} —— 必须排除该块")
    if "@import" in body_text:
        raise SystemExit("ERROR: 片段里出现了 @import")

    report = {
        "kept_rules": len(kept),
        "keyframes_kept": sorted(kf_kept),
        "keyframes_dropped": sorted(kf_dropped),
        "media_kept": media_kept,
        "dropped_samples": sorted(set(dropped))[:80],
        "dropped_total": len(dropped),
        "bytes": len(body_text.encode("utf-8")),
        "lines": body_text.count("\n") + 1,
    }
    return body_text, report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="追加到 base.css")
    ap.add_argument("--resync", action="store_true",
                    help="就地替换 base.css 里 BEGIN..END 之间的片段（排除表变更后重同步）")
    args = ap.parse_args()

    body_text, report = build()
    print(json.dumps(report, ensure_ascii=False, indent=2))

    if args.apply and args.resync:
        print("ERROR: --apply 与 --resync 互斥", file=sys.stderr)
        return 2

    if args.resync:
        cur = BASE_CSS.read_text(encoding="utf-8")
        i = cur.find(MARK_BEGIN)
        j = cur.find(MARK_END)
        if i < 0 or j < 0 or j < i:
            print("ERROR: base.css 里找不到完整的 UI-FUSION-FULL 标记对", file=sys.stderr)
            return 2
        # 段头（BEGIN + 来源说明注释）原样保留：它描述"谁生成、token 从哪来"，
        # 与排除表无关；只有"片段本体"（段头之后、END 之前）需要重算。
        inner_start = cur.find("\n\n", i + len(MARK_BEGIN))
        if inner_start < 0 or inner_start >= j:
            print("ERROR: 段头结构异常，拒绝改写", file=sys.stderr)
            return 2
        prefix = cur[i:inner_start]                 # BEGIN + 段头注释
        after = cur[j + len(MARK_END):]             # END 之后（含行尾换行）
        BASE_CSS.write_text(
            cur[:i] + prefix + "\n\n" + body_text + "\n\n" + MARK_END + after,
            encoding="utf-8",
        )
        print(f"\n已就地重同步 {BASE_CSS}（段内 {report['bytes']} 字节）")
        return 0

    if not args.apply:
        OUT.write_text(body_text, encoding="utf-8")
        print(f"\n已写出片段：{OUT}")
        return 0

    cur = BASE_CSS.read_text(encoding="utf-8")
    if MARK_BEGIN in cur:
        print("ERROR: base.css 已含 UI-FUSION-FULL 段（幂等保护，请先手工回退）", file=sys.stderr)
        return 2
    section = (
        "\n\n"
        + MARK_BEGIN
        + "\n"
        + "/* 来源：personal-workspace-ui/index.html（唯一视觉源）的两个样式块。\n"
        + " * 由 tools/_fusion_css_import.py 逐字抽取；未并入的块见该脚本的 EXCLUDE 表。\n"
        + " * token 依赖（--space-N / --app-tint-* / --border-focus / --titlebar-h …）\n"
        + " * 已先落入 styles/tokens.css 的 UI-FUSION-FULL 段。\n"
        + " * keyframes 仍只落在本文件（verify_tech04 T4c 守护：全局仅 base.css 含 @keyframes）。 */\n\n"
        + body_text
        + "\n\n"
        + MARK_END
        + "\n"
    )
    BASE_CSS.write_text(cur.rstrip() + section, encoding="utf-8")
    print(f"\n已追加到 {BASE_CSS}（+{report['bytes']} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
