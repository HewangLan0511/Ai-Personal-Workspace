#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Provider 注册中心（08 §1）

**设计判据**：新增一个 Provider 应当**只改本文件**（加一行登记），
不改任何业务代码 —— 这是"Provider 抽象是否成功"的验收标准
（与插件系统"新增插件零核心代码改动"同源）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import AIProvider, ProviderConfig
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider
from .user_agent import UserAgentProvider
from .web_ai import WebAIProvider


@dataclass
class ProviderMeta:
    """Provider 的注册信息（UI 的供应商列表就是它）。"""

    id: str
    label: str
    impl: Any
    # 默认连接参数（UI 预填，用户可改）
    default_base: str = ""
    default_model: str = ""
    # 是否需要 API Key（本地模型不需要 —— UI 据此隐藏 key 输入框）
    needs_key: bool = True
    # 是否已实现（占位 Provider 为 False，UI 置灰）
    enabled: bool = True
    # 说明文案（UI 上给用户看的）
    note: str = ""
    # 该 Provider 支持的能力（用于 UI 显示与后续工具调用扩展）
    capabilities: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 注册表 —— 新增 Provider 只改这里

PROVIDERS: dict[str, ProviderMeta] = {
    # --- 云端（OpenAI 兼容协议，覆盖一大片） ---
    "openai": ProviderMeta(
        id="openai",
        label="OpenAI",
        impl=OpenAICompatProvider(),
        default_base="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        needs_key=True,
        capabilities=["chat", "stream", "models"],
        note="OpenAI 官方接口",
    ),
    "deepseek": ProviderMeta(
        id="deepseek",
        label="DeepSeek",
        impl=OpenAICompatProvider(),  # 复用兼容实现（08 §1 表：DeepSeek = OpenAI 兼容）
        default_base="https://api.deepseek.com/v1",
        default_model="deepseek-chat",
        needs_key=True,
        capabilities=["chat", "stream", "models"],
        note="DeepSeek 官方接口，OpenAI 兼容",
    ),
    "compatible": ProviderMeta(
        id="compatible",
        label="OpenAI 兼容（自定义）",
        impl=OpenAICompatProvider(),
        default_base="",
        default_model="",
        needs_key=True,
        capabilities=["chat", "stream", "models"],
        note="任何遵循 /v1/chat/completions 的服务：通义、Kimi、智谱、自建网关等",
    ),
    # --- 本地（无需 key，不产生费用） ---
    "ollama": ProviderMeta(
        id="ollama",
        label="Ollama（本地）",
        impl=OllamaProvider(),
        default_base="http://localhost:11434",
        default_model="",
        needs_key=False,
        capabilities=["chat", "stream", "models"],
        note="本地模型，无需 API Key、不产生费用",
    ),
    "lmstudio": ProviderMeta(
        id="lmstudio",
        label="LM Studio（本地）",
        impl=OpenAICompatProvider(),  # LM Studio 提供 OpenAI 兼容层
        default_base="http://localhost:1234/v1",
        default_model="",
        needs_key=False,
        capabilities=["chat", "stream", "models"],
        note="LM Studio 本地服务（OpenAI 兼容层），无需 API Key",
    ),
    # --- 占位（未实现，UI 置灰） ---
    "web-ai": ProviderMeta(
        id="web-ai",
        label="网页 AI（内嵌浏览器）",
        impl=WebAIProvider(),
        needs_key=False,
        enabled=False,
        capabilities=[],
        note="尚未开放：网页 AI 的响应不经过本应用管线，无法支持流式输出",
    ),
    "user-agent": ProviderMeta(
        id="user-agent",
        label="自定义 Agent 接入",
        impl=UserAgentProvider(),
        needs_key=False,
        enabled=False,
        capabilities=[],
        note="尚未开放：接入协议（握手/鉴权/流式分帧）待定稿",
    ),
}


def get(provider_id: str) -> ProviderMeta:
    """按 id 取 Provider。未知 id 抛错（不静默兜底 —— 静默兜底会掩盖配置错误）。"""
    meta = PROVIDERS.get(provider_id)
    if meta is None:
        raise KeyError(f"未知 Provider：{provider_id}（可用：{', '.join(PROVIDERS)}）")
    return meta


def available() -> list[dict[str, Any]]:
    """给 UI 的供应商列表（含 enabled 标记，前端据此置灰）。"""
    out = []
    for meta in PROVIDERS.values():
        out.append(
            {
                "id": meta.id,
                "label": meta.label,
                "defaultBase": meta.default_base,
                "defaultModel": meta.default_model,
                "needsKey": meta.needs_key,
                "enabled": meta.enabled,
                "note": meta.note,
                "capabilities": meta.capabilities,
            }
        )
    return out


__all__ = ["ProviderMeta", "PROVIDERS", "get", "available", "ProviderConfig"]
