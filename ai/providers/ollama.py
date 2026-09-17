#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ollama Provider（08 §1 表：本地模型，无需 key）

**为什么不能复用 OpenAICompat**：Ollama 的原生 `/api/chat` 与 OpenAI 的
`/v1/chat/completions` 有两处实质差异：
  1. **流式格式不同** —— Ollama 每行是**裸 JSON**（不是 `data: {...}` SSE 帧）；
  2. **结束标记不同** —— 以 `{"done": true}` 结尾，没有 `[DONE]` 哨兵；
  3. 参数名不同 —— `options.num_predict` 而非 `max_tokens`。

它的 `/v1/chat/completions`（OpenAI 兼容层）**确实存在**，但对本地模型
走原生端点是官方推荐路径、且能拿到 `done_reason` 等更多信息。
故此处独立实现，同时保留 fallback 到兼容层的可能（见 `use_compat_layer`）。
"""

from __future__ import annotations

import http.client
import json
import socket
from typing import Any, Iterator

from .base import (
    ERR_LOCAL_DOWN,
    ERR_TIMEOUT,
    ERR_UNREACHABLE,
    Chunk,
    Message,
    ProviderConfig,
    ProviderError,
    extract_error,
)


class OllamaProvider:
    """Ollama 原生协议实现（`/api/chat`）。"""

    name = "ollama"

    def chat(
        self,
        messages: list[Message],
        *,
        config: ProviderConfig,
        stream: bool = True,
    ) -> Iterator[Chunk]:
        base = config.api_base or "http://localhost:11434"
        host, use_https = _host_of(base)
        model = config.model or "llama3"

        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "options": {
                "temperature": config.temperature,
                "num_predict": config.max_tokens,
            },
        }
        # 用户 extra 可覆盖 options 里的项（如 top_p、seed）
        for k, v in (config.extra or {}).items():
            if k == "options" and isinstance(v, dict):
                body["options"].update(v)
            else:
                body[k] = v

        parts: list[str] = []
        tokens: int | None = None

        for obj in _iter_json_lines(
            host, use_https, "/api/chat", body, config.timeout
        ):
            content = (obj.get("message") or {}).get("content") or ""
            done = bool(obj.get("done"))
            if obj.get("done") and obj.get("eval_count"):
                # Ollama 报的是 token 数；不折算成"总 token"以免误导
                tokens = int(obj["eval_count"])
            if not content and not done:
                continue
            chunk = Chunk(
                delta=content,
                done=done,
                tokens=tokens,
                finish_reason=obj.get("done_reason"),
            )
            if stream:
                yield chunk
            else:
                parts.append(content)

        if not stream:
            yield Chunk(delta="".join(parts), done=True, tokens=tokens)

    def list_models(self, *, config: ProviderConfig) -> list[str]:
        """`GET /api/tags`。失败返回空列表。"""
        base = config.api_base or "http://localhost:11434"
        try:
            host, use_https = _host_of(base)
            conn_cls = (
                http.client.HTTPSConnection if use_https else http.client.HTTPConnection
            )
            conn = conn_cls(host, timeout=min(config.timeout, 10))
            try:
                conn.request("GET", "/api/tags")
                resp = conn.getresponse()
                if resp.status >= 400:
                    return []
                obj = json.loads(resp.read().decode("utf-8"))
                return [m["name"] for m in obj.get("models", []) if m.get("name")]
            finally:
                conn.close()
        except Exception:
            return []

    def health(self, *, config: ProviderConfig) -> bool:
        base = config.api_base or "http://localhost:11434"
        try:
            host, use_https = _host_of(base)
            conn_cls = (
                http.client.HTTPSConnection if use_https else http.client.HTTPConnection
            )
            conn = conn_cls(host, timeout=3)
            try:
                conn.request("GET", "/api/tags")
                resp = conn.getresponse()
                resp.read()
                return resp.status < 400
            finally:
                conn.close()
        except Exception:
            return False


def _host_of(api_base: str) -> tuple[str, bool]:
    """把 base 拆成 (host[:port], use_https)。"""
    import urllib.parse

    parsed = urllib.parse.urlparse(api_base)
    if not parsed.hostname:
        raise ProviderError(ERR_UNREACHABLE, f"无效的 api_base：{api_base}")
    host = parsed.hostname
    if parsed.port:
        host = f"{host}:{parsed.port}"
    else:
        # 没写端口时按协议补默认端口（Ollama 默认 11434，但 base 可能省端口）
        default = 11434 if parsed.hostname in ("localhost", "127.0.0.1") else None
        if default:
            host = f"{host}:{default}"
    return host, (parsed.scheme or "http").lower() == "https"


def _iter_json_lines(
    host: str,
    use_https: bool,
    path: str,
    body: dict[str, Any],
    timeout: int,
) -> Iterator[dict[str, Any]]:
    """逐行读裸 JSON（Ollama 流式格式）。"""
    conn_cls = http.client.HTTPSConnection if use_https else http.client.HTTPConnection
    conn = conn_cls(host, timeout=timeout)
    try:
        conn.request(
            "POST",
            path,
            body=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        if resp.status >= 400:
            raise extract_error(resp.status, resp.read())

        while True:
            line = resp.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            try:
                yield json.loads(text)
            except json.JSONDecodeError:
                continue
    except socket.timeout as e:
        raise ProviderError(ERR_TIMEOUT, f"请求超时（{timeout}s）", retryable=True) from e
    except ConnectionRefusedError as e:
        raise ProviderError(
            ERR_LOCAL_DOWN, f"Ollama 未运行（{host}）—— 是否启动？"
        ) from e
    except OSError as e:
        raise ProviderError(ERR_UNREACHABLE, f"网络不可达：{e}") from e
    finally:
        conn.close()


__all__ = ["OllamaProvider"]
