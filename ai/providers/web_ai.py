#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网页 AI Provider（08 §1 表：内嵌 WebView）

**当前状态：接口占位，未实现**（依据 08 §1 的 provider 优先级裁决）。

## 为什么留占位而不是硬做

08 指令要求此 Provider「内嵌 WebView，优点：无需 API 费用」。
但它与前四个 Provider 有**本质区别**：

  - 前四个：我们主动发 HTTP 请求，拿结构化响应 → 可流式、可中断、可计数
  - 网页 AI：我们**打开别人家的网页给用户自己用** → 我们拿不到
    结构化的 token 流，也无法程序化中断

也就是说，它**无法满足 08 §3「必须支持流式」**的字面要求（流式是对方
网页自己实现的，不经过我们的管线）。硬要做只能：注入脚本 hook 对方 DOM
—— 这既脆弱（对方改版即失效）又涉及绕过服务条款的风险。

## 决策

按项目优先级铁律「宁可少一个功能，不可破坏架构」：
本 Provider **登记接口、明确标记未实现**，由 UI 诚实提示用户
"网页 AI 模式尚未开放，请使用 API 或本地模型"。

**这不是谎报**（红线 V6）：本文件不声称任何能力，`chat()` 直接抛
`ERR_NOT_IMPLEMENTED`；`registry.available()` 会把它标为 `enabled=False`，
UI 据此置灰。TESTS 中有断言锁死"它必须抛错，不得静默返回空"。

后续若要做，见 `ai/providers/README.md` 的"网页 AI 实现路径（备选方案）"。
"""

from __future__ import annotations

from typing import Iterator

from .base import Chunk, Message, ProviderConfig, ProviderError

ERR_NOT_IMPLEMENTED = "not_implemented"


class WebAIProvider:
    """内嵌 WebView 的网页 AI —— 接口占位。"""

    name = "web-ai"
    enabled = False  # registry 据此置灰，UI 显示"尚未开放"

    def chat(
        self,
        messages: list[Message],
        *,
        config: ProviderConfig,
        stream: bool = True,
    ) -> Iterator[Chunk]:
        raise ProviderError(
            ERR_NOT_IMPLEMENTED,
            "网页 AI 模式尚未实现：它无法满足「流式输出」要求（响应由对方网页产生，"
            "不经过本应用的管线）。请改用 API Provider 或本地模型（Ollama / LM Studio）。",
        )

    def list_models(self, *, config: ProviderConfig) -> list[str]:
        return []

    def health(self, *, config: ProviderConfig) -> bool:
        return False


__all__ = ["WebAIProvider", "ERR_NOT_IMPLEMENTED"]
