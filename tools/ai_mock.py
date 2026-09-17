#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI mock 服务：模拟 OpenAI 兼容 / Ollama 的流式响应（阶段5 验收用）

**为什么必须有它**：08 验收项 1~5（对话/流式/中断/多 Provider/模型列表）
都需要一个真实可点、可复现的模型端。真调云端 API 需要用户的 key 且计入费用，
不适合放进自动化脚本。

本 mock 用真实 HTTP + 真实 SSE 分帧（不是打桩函数），因此能验证：
  - sidecar 的流式转发是否逐块到达（而不是攒完一次性给）
  - 首块延迟 vs 总时长（验收项 2 的判据）
  - 客户端中断是否真的让服务端停止产出（验收项 3）

用法：
    python tools/ai_mock.py --port 18801 --kind openai
    python tools/ai_mock.py --port 18802 --kind ollama
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# 每个块之间的间隔 —— 故意留出可观测的间隔，才能验证"逐字出现"
CHUNK_DELAY = 0.08
REPLY = "这是 mock 模型的回复，用于验证流式输出的逐块到达行为。"

# ---- 阶段6 用：可控的"答案内容"（验收项 1 生成路线 / 8 解析降级）----
#
# 为什么要在 mock 侧做这件事：验收项 1/8 要验证的是**链路**（提示词渲染 → 派发 →
# 流式回传 → JSON 解析 → 建议态返回），不是模型的规划水平。真调云端模型既不稳定
# （同一次生成节点数会变）也要花用户的钱，无法作为可复现判据。
# 因此由 mock 输出**固定夹具**，把"链路通不通"与"模型答得好不好"分开：
# 前者机器判定，后者属人工验收（见 verify_stage6.py 的说明）。
ROADMAP_JSON = json.dumps(
    {
        "goal": "学习计算机视觉并完成项目",
        "nodes": [
            {"title": "Python 基础", "order": 1, "estimated": "2周",
             "resources": ["官方教程", "基础练习题"]},
            {"title": "OpenCV", "order": 2, "estimated": "3周", "resources": ["图像处理基础"]},
            {"title": "CNN", "order": 3, "estimated": "3周"},
            {"title": "深度学习", "order": 4, "estimated": "4周"},
            {"title": "项目实践", "order": 5, "estimated": "3周"},
        ],
    },
    ensure_ascii=False,
)

# 包了 Markdown 围栏 + 前后废话：解析器要能"从噪声里捞出 JSON"（真实模型常这样答）
FENCED_REPLY = "好的，这是我为你规划的路线：\n```json\n" + ROADMAP_JSON + "\n```\n希望对你有所帮助。"

# 纯废话 + 半个 JSON：解析必须**降级**而不是抛错（验收项 8）
INVALID_REPLY = "抱歉，我不太确定你的目标，能不能再说清楚一点？{nodes: [这不是合法的 JSON，"

REPLIES = {
    "text": REPLY,
    "roadmap": ROADMAP_JSON,
    "fenced": FENCED_REPLY,
    "invalid": INVALID_REPLY,
}


class MockHandler(BaseHTTPRequestHandler):
    kind = "openai"

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("[ai-mock] " + (fmt % args) + "\n")

    def _json(self, status: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if self.kind == "openai":
            if path.endswith("/models"):
                self._json(200, {"data": [{"id": "mock-gpt"}, {"id": "mock-gpt-mini"}]})
                return
        else:
            if path == "/api/tags":
                self._json(200, {"models": [{"name": "mock-llama"}, {"name": "mock-qwen"}]})
                return
        self._json(404, {"error": {"message": f"未知路径 {path}"}})

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            body = {}

        # 记录收到的 system 提示词，供"双模式隔离"的端到端断言比对
        msgs = body.get("messages") or []
        sys_prompt = next((m.get("content", "") for m in msgs if m.get("role") == "system"), "")
        # 记录收到的 system 提示词，供"双模式隔离"的端到端断言比对。
        # ★ 未指定 --record 时**不写文件**：默认落点若写死成 cwd 下的某个名字，
        #   任何忘了传参的调用方都会在项目根目录里留一个垃圾文件
        #   （阶段6 实测：仓库根出现 18 KB 的 ai_mock_record.jsonl）。
        if self.server.record_file:  # type: ignore[attr-defined]
            with open(self.server.record_file, "a", encoding="utf-8") as f:  # type: ignore[attr-defined]
                f.write(json.dumps({"system": sys_prompt, "count": len(msgs)}) + "\n")

        if self.kind == "openai":
            if not path.endswith("/chat/completions"):
                self._json(404, {"error": {"message": "未知路径"}})
                return
            self._stream_openai()
        else:
            if path != "/api/chat":
                self._json(404, {"error": {"message": "未知路径"}})
                return
            self._stream_ollama()

    # ---- OpenAI 兼容 SSE ----
    def _stream_openai(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        try:
            for ch in self.server.reply_text:  # type: ignore[attr-defined]
                frame = {
                    "choices": [{"delta": {"content": ch}, "finish_reason": None}],
                }
                self.wfile.write(f"data: {json.dumps(frame, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
                time.sleep(self.server.chunk_delay)  # type: ignore[attr-defined]
            done = {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"total_tokens": 42}}
            self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            # 客户端中断 —— 正是验收项 3 要观察的行为
            print("[ai-mock] 客户端中断，停止产出", file=sys.stderr)

    # ---- Ollama 裸 JSON 行 ----
    def _stream_ollama(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        try:
            for ch in self.server.reply_text:  # type: ignore[attr-defined]
                line = {"message": {"role": "assistant", "content": ch}, "done": False}
                self.wfile.write((json.dumps(line, ensure_ascii=False) + "\n").encode())
                self.wfile.flush()
                time.sleep(self.server.chunk_delay)  # type: ignore[attr-defined]
            final = {"message": {"role": "assistant", "content": ""}, "done": True,
                     "done_reason": "stop", "eval_count": 37}
            self.wfile.write((json.dumps(final) + "\n").encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            print("[ai-mock] 客户端中断，停止产出", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18801)
    parser.add_argument("--kind", choices=["openai", "ollama"], default="openai")
    parser.add_argument("--record", default="", help="把收到的 system 提示词记到该文件")
    parser.add_argument(
        "--reply",
        choices=sorted(REPLIES),
        default="text",
        help="回答内容夹具：text=流式文本（阶段5 默认）；roadmap=合法路线 JSON；"
             "fenced=围栏包裹的 JSON（测容错）；invalid=非法 JSON（测降级）",
    )
    parser.add_argument(
        "--chunk-delay",
        type=float,
        default=CHUNK_DELAY,
        help="每块之间的间隔秒数。阶段5 的流式验收依赖它（默认 0.08）；"
             "阶段6 的相关性验证要的是**内容**而非节奏，可调小以缩短用例时间",
    )
    args = parser.parse_args()

    handler = type("H", (MockHandler,), {"kind": args.kind})
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    server.daemon_threads = True
    server.record_file = args.record  # 空 = 不记录（不留任何文件）
    server.reply_text = REPLIES[args.reply]  # type: ignore[attr-defined]
    server.chunk_delay = args.chunk_delay  # type: ignore[attr-defined]

    if args.record:
        open(args.record, "w", encoding="utf-8").close()  # 清空

    print(f"[ai-mock] {args.kind} 已启动 127.0.0.1:{args.port}（reply={args.reply}）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
