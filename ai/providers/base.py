#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Provider 抽象层（阶段5 ★ 核心，08 §1）
=============================================

**铁律（08 §1）**：禁止任何业务代码直接发某个模型的 HTTP 请求。
一切模型调用都必须经过 `AIProvider` 接口，业务层只认接口不认供应商。

设计要点：
  - 仅标准库（与 sidecar 一致，零依赖）；HTTP 用 `http.client`，SSE 手工解析
  - `chat()` 返回**生成器**（逐块吐出），`stream=False` 时也走同一路径
    —— 这样调用方只有一条代码路径，不会出现"流式/非流式两套实现不一致"
  - Provider 只负责"跟模型说话"，不碰数据库、不碰用户数据（那是 core 的事）

新增一个 Provider 的步骤（见 ai/providers/README.md）：
  1. 写一个类实现 `AIProvider` 协议（`name` / `chat` / `list_models` / `health`）
  2. 在 `registry.py` 的 `PROVIDERS` 里登记
  3. 不要改任何业务代码 —— 这是"Provider 抽象是否成功"的判据
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# 数据契约（与契约 3.2 AI 相关结构对应）

@dataclass
class Message:
    """一条对话消息。role: system | user | assistant。"""

    role: str
    content: str


@dataclass
class Chunk:
    """流式片段。`delta` 是增量文本，`done=True` 表示该轮结束。"""

    delta: str = ""
    done: bool = False
    # 结束时的统计（仅最后一个 chunk 携带；拿不到就为 None）
    tokens: int | None = None
    finish_reason: str | None = None


@dataclass
class ProviderConfig:
    """单个 Provider 的运行时配置（**不含明文 key** —— 见 08 §2）。

    `api_key` 由调用方从凭据库取出后**临时传入**，不从数据库读、不落盘、不记日志。
    """

    api_base: str = ""
    api_key: str = ""          # 运行时注入，来源 = 系统凭据库
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 2048
    timeout: int = 60
    extra: dict[str, Any] = field(default_factory=dict)


class ProviderError(Exception):
    """Provider 调用失败。`code` 供上层映射为用户可读提示（08 §7 失败与降级）。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


# 失败码（08 §7 的降级表用这些码分流）
ERR_NO_KEY = "no_api_key"           # 未配置 key → 引导去设置
ERR_UNREACHABLE = "unreachable"     # 网络不可达 → 提示切本地模型
ERR_LOCAL_DOWN = "local_model_down"  # 本地模型未启动 → 问是否启动
ERR_TIMEOUT = "timeout"             # 超时 → 可重试
ERR_RATE_LIMIT = "rate_limit"       # 429 → 退避重试
ERR_AUTH = "auth_failed"            # 401/403 → key 无效
ERR_BAD_RESPONSE = "bad_response"   # 返回体不符合预期


# ---------------------------------------------------------------------------
# 接口

@runtime_checkable
class AIProvider(Protocol):
    """所有 Provider 的统一接口（08 §1）。

    注意这里是**同步生成器**而非 `async def`：sidecar 本身是
    `ThreadingHTTPServer`（每请求一线程），用同步生成器即可逐块吐给客户端，
    且避免在 stdlib-only 环境里引入 asyncio 事件循环的复杂度。
    真正需要异步的场景（阶段8 并发多请求）由线程池承担。
    """

    name: str

    def chat(
        self,
        messages: list[Message],
        *,
        config: ProviderConfig,
        stream: bool = True,
    ) -> Iterator[Chunk]:
        """发送对话请求，逐块产出 Chunk。

        - `stream=True`：真的流式（边收边吐）
        - `stream=False`：内部仍走同一实现，只是把整段作为**一个** chunk 吐出
          —— 保证两种情况行为一致，不出现两套解析逻辑
        """
        ...

    def list_models(self, *, config: ProviderConfig) -> list[str]:
        """列出可用模型（拉不到则返回空列表，**不抛异常**）。"""
        ...

    def health(self, *, config: ProviderConfig) -> bool:
        """探活。不抛异常，不可用返回 False。"""
        ...


# ---------------------------------------------------------------------------
# 公共工具（各 Provider 复用，避免重复实现）

def merge_extra(config: ProviderConfig, defaults: dict[str, Any]) -> dict[str, Any]:
    """把调用方 extra 合并到默认参数上（extra 优先）。"""
    merged = dict(defaults)
    merged.update(config.extra or {})
    return merged


def sse_lines(raw: bytes) -> Iterator[str]:
    """把 SSE 原始字节拆成 `data:` 后的负载字符串（跳过心跳与注释）。

    各家 OpenAI 兼容实现的 SSE 格式一致：`data: {json}\\n\\n`，结尾 `data: [DONE]`。
    这里不做 JSON 解析，只负责"拆出 data 负载"，解析交给各 Provider。
    """
    text = raw.decode("utf-8", errors="replace")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                yield payload


def parse_openai_chunk(payload: str) -> Chunk | None:
    """解析一条 OpenAI 兼容的流式 chunk。返回 None 表示该条不含内容（如 role 声明）。"""
    if payload == "[DONE]":
        return Chunk(done=True)
    try:
        obj = json.loads(payload)
    except json.JSONDecodeError:
        return None

    choices = obj.get("choices") or []
    if not choices:
        return None
    choice = choices[0]
    delta = choice.get("delta") or {}
    content = delta.get("content") or ""
    finish = choice.get("finish_reason")

    usage = obj.get("usage") or {}
    tokens = usage.get("total_tokens")

    if not content and not finish:
        return None
    return Chunk(delta=content, done=bool(finish), tokens=tokens, finish_reason=finish)


def extract_error(status: int, body: bytes) -> ProviderError:
    """把 HTTP 错误映射成带降级语义的 ProviderError（08 §7）。"""
    text = body.decode("utf-8", errors="replace")[:500]
    # 尽量取出供应商返回的 message，取不到就用原始体
    msg = text
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            err = obj.get("error")
            if isinstance(err, dict) and err.get("message"):
                msg = str(err["message"])
            elif isinstance(err, str):
                msg = err
    except Exception:
        pass

    if status in (401, 403):
        return ProviderError(ERR_AUTH, f"凭据被拒绝（{status}）：{msg}")
    if status == 429:
        return ProviderError(ERR_RATE_LIMIT, f"请求过于频繁（429）：{msg}", retryable=True)
    if status >= 500:
        return ProviderError(ERR_UNREACHABLE, f"服务端错误（{status}）：{msg}", retryable=True)
    return ProviderError(ERR_BAD_RESPONSE, f"请求失败（{status}）：{msg}")
