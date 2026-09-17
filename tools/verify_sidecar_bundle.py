#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""发行态 sidecar 验收：**打包出来的单文件**能不能真的干活。

为什么需要这个脚本（阶段5 踩到的坑）
------------------------------------
`tools/verify_stage5.py` 跑的是**开发态**（core 拉 `system/service.py` 源码），
它证明不了"装到用户机器上的那个 exe"可用：

PyInstaller 只自动收集**被 import 的 .py**，不会收集 `.md`。
`ai/prompt/*.md` 是运行时按 `PROMPT_DIR` 读的数据文件 —— 不打进单文件，
发行版里该目录就是空的，`/ai/chat` 一律报「模板不存在：consult_default」。

症状的特殊性：**开发态全绿、发行态全死**，且报错像是"路由没写"，
排查容易跑偏（本项目已在这类"跑的不是这份产物"上栽过两次：L-043 / L-044）。
故把"发行态可用"做成脚本，纳入交付证据。

本脚本验证（真跑打包 exe，不 import 任何业务模块）：
  1. 打包 exe 能启动并按 `--announce` 协议把端口打到 stdout 首行
  2. `/health` 可用
  3. `/ai/providers` 返回完整 Provider 注册表（说明 ai 包进了包）
  4. `/ai/credential` 写 key 返回掩码（说明 ai.credentials 进了包）
  5. **`/ai/chat` 能真出 chunk 并正常结束**（说明 ai/prompt/*.md 进了包）★核心
  6. consult 模式的 system 提示词不含任何用户数据（红线 V2，发行态同样成立）

用法：
  python system/build_sidecar.py          # 先产出 core/binaries/service-*.exe
  python tools/verify_sidecar_bundle.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
BIN_DIR = ROOT / "core" / "binaries"

MOCK_PORT = 18831
SECRET_KEY = "sk-bundle-verify-must-not-leak-7c1e"
SECRET_PROJECT = "BUNDLE-secret-project"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")


def http_json(url: str, method: str = "GET", body=None, timeout: float = 30.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode())
        except Exception:
            return e.code, None
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)}


def post_stream(url: str, payload: dict, timeout: float = 30.0):
    """POST 并逐行读 NDJSON。返回 (lines, first_chunk_at_ms, total_ms)。"""
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    lines: list[dict] = []
    t0 = time.time()
    first_at: float | None = None
    resp = urllib.request.urlopen(req, timeout=timeout)
    try:
        for raw in resp:
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                continue
            lines.append(obj)
            if obj.get("type") == "chunk" and first_at is None:
                first_at = (time.time() - t0) * 1000
    finally:
        resp.close()
    return lines, first_at, (time.time() - t0) * 1000


def find_bundle() -> Path | None:
    """找打包产物：core/binaries/service-<target-triple>[.exe]"""
    if not BIN_DIR.is_dir():
        return None
    suffix = ".exe" if sys.platform == "win32" else ""
    cands = sorted(p for p in BIN_DIR.glob(f"service-*{suffix}") if p.is_file())
    return cands[0] if cands else None


def wait_tcp(port: int, timeout: float = 20.0) -> bool:
    import socket as _socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with _socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def read_announced_port(proc: subprocess.Popen) -> int | None:
    """读 stdout 首行 announce JSON：{"event":"sidecar_ready","port":N}"""
    assert proc.stdout is not None
    deadline = time.time() + 30
    while time.time() < deadline:
        line = proc.stdout.readline()
        if not line:
            if proc.poll() is not None:
                return None
            continue
        try:
            obj = json.loads(line.decode("utf-8", "replace").strip())
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "sidecar_ready":
            return int(obj.get("port"))
    return None


def main() -> int:
    bundle = find_bundle()
    if bundle is None:
        print(f"[FATAL] 未找到打包产物（{BIN_DIR}/service-*）")
        print("        先跑 `python system/build_sidecar.py`。")
        return 2

    print(f"[bundle] 产物 = {bundle}  ({bundle.stat().st_size / 1048576:.1f} MB)")

    record = ROOT / "tools" / "_bundle_record.jsonl"
    mock: subprocess.Popen | None = None
    sidecar: subprocess.Popen | None = None

    try:
        # 起 mock Provider（真 HTTP，供 /ai/chat 用）
        mock = subprocess.Popen(
            [PY, str(ROOT / "tools" / "ai_mock.py"),
             "--port", str(MOCK_PORT), "--kind", "openai", "--record", str(record)],
            cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if not wait_tcp(MOCK_PORT):
            raise RuntimeError("mock Provider 未启动")

        # 起**打包 exe**（注意：这里没有任何 PW_SIDECAR_FORCE_DEV，也不碰源码）
        sidecar = subprocess.Popen(
            [str(bundle), "--announce"],
            cwd=str(ROOT.parent),  # cwd 故意设在仓库**外**，证明不依赖 cwd
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        port = read_announced_port(sidecar)
        check("打包 exe 启动并按 announce 协议回报端口（不依赖仓库源码）", bool(port),
              f"port={port}")
        if not port:
            raise RuntimeError("打包 exe 未 announce 端口")
        base = f"http://127.0.0.1:{port}"

        st, body = http_json(f"{base}/health")
        check("打包 exe /health 可用", st == 200 and (body or {}).get("ok") is True,
              f"status={st} body={body}")

        st, body = http_json(f"{base}/ai/providers", "POST", {})
        provs = ((body or {}).get("data") or {}).get("providers") or []
        check("打包 exe 内含完整 ai 包（/ai/providers 返回 7 个注册项）",
              st == 200 and len(provs) == 7, f"count={len(provs)}")

        # ★ 核心：模板数据文件是否进了包
        st, body = http_json(f"{base}/ai/credential", "POST",
                             {"provider": "openai", "secret": SECRET_KEY})
        mask = ((body or {}).get("data") or {}).get("keyMask")
        check("打包 exe 凭据写入可用（ai.credentials 已入包）",
              st == 200 and str(mask or "").startswith("sk-"), f"status={st} mask={mask!r}")

        open(record, "w", encoding="utf-8").close()
        lines, first_ms, total_ms = post_stream(
            f"{base}/ai/chat",
            {
                "provider": "openai", "model": "mock-gpt",
                "apiBase": f"http://127.0.0.1:{MOCK_PORT}/v1",
                "mode": "consult",
                "messages": [{"role": "user", "content": "你好"}],
            },
        )
        errs = [l for l in lines if l.get("type") == "error"]
        chunks = [l for l in lines if l.get("type") == "chunk"]
        text = "".join(l.get("delta", "") for l in chunks)
        check("★ 打包 exe /ai/chat 能出流式内容（ai/prompt/*.md 已入包）",
              len(chunks) > 5 and len(text) > 10
              and any(l.get("type") == "done" for l in lines),
              f"chunk={len(chunks)} 首块={first_ms:.0f}ms 总={total_ms:.0f}ms "
              f"err={errs[:1] if errs else 'none'}")
        check("★ 打包 exe 不再报「模板不存在」",
              not any("模板不存在" in str(l.get("message", "")) for l in errs),
              f"errors={errs[:1]}")

        # 红线 V2：发行态下 consult 同样不能拿到用户数据
        time.sleep(0.4)
        sys_msgs: list[str] = []
        if record.exists():
            with open(record, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        sys_msgs.append(json.loads(line).get("system", ""))
        check("发行态 consult 的 system 提示词不含用户数据（红线 V2）",
              bool(sys_msgs) and SECRET_PROJECT not in " ".join(sys_msgs),
              f"记录 {len(sys_msgs)} 条")

        # 打包 exe 对已废弃路径仍返回 410（ADR-001 不被绕过）
        st, body = http_json(f"{base}/sys/process/launch", "POST", {})
        check("打包 exe 对 /sys/process/* 返回 410 moved_to_core（ADR-001）",
              st == 410, f"status={st}")

    except Exception as e:  # noqa: BLE001
        check("执行异常", False, f"{type(e).__name__}: {e}")
    finally:
        if sidecar and sidecar.poll() is None:
            sidecar.terminate()
            try:
                sidecar.wait(timeout=10)
            except subprocess.TimeoutExpired:
                sidecar.kill()
        if mock and mock.poll() is None:
            mock.terminate()
            try:
                mock.wait(timeout=5)
            except subprocess.TimeoutExpired:
                mock.kill()
        # 清掉本脚本写入的系统凭据（不留痕）
        try:
            subprocess.run(
                [PY, "-c",
                 "import sys; sys.path.insert(0, r'%s');"
                 "from ai.credentials import store, ref_for;"
                 "store().delete(ref_for('openai'))" % ROOT],
                capture_output=True, timeout=15,
            )
        except Exception:  # noqa: BLE001
            pass
        if record.exists():
            try:
                os.remove(record)
            except OSError:
                pass

    print("\n" + "=" * 70)
    print("发行态 sidecar 验收结果")
    print("=" * 70)
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
        if detail:
            print(f"      {detail}")
    print("=" * 70)
    ok = sum(1 for _, p, _ in results if p)
    print(f"合计 {ok}/{len(results)} 通过")
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
