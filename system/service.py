#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Personal Workspace · Python sidecar 服务
==========================================

职责（ADR-001 定稿后）：
  - 媒体会话 / 性能计数 / AI Provider 调用（阶段5/8 实现）
  - 窗口与进程控制**不在此实现**（归 Rust core，见 docs/adr/ADR-001）

设计约束：
  - 仅标准库（零依赖，sidecar 不应因为 pip 环境损坏而失效）
  - 随机端口：默认绑定 127.0.0.1:0，实际端口以首行 JSON announce 到 stdout
  - 契约：docs/agent-dev/03-数据契约与接口规范.md §3.4
  - ADR-001 迁移的 /sys/process/*、/sys/window/* 路径返回 410（moved_to_core）

用法：
  python system/service.py [--announce] [--port N]
  --announce  在 stdout 首行打印 {"event":"sidecar_ready","port":N}（core 解析用）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# 让 `win.apps_probe` 可导入（脚本所在目录 = system/）。打包成单文件后同样成立。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from win import apps_probe
except Exception:  # pragma: no cover - 非 Windows / 模块缺失时降级为"能力不可用"
    apps_probe = None  # type: ignore[assignment]

# 阶段5：AI 层在仓库根目录的 `ai/` 下（不在 system/）。
# sidecar 以 `system/service.py` 启动时，`ai/` 是它的上一级目录，需显式加入 path。
# 打包成单文件（PyInstaller）后同样成立 —— 届时 ai/ 会被一起打进包。
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
try:
    from ai import service as ai_service
except Exception as _ai_import_err:  # pragma: no cover
    ai_service = None  # type: ignore[assignment]
    _AI_IMPORT_ERROR = str(_ai_import_err)
else:
    _AI_IMPORT_ERROR = ""

# 阶段8：生活中心（天气/音乐 SMTC/社交概览）。系统/网络能力，02 §2.4 归 Python。
try:
    import life as life_mod
except Exception:  # pragma: no cover
    life_mod = None  # type: ignore[assignment]

# 阶段9：插件 zip 解包（仅解包到临时目录；注册/授权在 Rust core，trust boundary 不变）。
try:
    import plugin_import
except Exception:  # pragma: no cover
    plugin_import = None  # type: ignore[assignment]

VERSION = "0.1.0"

# ---------------------------------------------------------------------------
# 错误码约定：与 core 一致 { ok, data?, error? { code, message } }


def ok(data: Any = None) -> bytes:
    body = {"ok": True}
    if data is not None:
        body["data"] = data
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


def err(code: str, message: str) -> bytes:
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False
    ).encode("utf-8")


# ADR-001：窗口/进程能力已迁往 Rust core，保留路径返回 410。
MOVED_TO_CORE = {
    "/sys/process/launch": "ADR-001：进程启动已迁移至 Rust core（core/src/app_manager）",
    "/sys/process/status": "ADR-001：进程状态检测已迁移至 Rust core",
    "/sys/window/find": "ADR-001：窗口查找已迁移至 Rust core（core/src/window_manager）",
    "/sys/window/set": "ADR-001：窗口定位已迁移至 Rust core",
}

# 阶段路线：这些端点在后续阶段实现，当前 501。
# 注：`/ai/chat` 已于阶段5 实现，从这里移除（见 do_POST 的流式分支）。
NOT_YET = {
    "/sys/media/current": "阶段8 实现（SMTC 媒体会话）",
    "/sys/perf/metrics": "阶段8 实现（性能计数）",
}


class Handler(BaseHTTPRequestHandler):
    server_version = f"pw-sidecar/{VERSION}"

    # ---- 基础设施 -------------------------------------------------------

    def _send(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        # 侧车日志走 stderr（stdout 留给 announce 协议），静默常见访问噪音。
        sys.stderr.write("[sidecar] " + (fmt % args) + "\n")

    def _read_json(self) -> dict[str, Any]:
        """读 POST body 为 JSON（容错：空 body / 非 JSON → 空 dict）。"""
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    # ---- 流式（阶段5：AI 逐块输出）-------------------------------------

    def _begin_stream(self) -> None:
        """声明进入流式响应。

        用 **NDJSON**（每行一个 JSON 对象）而不是 SSE：
          - 客户端是 core（Rust，用 reqwest/裸 socket 读行都简单），不是浏览器，
            不需要 SSE 的 `data:` 帧语义；
          - NDJSON 每行独立可解析，断流时已收到的行仍然有效（SSE 需要自己拼帧）。
        每行形如：
          {"type":"chunk","delta":"..."}  增量
          {"type":"done","tokens":N}      结束
          {"type":"error","code":"...","message":"..."}  失败
        """
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        # 不用 chunked：逐行 write + flush 已足够，且 core 端读取更简单
        self.end_headers()

    def _stream_line(self, obj: dict[str, Any]) -> bool:
        """写一行流式 JSON。返回 False 表示客户端已断开（应停止产出）。"""
        try:
            self.wfile.write(
                (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
            )
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError, OSError):
            # 用户点了"停止"或关掉了窗口 —— 不是错误，正常终止
            return False

    def _handle_ai_chat(self) -> None:
        """`/ai/chat`：一次 AI 请求（流式）。08 §3 的事件序列由此产出。"""
        if ai_service is None:
            self._send(
                503,
                err(
                    "unavailable",
                    f"AI 模块不可用：{_AI_IMPORT_ERROR or 'ai.service 未加载'}",
                ),
            )
            return

        body = self._read_json()
        try:
            req = ai_service.ChatRequest(
                provider=body.get("provider") or "",
                model=body.get("model") or "",
                messages=list(body.get("messages") or []),
                mode=body.get("mode") or ai_service.MODE_CONSULT,
                context=body.get("context"),
                enabled_scopes=dict(body.get("enabledScopes") or {}),
                prompt_key=body.get("promptKey") or "",
                temperature=float(body.get("temperature", 0.7)),
                max_tokens=int(body.get("maxTokens", 2048)),
                stream=True,
                api_base_override=body.get("apiBase") or "",
            )
        except (TypeError, ValueError) as exc:
            self._send(400, err("bad_request", f"请求体不合法：{exc}"))
            return

        if not req.provider:
            self._send(400, err("bad_request", "缺少 provider"))
            return

        self._begin_stream()
        self._stream_line({"type": "start", "provider": req.provider})
        try:
            any_chunk = False
            for chunk in ai_service.stream(req):
                if chunk.delta:
                    any_chunk = True
                    if not self._stream_line({"type": "chunk", "delta": chunk.delta}):
                        return  # 客户端断开
                if chunk.done:
                    self._stream_line(
                        {
                            "type": "done",
                            "tokens": chunk.tokens,
                            "finishReason": chunk.finish_reason,
                        }
                    )
                    return
            if not any_chunk:
                # Provider 正常结束但一个字都没产出 —— 如实报告，不假装成功
                self._stream_line(
                    {"type": "error", "code": "empty_response", "message": "模型未返回任何内容"}
                )
                return
            self._stream_line({"type": "done"})
        except Exception as exc:  # noqa: BLE001
            # 失败不中断连接：已输出的内容保持有效，错误作为最后一行发出
            code = getattr(exc, "code", "ai_failed")
            self._stream_line({"type": "error", "code": code, "message": str(exc)})

    def _handle_ai_json(self, path: str) -> bool:
        """`/ai/*` 中返回普通 JSON 的端点。返回是否已处理。"""
        if ai_service is None:
            return False

        if path == "/ai/providers":
            self._send(200, ok(ai_service.info()))
            return True

        if path == "/ai/credential":
            body = self._read_json()
            provider = body.get("provider") or ""
            secret = body.get("secret") or ""
            if not provider:
                self._send(400, err("bad_request", "需要 provider"))
                return True
            # 空 secret = 删除该凭据（显式语义，避免"传空字符串想清除却报错"）
            if not secret:
                try:
                    removed = ai_service.delete_credential(provider)
                    self._send(200, ok({"provider": provider, "removed": removed}))
                except Exception as exc:  # noqa: BLE001
                    self._send(500, err("credential_failed", str(exc)))
                return True
            try:
                self._send(200, ok(ai_service.set_credential(provider, secret)))
            except Exception as exc:  # noqa: BLE001
                self._send(400, err("credential_failed", str(exc)))
            return True

        if path == "/ai/models":
            body = self._read_json()
            provider = body.get("provider") or ""
            from ai.credentials import ref_for, store  # noqa: PLC0415
            from ai.providers import registry as ai_registry  # noqa: PLC0415
            from ai.providers.base import ProviderConfig  # noqa: PLC0415

            try:
                meta = ai_registry.get(provider)
            except KeyError as exc:
                self._send(400, err("bad_request", str(exc)))
                return True

            cred = store().get(ref_for(provider))
            cfg = ProviderConfig(
                api_base=body.get("apiBase") or meta.default_base,
                api_key=cred.password if cred else "",
                model=body.get("model") or meta.default_model,
            )
            try:
                self._send(200, ok({"models": meta.impl.list_models(config=cfg)}))
            except Exception as exc:  # noqa: BLE001
                self._send(500, err("list_models_failed", str(exc)))
            return True

        if path == "/ai/scopes":
            body = self._read_json()
            mode = body.get("mode") or ai_service.MODE_CONSULT
            self._send(
                200,
                ok(
                    {
                        "mode": mode,
                        "scopes": ai_service.scopes_for(
                            mode, dict(body.get("enabledScopes") or {})
                        ),
                    }
                ),
            )
            return True

        return False

    # ---- GET ------------------------------------------------------------

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/health":
            self._send(200, ok({"service": "pw-sidecar", "version": VERSION}))
            return
        if path == "/life/media":
            # A2：SMTC 媒体会话（winsdk 可选；不可用时 available=false 降级）
            try:
                self._send(200, ok(life_mod.media_now() if life_mod else {"available": False, "reason": "life 模块未加载"}))
            except Exception as exc:  # noqa: BLE001
                self._send(500, err("media_failed", str(exc)))
            return
        if path in NOT_YET:
            self._send(501, err("not_implemented", NOT_YET[path]))
            return
        self._send(404, err("not_found", f"未知路径：{path}"))

    # ---- POST -----------------------------------------------------------

    def do_POST(self) -> None:
        path = self.path.split("?")[0]

        # ---- 阶段2：软件管理（05 §1 / §技术要点）----
        # 归属说明：注册表与文件属性读取属"系统 API"（02 §2.4 归 Python），
        # 而进程启动/窗口控制归 Rust（ADR-001）—— 故这两项在 sidecar，不在 core。
        if path == "/apps/scan":
            if apps_probe is None:
                self._send(503, err("unavailable", "扫描模块不可用（win.apps_probe 未加载）"))
                return
            try:
                items = apps_probe.scan_installed()
                self._send(200, ok({"items": items, "count": len(items)}))
            except Exception as exc:  # noqa: BLE001
                self._send(500, err("scan_failed", str(exc)))
            return

        if path == "/apps/probe":
            if apps_probe is None:
                self._send(503, err("unavailable", "探测模块不可用（win.apps_probe 未加载）"))
                return
            body = self._read_json()
            target = body.get("path") or ""
            out_dir = body.get("out_dir") or ""
            if not target or not out_dir:
                self._send(400, err("bad_request", "需要 path 与 out_dir"))
                return
            try:
                self._send(200, ok(apps_probe.probe(target, out_dir)))
            except Exception as exc:  # noqa: BLE001
                self._send(500, err("probe_failed", str(exc)))
            return

        if path in MOVED_TO_CORE:
            self._send(410, err("moved_to_core", MOVED_TO_CORE[path]))
            return
        if path in NOT_YET:
            self._send(501, err("not_implemented", NOT_YET[path]))
            return

        # ---- 阶段5：AI（08）----
        # /ai/chat 必须最先处理：它是流式端点，响应头一旦发出就不能再回 JSON 错误。
        if path == "/ai/chat":
            self._handle_ai_chat()
            return
        if path.startswith("/ai/") and self._handle_ai_json(path):
            return

        # ---- 阶段8：生活中心（11 §A）----
        if path in ("/life/weather", "/life/media"):
            # 天气为 POST；媒体为 POST（core 的 sidecar::call 统一走 POST，
            # GET /life/media 仅作为人类可读别名保留）
            if life_mod is None:
                self._send(503, err("unavailable", "life 模块未加载"))
                return
            body = self._read_json()
            try:
                if path == "/life/weather":
                    self._send(200, ok(life_mod.weather(body.get("city") or "", body.get("apiBase") or "")))
                else:
                    self._send(200, ok(life_mod.media_now()))
            except Exception as exc:  # noqa: BLE001
                code = "weather_failed" if path == "/life/weather" else "media_failed"
                self._send(502, err(code, str(exc)))
            return

        if path == "/life/media/control":
            if life_mod is None:
                self._send(503, err("unavailable", "life 模块未加载"))
                return
            body = self._read_json()
            try:
                self._send(200, ok(life_mod.media_control(body.get("action") or "")))
            except Exception as exc:  # noqa: BLE001
                self._send(400, err("media_control_failed", str(exc)))
            return

        if path == "/life/social/overview":
            if life_mod is None:
                self._send(503, err("unavailable", "life 模块未加载"))
                return
            body = self._read_json()
            services = body.get("services") or []
            try:
                injected = life_mod.inject_passwords(services)
                self._send(200, ok(life_mod.social_overview(injected)))
            except Exception as exc:  # noqa: BLE001
                self._send(500, err("social_failed", str(exc)))
            return

        if path == "/life/social/credential":
            # 密码只进系统凭据库（keyring），不进 config 表 / 数据库（红线 V1）
            if life_mod is None:
                self._send(503, err("unavailable", "life 模块未加载"))
                return
            body = self._read_json()
            name = str(body.get("name") or "").strip()
            password = str(body.get("password") or "")
            if not name or not password:
                self._send(400, err("bad_request", "需要 name 与 password"))
                return
            try:
                life_mod.set_social_password(name, password)
                self._send(200, ok({"saved": True, "name": name}))
            except Exception as exc:  # noqa: BLE001
                self._send(500, err("credential_failed", str(exc)))
            return

        # ---- 阶段9：插件导入（仅安全解包；注册与授权在 core plugins::install）----
        if path == "/plugin/import":
            if plugin_import is None:
                self._send(503, err("unavailable", "plugin_import 模块未加载"))
                return
            body = self._read_json()
            try:
                result = plugin_import.import_zip(
                    str(body.get("zipPath") or ""), str(body.get("dataDir") or "")
                )
                self._send(200, ok(result))
            except plugin_import.ImportError as exc:
                self._send(400, err("plugin_import_failed", str(exc)))
            except Exception as exc:  # noqa: BLE001
                self._send(500, err("plugin_import_failed", str(exc)))
            return

        if path == "/internal/db/query" or path == "/internal/db/exec":
            # sidecar 自身不直连数据库（单一写入者原则）——数据操作走 core。
            self._send(
                410,
                err(
                    "single_writer",
                    "sidecar 不直连 SQLite；数据读写请走 core 的 /internal/db/* 接口",
                ),
            )
            return
        self._send(404, err("not_found", f"未知路径：{path}"))


# ---------------------------------------------------------------------------
# 入口


def main() -> int:
    parser = argparse.ArgumentParser(description="Personal Workspace sidecar")
    parser.add_argument("--port", type=int, default=0, help="监听端口（0 = 随机）")
    parser.add_argument(
        "--announce",
        action="store_true",
        help="stdout 首行打印端口 announce JSON（供 core 解析）",
    )
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    server.daemon_threads = True
    actual_port = server.server_address[1]

    if args.announce:
        sys.stdout.write(
            json.dumps({"event": "sidecar_ready", "port": actual_port}) + "\n"
        )
        sys.stdout.flush()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
