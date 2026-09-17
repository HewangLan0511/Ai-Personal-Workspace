#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提示词模板加载与渲染（08 §4）

模板集中放在 `ai/prompt/`，**禁止散落在代码里**（08 §4 硬要求）。
变量语法 `{{变量名}}`。

## 设计取舍

不用 Jinja2（sidecar 是 stdlib-only）。用正则做单遍替换：
  - 未提供的变量**原样保留**（`{{foo}}`）而不是替换成空 —— 这样漏传变量时
    在输出里一眼可见，而不是静默变成一句缺词的话。
  - 不提供条件/循环语法。提示词模板不需要图灵完备；
    需要动态内容时由 context.py 装配好后整体作为 `{{context}}` 传入。
"""

from __future__ import annotations

import os
import re
from typing import Any

PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt")

# 阶段5 需要的模板（其余的 V2 模板也已就位，供后续阶段直接使用）
TEMPLATES = {
    "consult_default",
    "study_assistant",
    "dev_assistant",
    "profile_suggest",
    "roadmap_generate",
}

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


class TemplateError(Exception):
    pass


def load(name: str) -> str:
    """读取模板原文。不存在则抛错（不静默返回空 —— 空提示词会导致 AI 行为不可预期）。"""
    if not name:
        raise TemplateError("模板名不能为空")
    # 防目录穿越（模板名来自配置，配置可能被改）
    if "/" in name or "\\" in name or ".." in name:
        raise TemplateError(f"非法模板名：{name}")

    path = os.path.join(PROMPT_DIR, f"{name}.md")
    if not os.path.isfile(path):
        raise TemplateError(
            f"模板不存在：{name}（可用：{', '.join(sorted(TEMPLATES))}）"
        )
    with open(path, encoding="utf-8") as f:
        return f.read()


def render(name: str, variables: dict[str, Any] | None = None) -> str:
    """加载并渲染模板。未提供的变量原样保留。"""
    text = load(name)
    variables = variables or {}

    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        if key in variables:
            return str(variables[key])
        return m.group(0)  # 原样保留，暴露"漏传变量"

    return _VAR_RE.sub(repl, text)


def unresolved(text: str) -> list[str]:
    """返回文本里**仍未替换**的变量名（供测试与自检使用）。"""
    return sorted({m.group(1) for m in _VAR_RE.finditer(text)})


def list_templates() -> list[dict[str, str]]:
    """列出模板及其中未填充的变量（UI 的模板选择器可用）。"""
    out = []
    for name in sorted(TEMPLATES):
        try:
            text = load(name)
        except TemplateError:
            continue
        out.append({"name": name, "variables": ",".join(unresolved(text))})
    return out


__all__ = ["load", "render", "unresolved", "list_templates", "TemplateError", "TEMPLATES"]
