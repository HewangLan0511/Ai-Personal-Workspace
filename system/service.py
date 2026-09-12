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
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

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
NOT_YET = {
    "/sys/media/current": "阶段8 实现（SMTC 媒体会话）",
    "/sys/perf/metrics": "阶段8 实现（性能计数）",
    "/ai/chat": "阶段5 实现（AI Provider 抽象层）",
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

    # ---- GET ------------------------------------------------------------

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/health":
            self._send(200, ok({"service": "pw-sidecar", "version": VERSION}))
            return
        if path in NOT_YET:
            self._send(501, err("not_implemented", NOT_YET[path]))
            return
        self._send(404, err("not_found", f"未知路径：{path}"))

    # ---- POST -----------------------------------------------------------

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        if path in MOVED_TO_CORE:
            self._send(410, err("moved_to_core", MOVED_TO_CORE[path]))
            return
        if path in NOT_YET:
            self._send(501, err("not_implemented", NOT_YET[path]))
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
