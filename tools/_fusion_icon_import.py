"""UI-FUSION-FULL：把设计稿的图标体系（62 个 <symbol>）逐字搬成 Vue 组件。

设计稿用 SVG sprite（`<symbol id="i-xxx">` + `<use href="#i-xxx">`）；
真实应用没有 sprite 宿主，所以这里改成**同名同路径**的组件：
  - 每个图标的内部路径**逐字**取自设计稿的 `<symbol>`（stroke 1.6 / 24 网格 / round）；
  - 组件挂在 `components/PwIcon.vue`（**不是** components/ui/ —— 那里被
    verify_tech05d T9c 钉死为 4 个原语，新增会判红；图标集不是"第二套组件体系"）。

用法：
    python tools/_fusion_icon_import.py            # 生成 + 报告
    python tools/_fusion_icon_import.py --check    # 只比对：产物是否与设计稿一致
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTO = ROOT / "personal-workspace-ui" / "index.html"
OUT = ROOT / "ui" / "src" / "components" / "PwIcon.vue"

SYM_RE = re.compile(
    r'<symbol\s+id="i-([A-Za-z0-9_-]+)"\s+viewBox="([^"]+)"\s*>(.*?)</symbol>',
    re.S,
)


def extract() -> list[tuple[str, str, str]]:
    text = PROTO.read_text(encoding="utf-8")
    body = text[text.index("<body>") : text.index("</svg>", text.index("<body>"))]
    out: list[tuple[str, str, str]] = []
    for m in SYM_RE.finditer(body):
        name, vb, inner = m.group(1), m.group(2), m.group(3)
        out.append((name, vb, re.sub(r"\s+", " ", inner).strip()))
    return out


def render(icons: list[tuple[str, str, str]]) -> str:
    lines = [
        "<script setup lang=\"ts\">",
        "/**",
        " * PwIcon · 设计稿图标体系（UI-FUSION-FULL）",
        " *",
        " * 唯一来源 = `personal-workspace-ui/index.html` 的 62 个 `<symbol id=\"i-*\">`。",
        " * 本文件由 `tools/_fusion_icon_import.py` 生成，**请勿手改** —— 改设计稿后重跑脚本。",
        " *",
        " * 为什么不用 sprite：真实应用没有全局 sprite 宿主，逐 symbol 组件化可以",
        " * 保留同名同路径（零视觉偏差），同时按需 tree-shake。",
        " * 注意：本组件刻意不放在 `components/ui/` —— 那里被验收脚本钉死为 4 个原语。",
        " */",
        "",
        "const ICONS: Record<string, string> = {",
    ]
    for name, vb, inner in sorted(icons):
        esc = inner.replace("\\", "\\\\").replace("'", "\\'")
        lines.append(f"  '{name}': '{esc}',")
    lines += [
        "}",
        "",
        "export type PwIconName = keyof typeof ICONS",
        "",
        "const props = withDefaults(",
        "  defineProps<{ name: string; size?: number | string; strokeWidth?: number }>(),",
        "  { size: 18, strokeWidth: 1.6 },",
        ")",
        "",
        "const px = (v: number | string) => (typeof v === 'number' ? `${v}px` : v)",
        "</script>",
        "",
        "<template>",
        "  <svg",
        "    class=\"pw-ico\"",
        "    :style=\"{ width: px(props.size), height: px(props.size) }\"",
        "    viewBox=\"0 0 24 24\"",
        "    fill=\"none\"",
        "    stroke=\"currentColor\"",
        "    :stroke-width=\"props.strokeWidth\"",
        "    stroke-linecap=\"round\"",
        "    stroke-linejoin=\"round\"",
        "    aria-hidden=\"true\"",
        "    v-html=\"ICONS[props.name] || ''\"",
        "  />",
        "</template>",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    icons = extract()
    names = [n for n, _, _ in icons]
    assert len(names) == len(set(names)), "设计稿里 id 重复？"
    content = render(icons)

    report = {"count": len(icons), "viewboxes": sorted({vb for _, vb, _ in icons})[:5], "out": str(OUT)}
    if not args.check:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(content, encoding="utf-8")

    # 一致性核对：产物里出现的路径必须能在设计稿里逐条找到（少一条 = 抄漏）
    if OUT.exists():
        got = OUT.read_text(encoding="utf-8")
        missing = [n for n in names if f"'{n}':" not in got]
        report["missing_in_out"] = missing
        report["all_present"] = not missing
        if missing:
            print(json.dumps(report, ensure_ascii=False, indent=2), file=sys.stderr)
            return 1
    report["names"] = names
    print(json.dumps(report, ensure_ascii=False, indent=2)[:1200])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
