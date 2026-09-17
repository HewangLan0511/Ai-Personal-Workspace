#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAI 兼容 Provider（08 §1 表：覆盖 OpenAI / DeepSeek / 通义 / Kimi 等）

**这是覆盖率最高的一实现** —— 凡遵循 `POST /v1/chat/completions` 的服务，
填对 `api_base` + `model` 即可用，无需新增代码。

DeepSeek / LM Studio 均是它的**特例**（见 registry.py 的预设 base_url），
单独登记只是为了 UI 上给用户一个开箱即用的选项，实现上不做重复。
"""

from __future__ import annotations

import http.client
import json
import socket
import urllib.parse
from typing import Any, Iterator

from .base import (
    ERR_LOCAL_DOWN,
    ERR_NO_KEY,
    ERR_TIMEOUT,
    ERR_UNREACHABLE,
    AIProvider,
    Chunk,
    Message,
    ProviderConfig,
    ProviderError,
    extract_error,
    parse_openai_chunk,
)


def _split_base(api_base: str) -> tuple[str, str, bool]:
    """把 api_base 拆成 (host, path_prefix, is_https)。

    path_prefix 会带上 `/v1`（若用户只写了域名）—— 大多数服务的
    chat 端点是 `<base>/v1/chat/completions`，但用户可能写
    `https://api.openai.com` 或 `https://api.openai.com/v1`，两种都要能工作。
    """
    parsed = urllib.parse.urlparse(api_base)
    if not parsed.hostname:
        raise ProviderError(ERR_UNREACHABLE, f"无效的 api_base：{api_base}")

    scheme = (parsed.scheme or "https").lower()
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"

    prefix = parsed.path.rstrip("/")
    return host, prefix, scheme == "https"


def _post_stream(
    host: str,
    path: str,
    use_https: bool,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout: int,
) -> Iterator[bytes]:
    """发送请求并**逐行**产出响应体（流式）。

    用 `http.client` 直接读，而不是 `urllib.request`：后者不便于按块读取，
    而流式输出要求"服务器吐一点、我们转一点"。
    """
    conn_cls = http.client.HTTPSConnection if use_https else http.client.HTTPConnection
    conn = conn_cls(host, timeout=timeout)
    try:
        conn.request(
            "POST",
            path,
            body=json.dumps(body).encode("utf-8"),
            headers=headers,
        )
        resp = conn.getresponse()

        if resp.status >= 400:
            raw = resp.read()
            raise extract_error(resp.status, raw)

        # 逐行读：SSE 以 `\n` 分帧，`readline()` 足够且内存友好
        while True:
            line = resp.readline()
            if not line:
                break
            yield line
    except socket.timeout as e:
        raise ProviderError(ERR_TIMEOUT, f"请求超时（{timeout}s）", retryable=True) from e
    except (ConnectionRefusedError, socket.gaierror, OSError) as e:
        # 本地服务未启动 vs 网络不通，错误码不同（08 §7 要分别给提示）
        if isinstance(e, ConnectionRefusedError):
            raise ProviderError(ERR_LOCAL_DOWN, f"无法连接到 {host}，服务可能未启动") from e
        raise ProviderError(ERR_UNREACHABLE, f"网络不可达：{e}") from e
    finally:
        conn.close()


class OpenAICompatProvider:
    """OpenAI 兼容协议实现。"""

    name = "openai-compat"

    def chat(
        self,
        messages: list[Message],
        *,
        config: ProviderConfig,
        stream: bool = True,
    ) -> Iterator[Chunk]:
        if not config.api_base:
            raise ProviderError(ERR_UNREACHABLE, "未配置 api_base")

        host, prefix, use_https = _split_base(config.api_base)
        # 未带版本号时补 /v1（用户写域名是最常见的情况）
        if not prefix.endswith("/v1") and "/v1/" not in prefix:
            prefix += "/v1"
        path = f"{prefix}/chat/completions"

        headers = {"Content-Type": "application/json"}
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key}"
        # 部分本地服务（LM Studio）不校验 key，但要求有该头才不报错

        body: dict[str, Any] = {
            "model": config.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": True,   # 内部恒为流式，非流式在末尾合并（保证单一路径）
        }
        body.update(config.extra or {})

        if not stream:
            # 非流式 = 收完再一次性吐出。仍走同一解析代码，避免两套实现漂移。
            parts: list[str] = []
            tokens: int | None = None
            for line in _post_stream(host, path, use_https, body, headers, config.timeout):
                for payload in _data_payloads(line):
                    chunk = parse_openai_chunk(payload)
                    if chunk is None:
                        continue
                    parts.append(chunk.delta)
                    if chunk.tokens:
                        tokens = chunk.tokens
            yield Chunk(delta="".join(parts), done=True, tokens=tokens)
            return

        for line in _post_stream(host, path, use_https, body, headers, config.timeout):
            for payload in _data_payloads(line):
                chunk = parse_openai_chunk(payload)
                if chunk is None:
                    continue
                yield chunk

    def list_models(self, *, config: ProviderConfig) -> list[str]:
        """`GET /v1/models`。失败返回空列表 —— 拉起可选，不该让设置页报错。"""
        if not config.api_base:
            return []
        try:
            host, prefix, use_https = _split_base(config.api_base)
            if not prefix.endswith("/v1") and "/v1/" not in prefix:
                prefix += "/v1"
            conn_cls = (
                http.client.HTTPSConnection if use_https else http.client.HTTPConnection
            )
            conn = conn_cls(host, timeout=min(config.timeout, 10))
            try:
                headers = {}
                if config.api_key:
                    headers["Authorization"] = f"Bearer {config.api_key}"
                conn.request("GET", f"{prefix}/models", headers=headers)
                resp = conn.getresponse()
                if resp.status >= 400:
                    return []
                obj = json.loads(resp.read().decode("utf-8"))
                return [m["id"] for m in obj.get("data", []) if m.get("id")]
            finally:
                conn.close()
        except Exception:
            return []

    def health(self, *, config: ProviderConfig) -> bool:
        """有 key 且 base 可达即视为可用（不真的发一次对话，避免计费）。"""
        if not config.api_base:
            return False
        if not config.api_key and "localhost" not in config.api_base and "127.0.0.1" not in config.api_base:
            return False
        return bool(self.list_models(config=config))


def _data_payloads(line: bytes) -> Iterator[str]:
    """从一行 SSE 字节里取 data 负载（一行一条）。"""
    text = line.decode("utf-8", errors="replace").strip()
    if not text or text.startswith(":"):
        return
    if text.startswith("data:"):
        payload = text[5:].strip()
        if payload:
            yield payload


__all__ = ["OpenAICompatProvider", "AIProvider"]
