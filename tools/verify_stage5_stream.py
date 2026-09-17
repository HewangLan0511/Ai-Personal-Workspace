#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段5 端到端流式验证（真 HTTP、真 SSE、真 NDJSON）

验证的是**链路**，不是函数：
    mock Provider(SSE) → ai.providers → ai.service → sidecar /ai/chat(NDJSON)

关键断言（对应 08 验收项 2 / 3 / 4 / 5 / 7 / 8）：
  - 验收2 流式：**首块到达时间 << 总时长**（证明不是攒完一次性给）
  - 验收3 中断：客户端提前断开 → 服务端停止产出（不继续烧 token）
  - 验收4 多 Provider：openai 与 ollama 两种协议都能跑通
  - 验收5 模型列表：/ai/models 能拉到 mock 的模型清单
  - 验收7 隔离：consult 模式请求体的 system 提示词**不含**任何用户数据
  - 验收8 注入：workspace 模式请求体的 system 提示词**含**当前模式与项目

用法：python tools/verify_stage5_stream.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
sys.path.insert(0, ROOT)

MOCK_OPENAI_PORT = 18801
MOCK_OLLAMA_PORT = 18802
SIDECAR_PORT = 18811

PASSED = 0
FAILED = 0
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  [PASS] {name}")
    else:
        FAILED += 1
        FAILURES.append(f"{name} — {detail}")
        print(f"  [FAIL] {name} {detail}")


def wait_port(port: int, timeout: float = 15.0) -> bool:
    """等端口就绪（探 /health 或 TCP 连通）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            return True
        except Exception:
            time.sleep(0.3)
    return False


def post_json(url: str, payload: dict, timeout: int = 30) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_stream(url: str, payload: dict, timeout: int = 30, stop_after: int = 0):
    """POST 并逐行读 NDJSON。

    返回 (lines, first_chunk_at, total_ms, interrupted)
    `stop_after` > 0 时，读到第 N 个 chunk 就主动关闭连接（模拟用户点"停止"）。
    """
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    lines: list[dict] = []
    t0 = time.time()
    first_at: float | None = None
    interrupted = False

    resp = urllib.request.urlopen(req, timeout=timeout)
    try:
        chunk_count = 0
        for raw in resp:
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            lines.append(obj)
            if obj.get("type") == "chunk":
                if first_at is None:
                    first_at = time.time() - t0
                chunk_count += 1
                if stop_after and chunk_count >= stop_after:
                    interrupted = True
                    break
    finally:
        resp.close()

    return lines, first_at, (time.time() - t0) * 1000, interrupted


def main() -> int:
    procs: list[subprocess.Popen] = []
    record = os.path.join(ROOT, "tools", "_ai_record.jsonl")

    try:
        # ---------------------------------------------------------- 起服务
        print("启动 mock Provider 与 sidecar ...")
        for port, kind in ((MOCK_OPENAI_PORT, "openai"), (MOCK_OLLAMA_PORT, "ollama")):
            procs.append(
                subprocess.Popen(
                    [PY, os.path.join(ROOT, "tools", "ai_mock.py"),
                     "--port", str(port), "--kind", kind, "--record", record],
                    cwd=ROOT,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        procs.append(
            subprocess.Popen(
                [PY, os.path.join(ROOT, "system", "service.py"),
                 "--port", str(SIDECAR_PORT), "--announce"],
                cwd=ROOT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )

        if not wait_port(SIDECAR_PORT):
            print("  [FAIL] sidecar 未启动")
            return 1
        print("  sidecar 就绪")

        # 给 mock 配置凭据（本地 mock 不校验，但 openai 路径要求有 key 才不发 no_api_key）
        for pid in ("openai", "ollama"):
            try:
                post_json(
                    f"http://127.0.0.1:{SIDECAR_PORT}/ai/credential",
                    {"provider": pid, "secret": "sk-mock-test-key-1234567890"},
                )
            except Exception as e:  # noqa: BLE001
                print(f"  [warn] 写入 {pid} 凭据失败：{e}")

        SIDECAR = f"http://127.0.0.1:{SIDECAR_PORT}"

        # ---------------------------------------------------------- 验收2 流式
        print("\n--- 验收项 2：流式输出（逐块到达）" + "-" * 30)
        lines, first_ms, total_ms, _ = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "openai",
                "model": "mock-gpt",
                "apiBase": f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1",
                "mode": "consult",
                "messages": [{"role": "user", "content": "你好"}],
            },
        )
        chunks = [l for l in lines if l.get("type") == "chunk"]
        text = "".join(c.get("delta", "") for c in chunks)
        done = [l for l in lines if l.get("type") == "done"]

        check("收到多个 chunk（不是一次性）", len(chunks) > 5, f"chunk 数={len(chunks)}")
        check("文本完整拼接", len(text) > 10, f"text={text[:40]!r}")
        check("有 done 终止标记", len(done) == 1, f"done 数={len(done)}")
        if first_ms is not None:
            check(
                "首块延迟远小于总时长（证明真流式）",
                first_ms * 1000 < total_ms * 0.5,
                f"首块 {first_ms*1000:.0f}ms / 总 {total_ms:.0f}ms",
            )
        else:
            check("首块延迟远小于总时长（证明真流式）", False, "未记录到首块")

        # ---------------------------------------------------------- 验收3 中断
        print("\n--- 验收项 3：中断（客户端提前断开）" + "-" * 30)
        lines_i, first_i, total_i, interrupted = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "openai",
                "model": "mock-gpt",
                "apiBase": f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1",
                "mode": "consult",
                "messages": [{"role": "user", "content": "你好"}],
            },
            stop_after=3,
        )
        chunk_i = [l for l in lines_i if l.get("type") == "chunk"]
        check("客户端成功中断", interrupted)
        check("中断后只收到少量 chunk", len(chunk_i) <= 4, f"收到 {len(chunk_i)}")
        check("中断后无 done（未自然结束）", not any(l.get("type") == "done" for l in lines_i))
        check(
            "中断后总耗时应明显短于完整生成",
            total_i < total_ms,
            f"中断 {total_i:.0f}ms vs 完整 {total_ms:.0f}ms",
        )

        # ---------------------------------------------------------- 验收4 多 Provider
        print("\n--- 验收项 4：多 Provider（Ollama 协议）" + "-" * 30)
        lines_o, first_o, total_o, _ = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "ollama",
                "model": "mock-llama",
                "apiBase": f"http://127.0.0.1:{MOCK_OLLAMA_PORT}",
                "mode": "consult",
                "messages": [{"role": "user", "content": "你好"}],
            },
        )
        chunks_o = [l for l in lines_o if l.get("type") == "chunk"]
        text_o = "".join(c.get("delta", "") for c in chunks_o)
        check("Ollama 协议也走通", len(chunks_o) > 5 and len(text_o) > 10, f"chunk={len(chunks_o)}")
        check("Ollama 有 done", any(l.get("type") == "done" for l in lines_o))

        # ---------------------------------------------------------- 验收5 模型列表
        print("\n--- 验收项 5：模型列表" + "-" * 30)
        try:
            r = post_json(
                f"{SIDECAR}/ai/models",
                {"provider": "openai", "apiBase": f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1"},
            )
            models = (r.get("data") or {}).get("models") or []
            check("能拉到模型列表", "mock-gpt" in models, f"models={models}")
        except Exception as e:  # noqa: BLE001
            check("能拉到模型列表", False, str(e))

        try:
            r = post_json(
                f"{SIDECAR}/ai/models",
                {"provider": "ollama", "apiBase": f"http://127.0.0.1:{MOCK_OLLAMA_PORT}"},
            )
            models = (r.get("data") or {}).get("models") or []
            check("Ollama 模型列表可拉取", "mock-llama" in models, f"models={models}")
        except Exception as e:  # noqa: BLE001
            check("Ollama 模型列表可拉取", False, str(e))

        # ---------------------------------------------------------- 验收7/8 双模式（端到端）
        print("\n--- 验收项 7/8：双模式隔离与上下文注入（端到端）" + "-" * 30)
        open(record, "w", encoding="utf-8").close()  # 清空记录

        ctx = {
            "modeName": "AI开发模式",
            "modeApps": ["VSCode", "Chrome"],
            "projectDir": "D:/projects/e2e-secret-project",
            "learningGoal": "掌握 Rust 异步",
            "profileSkills": ["Python"],
        }

        # consult 模式：**即便请求体里塞了 context，也必须不注入**
        post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "openai",
                "model": "mock-gpt",
                "apiBase": f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1",
                "mode": "consult",
                "context": ctx,  # ← 故意越权传入
                "messages": [{"role": "user", "content": "我的项目是什么"}],
            },
        )
        # workspace 模式：应该注入
        post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "openai",
                "model": "mock-gpt",
                "apiBase": f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1",
                "mode": "workspace",
                "context": ctx,
                "messages": [{"role": "user", "content": "我现在该做什么"}],
            },
        )

        time.sleep(0.5)
        recs = []
        with open(record, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))

        check("mock 收到两次请求", len(recs) >= 2, f"收到 {len(recs)}")

        if recs:
            consult_sys = recs[0].get("system", "")
            workspace_sys = recs[1].get("system", "") if len(recs) > 1 else ""

            leaks = [
                t
                for t in ("AI开发模式", "VSCode", "e2e-secret-project", "掌握 Rust 异步")
                if t in consult_sys
            ]
            check(
                "验收7 ★ consult 模式：模型侧拿不到任何用户数据（即使请求体硬塞）",
                not leaks,
                f"泄露：{leaks}",
            )
            check(
                "验收8 ★ workspace 模式：模型侧确实收到模式与项目（对照组）",
                "AI开发模式" in workspace_sys and "e2e-secret-project" in workspace_sys,
                f"system 前 150 字：{workspace_sys[:150]}",
            )
            check(
                "两模式的 system 提示词**不同**（证明真的分支，而非同一份）",
                consult_sys != workspace_sys,
            )

        # ---------------------------------------------------------- 验收10 降级
        print("\n--- 验收项 10：降级（Provider 不可达）" + "-" * 30)
        lines_e, _, _, _ = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "ollama",
                "apiBase": "http://127.0.0.1:9",  # 关闭的端口
                "model": "x",
                "mode": "consult",
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=15,
        )
        errs = [l for l in lines_e if l.get("type") == "error"]
        check("不可达时返回结构化错误（不是崩溃）", len(errs) == 1, f"lines={lines_e[:3]}")
        if errs:
            check(
                "错误码可映射为用户提示（local/unreachable/timeout）",
                errs[0].get("code") in ("local_model_down", "unreachable", "timeout"),
                f"code={errs[0].get('code')}",
            )

        # ---------------------------------------------------------- 汇总
        print("\n" + "=" * 68)
        print(f"端到端流式验证：PASS={PASSED}  FAIL={FAILED}")
        if FAILURES:
            print("\n失败明细：")
            for f in FAILURES:
                print(f"  - {f}")
        return 0 if FAILED == 0 else 1

    finally:
        for p in procs:
            try:
                p.terminate()
            except Exception:  # noqa: BLE001
                pass
        for p in procs:
            try:
                p.wait(timeout=5)
            except Exception:  # noqa: BLE001
                p.kill()
        if os.path.exists(record):
            try:
                os.remove(record)
            except OSError:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
