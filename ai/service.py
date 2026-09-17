#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 服务：把 Provider / 凭据 / 上下文 / 提示词串起来（阶段5 编排层）
====================================================================

本模块是 sidecar `/ai/*` 端点的业务实现。它**不碰数据库**
（02 §2.4 单一写入者）：会话元数据的读写由 core 负责，
本模块只处理"一次 AI 请求"这件事。

数据流：
    core（装配上下文）→ sidecar /ai/chat（本模块）
        → 取凭据 → 选 Provider → 渲染提示词 → 流式产出 chunk
    chunk 由 core 转成 AI_STREAM_CHUNK 事件广播给前端
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, Iterator

# 让 `ai` 包内模块用绝对导入（`from ai.xxx import`）与相对导入都能工作。
# sidecar 会把仓库根加入 sys.path，此处保证直接 `python ai/service.py` 也能跑。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from ai.credentials import ref_for, store  # noqa: E402
from ai.context import (  # noqa: E402
    MODE_CONSULT,
    MODE_WORKSPACE,
    ContextSource,
    assemble,
    permission_scope,
)
from ai.prompt_renderer import list_templates, render  # noqa: E402
from ai.providers import registry  # noqa: E402
from ai.providers.base import (  # noqa: E402
    ERR_NO_KEY,
    Chunk,
    Message,
    ProviderConfig,
    ProviderError,
)


@dataclass
class ChatRequest:
    """一次对话请求（由 core 的 HTTP 调用传入）。"""

    provider: str
    model: str = ""
    messages: list[dict[str, str]] = field(default_factory=list)
    mode: str = MODE_CONSULT
    # 工作助手模式的上下文素材（**consult 模式必须为空** —— 双保险：
    # 即便调用方传了，assemble() 也会因 mode 不匹配而丢弃）
    context: dict[str, Any] | None = None
    # 用户开关：哪些上下文来源参与
    enabled_scopes: dict[str, bool] = field(default_factory=dict)
    # 提示词模板名（不传则按 mode 选默认）
    prompt_key: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    stream: bool = True
    api_base_override: str = ""   # 用户自定义（compatible provider 用）


def _resolve_prompt_key(req: ChatRequest) -> str:
    if req.prompt_key:
        return req.prompt_key
    return "consult_default" if req.mode == MODE_CONSULT else "dev_assistant"


def _build_source(raw: dict[str, Any] | None) -> ContextSource | None:
    if not raw:
        return None
    return ContextSource(
        mode_name=raw.get("modeName"),
        mode_apps=list(raw.get("modeApps") or []),
        project_dir=raw.get("projectDir"),
        learning_goal=raw.get("learningGoal"),
        profile_skills=list(raw.get("profileSkills") or []),
    )


def prepare(req: ChatRequest) -> tuple[Any, ProviderConfig, list[Message], list[str]]:
    """装配一次请求所需的全部素材。

    返回 (provider_impl, config, messages, used_scopes)。
    抽成独立函数是为了**可测试**：双模式隔离的断言直接查这里，
    不必真的发网络请求。
    """
    meta = registry.get(req.provider)
    if not meta.enabled:
        raise ProviderError(
            "not_implemented",
            f"Provider「{meta.label}」尚未开放。{meta.note}",
        )

    # --- 凭据（红线 V1：只从系统凭据库取，绝不从数据库取明文） ---
    api_key = ""
    if meta.needs_key:
        cred = store().get(ref_for(req.provider))
        if cred is None:
            raise ProviderError(
                ERR_NO_KEY,
                f"尚未配置 {meta.label} 的 API Key，请到「设置 → AI」中添加。",
            )
        api_key = cred.password

    config = ProviderConfig(
        api_base=req.api_base_override or meta.default_base,
        api_key=api_key,
        model=req.model or meta.default_model,
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )

    # --- 上下文 + 提示词（红线 V2 的关口） ---
    source = _build_source(req.context)
    assembled = assemble(
        req.mode,
        source,
        enabled=req.enabled_scopes,
    )
    prompt_text = render(
        _resolve_prompt_key(req),
        {"context": assembled.system_prompt or "（无可用上下文）"},
    )

    # consult 模式下，assemble 保证 used_scopes 为空；
    # 但提示词里也不该出现任何用户数据 —— 用 consult 专用模板而非工作助手模板。
    messages: list[Message] = [Message(role="system", content=prompt_text)]
    for m in req.messages:
        role = m.get("role", "user")
        if role == "system":
            continue  # 客户端不得覆盖系统提示词（防注入）
        messages.append(Message(role=role, content=m.get("content", "")))

    return meta.impl, config, messages, assembled.used_scopes


def stream(req: ChatRequest) -> Iterator[Chunk]:
    """执行一次对话，逐块产出。"""
    impl, config, messages, _ = prepare(req)
    yield from impl.chat(messages, config=config, stream=req.stream)


def info() -> dict[str, Any]:
    """给 UI 的 Provider 列表 + 凭据状态 + 模板列表。"""
    providers = registry.available()
    cs = store()
    for p in providers:
        if p["needsKey"]:
            ref = ref_for(p["id"])
            cred = cs.get(ref)
            p["hasKey"] = cred is not None
            p["keyMask"] = cs.mask(cred.password) if cred else ""
            p["credentialRef"] = ref
        else:
            p["hasKey"] = True   # 本地模型不需要 key
            p["keyMask"] = ""
            p["credentialRef"] = ""

    return {
        "providers": providers,
        "templates": list_templates(),
        "credentialBackend": cs.backend(),
        "credentialPersistent": cs.persistent(),
    }


def set_credential(provider_id: str, secret: str) -> dict[str, Any]:
    """写入凭据（红线 V1：只写系统凭据库，返回掩码而非明文）。"""
    meta = registry.get(provider_id)
    ref = ref_for(provider_id)
    cs = store()
    cs.set(ref, secret)
    return {
        "provider": provider_id,
        "credentialRef": ref,
        "keyMask": cs.mask(secret),
        "backend": cs.backend(),
        "label": meta.label,
    }


def delete_credential(provider_id: str) -> bool:
    return store().delete(ref_for(provider_id))


def scopes_for(mode: str, enabled: dict[str, bool] | None = None) -> list[str]:
    return permission_scope(mode, enabled)


__all__ = [
    "ChatRequest",
    "prepare",
    "stream",
    "info",
    "set_credential",
    "delete_credential",
    "scopes_for",
    "MODE_CONSULT",
    "MODE_WORKSPACE",
]
