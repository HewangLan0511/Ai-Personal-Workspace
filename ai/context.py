#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""上下文注入器 + 双模式隔离（08 §5 / §6，**红线 V2 的实现处**）
================================================================

两个模式的区别是本项目的隐私红线，必须由**代码结构**保证，而不是靠提示词：

  - **咨询模式（consult）**：`assemble()` 在**第一行就返回空上下文**，
    永不接触任何用户数据。这是结构性的"够不着"，不是"不去拿"。
  - **工作助手模式（workspace）**：按用户开关装配模式/项目/学习/档案信息。

## 为什么不用"提示词里叫它别看"

提示词是**软约束** —— 只要数据进了请求体，模型就有渠道说出来，
而且可能被越狱。红线 V2 要求的是**数据根本不进请求**。故：

    咨询模式 → 不传任何 user_* 字段 → 模型物理上无从得知

这一点有对抗性测试锁死（见 tools/verify_stage5.py 的隔离用例）。

## 权限边界显式化（08 §5）

UI 顶部要常驻"🔓 已授权：…"提示。`permission_scope()` 产出该文案的数据，
它和真正装配的上下文**同源**（同一个函数算出来的），避免"提示说开了但实际没开"
或反之。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 模式常量（契约 3.1：ai_conversations.mode = consult | workspace）
MODE_CONSULT = "consult"
MODE_WORKSPACE = "workspace"

# 上下文来源开关（08 §6：提供开关让用户控制哪些上下文参与）
SCOPES = ("mode", "apps", "project", "learning", "profile")

# 各来源的授权说明（UI 可读）
SCOPE_LABEL = {
    "mode": "当前工作模式",
    "apps": "已打开软件",
    "project": "项目目录",
    "learning": "学习状态",
    "profile": "个人档案",
}


@dataclass
class ContextSource:
    """上游（core）提供的原始上下文素材。

    `None` 表示该项不可得（如未进入模式）。核心原则：**只有 workspace 模式会读它**。
    """

    mode_name: str | None = None
    mode_apps: list[str] = field(default_factory=list)
    project_dir: str | None = None
    learning_goal: str | None = None
    profile_skills: list[str] = field(default_factory=list)


@dataclass
class AssembledContext:
    """装配结果：注入用的文本 + 声明实际用了哪些来源。"""

    system_prompt: str
    used_scopes: list[str]

    def is_empty(self) -> bool:
        return not self.system_prompt


def permission_scope(mode: str, enabled: dict[str, bool] | None = None) -> list[str]:
    """该模式下**实际可用**的授权范围（UI 提示用）。

    关键：consult 模式**恒为空** —— 与 assemble() 的判据同源，
    保证 UI 提示与实际行为不会不一致。
    """
    if mode != MODE_WORKSPACE:
        return []
    enabled = enabled or {}
    return [s for s in SCOPES if enabled.get(s, True)]


def assemble(
    mode: str,
    source: ContextSource | None,
    *,
    enabled: dict[str, bool] | None = None,
    system_prompt_text: str = "",
) -> AssembledContext:
    """装配系统提示词。

    **第一行是红线 V2 的实现**：consult 直接返回空，不触碰 source。
    """
    if mode != MODE_WORKSPACE:
        # ← 这里就是红线 V2。不要把 source 里的任何字段拼进来。
        #    consult 模式只有 system prompt 文本（AI 人格设定），无任何用户数据。
        return AssembledContext(
            system_prompt=system_prompt_text or _CONSULT_FALLBACK,
            used_scopes=[],
        )

    if source is None:
        return AssembledContext(system_prompt=system_prompt_text, used_scopes=[])

    enabled = enabled or {}
    lines: list[str] = []
    used: list[str] = []

    if enabled.get("mode", True) and source.mode_name:
        lines.append(f"当前工作模式：{source.mode_name}")
        used.append("mode")

    if enabled.get("apps", True) and source.mode_apps:
        lines.append(f"已打开软件：{', '.join(source.mode_apps)}")
        used.append("apps")

    if enabled.get("project", True) and source.project_dir:
        lines.append(f"项目目录：{source.project_dir}")
        used.append("project")

    if enabled.get("learning", True) and source.learning_goal:
        lines.append(f"最近学习目标：{source.learning_goal}")
        used.append("learning")

    if enabled.get("profile", True) and source.profile_skills:
        lines.append(f"技能背景：{', '.join(source.profile_skills)}")
        used.append("profile")

    if not lines:
        return AssembledContext(system_prompt=system_prompt_text, used_scopes=[])

    body = "\n".join(f"       {line}" for line in lines)
    prompt = (
        "[系统] 当前工作环境：\n"
        f"{body}\n"
        "[提示] 你应以工作助手身份回答，必要时可建议如何利用当前环境。"
    )
    if system_prompt_text:
        prompt = system_prompt_text + "\n\n" + prompt

    return AssembledContext(system_prompt=prompt, used_scopes=used)


_CONSULT_FALLBACK = (
    "你是一个通用 AI 助手。你没有任何用户数据的访问权限，"
    "无法得知用户的项目、文件、学习进度或个人信息。"
    "若用户问及此类信息，请如实说明你无法访问。"
)


def context_tags(used: list[str], source: ContextSource | None) -> list[str]:
    """工作助手模式的"当前上下文"标签（08 §5：显示 `#开发模式` `#项目:my-app`）。"""
    tags: list[str] = []
    if source is None:
        return tags
    if "mode" in used and source.mode_name:
        tags.append(f"#{source.mode_name}")
    if "project" in used and source.project_dir:
        import os

        tags.append(f"#项目:{os.path.basename(source.project_dir.rstrip('/\\'))}")
    return tags


__all__ = [
    "MODE_CONSULT",
    "MODE_WORKSPACE",
    "SCOPES",
    "SCOPE_LABEL",
    "ContextSource",
    "AssembledContext",
    "assemble",
    "permission_scope",
    "context_tags",
]
