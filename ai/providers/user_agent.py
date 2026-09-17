#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户 Agent Provider（08 §1 表 / 3.2.5：HTTP / WebSocket 自定义接入）

**当前状态：接口占位，未实现**（依据 08 §1 的 provider 优先级裁决）。

## 为什么留占位

08 指令要求支持「用户自己写的 Agent 接进来」，接入方式 HTTP / WebSocket。
这需要先定一套**接入协议**（握手、鉴权、能力声明、流式分帧、错误码），
而协议一旦定错，外部 Agent 作者就得跟着改 —— 属于"定了就难改"的接口。

产品上它服务的是"高级用户自己接一个 Agent"，**当前阶段没有这样的用户**，
也没有可对齐的协议草案。按优先级铁律，先不做，避免拍脑袋定协议。

## 与网页 AI 占位的区别

- 网页 AI：**技术上**无法满足流式要求 ⇒ 短期也不该做
- 用户 Agent：**技术上可行**，缺的是协议设计与真实需求 ⇒ 等有需求再做

## 决策

`enabled=False`，`chat()` 抛 `ERR_NOT_IMPLEMENTED`。
UI 置灰并提示"自定义 Agent 接入尚未开放"。

若要做，`ai/providers/README.md` 已写好协议草案要点（见该文件末节）。
"""

from __future__ import annotations

from typing import Iterator

from .base import Chunk, Message, ProviderConfig, ProviderError


class UserAgentProvider:
    """用户自定义 Agent —— 接口占位（协议未定稿）。"""

    name = "user-agent"
    enabled = False

    def chat(
        self,
        messages: list[Message],
        *,
        config: ProviderConfig,
        stream: bool = True,
    ) -> Iterator[Chunk]:
        raise ProviderError(
            "not_implemented",
            "自定义 Agent 接入协议尚未定稿（需先确定握手/鉴权/流式分帧规范），"
            "当前版本未开放。请改用 API Provider 或本地模型。",
        )

    def list_models(self, *, config: ProviderConfig) -> list[str]:
        return []

    def health(self, *, config: ProviderConfig) -> bool:
        return False


__all__ = ["UserAgentProvider"]
