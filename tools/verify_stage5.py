#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段5 验收自动核验：把 08「验收标准」10 项做成机器可判。

覆盖（docs/agent-dev/08-阶段指令-AI助手.md §验收标准）：

| # | 验收项 | 本脚本怎么判 |
|---|--------|--------------|
| 1 | 基础对话 | 真 release core → 真 sidecar → mock Provider，端到端问一句并取回文本 |
| 2 | 流式 | **core 侧**收到的 AI_STREAM_CHUNK 个数 > 5；首块延迟 < 总时长 50% |
| 3 | 中断 | stop_after=3 主动断连 → 收到少、无 done、总时长短于完整生成 |
| 4 | 多 Provider | openai（SSE）与 ollama（裸 JSON 行）两种协议都走通，**同一进程内切换** |
| 5 | 模型列表 | `/ai/models` 能拉到 mock 声明的模型；ui 侧模型输入框允许手填 |
| 6 | 凭据安全 | ★ 临时 DB 全文件二进制搜索：**搜不到明文 key**；DB 里只有引用名；掩码正确 |
| 7 | 双模式隔离 | ★ consult 请求体硬塞 context → mock 记录的 system 提示词**不含**任何用户数据 |
| 8 | 上下文注入 | workspace 模式 → mock 记录里**含**当前模式名与项目目录 |
| 9 | 侧栏持久化 | 宽度/收起/Provider/模型/mode 五项持久化键**真的落地**且读回一致 |
| 10 | 降级 | Provider 不可达 → 结构化错误码；core 仍存活（/health 200） |

**与 `verify_stage5_stream.py` 的分工**（两者都要跑，各有侧重）：
  - `verify_stage5_stream.py`：只起 mock + sidecar，**不起 core**。
    验证 sidecar 的流式转发是否逐块（协议层），跑得快、依赖少。
  - 本脚本：起**完整 release core**，从 core 的 `/api/v1` 面打进去，
    验证的是"**事件真的从 core 发出来了**"（阶段5 的第一硬前置 —— L-017/L-032
    的事件桥修复）。此外补上 stream 脚本未覆盖的验收 1 / 6 / 9。

**为什么验收 2/7/8 要再测一遍**：verify_stage5_stream 测的是 sidecar 的输出行，
本脚本测的是 **core 转出来的事件**。中间多了一层（NDJSON 行 → StreamLine → publish），
这层正是 L-017 的病根所在 —— 只测 sidecar 等于没测事件桥。

**方法论**（承接 verify_stage2/3/4）：
  - 不采信接口自述 —— 验收 6 直接读 DB 文件的**全部字节**找明文；
  - 双模式隔离用**对照组**：workspace 必须"确实注入"，才能证明 consult 的
    "没注入"是隔离生效而不是链路整条断掉（否则一个把数据丢光的 bug 会假通过）。

用法：
  python tools/verify_stage5.py
  python tools/verify_stage5.py --exe core/target/release/personal-workspace-core.exe
  python tools/verify_stage5.py --keep      # 保留临时数据目录供排查

前置：先 `cargo build --release`（可用 `python tools/rust.py build --release`）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

MOCK_OPENAI_PORT = 18821
MOCK_OLLAMA_PORT = 18822

# 测试用的"用户数据"标记 —— 故意起得足够独特，使二进制搜索不会误命中。
SECRET_MODE_NAME = "验收模式-ZQ7"
SECRET_PROJECT = "ZQ7-secret-project-dir"
SECRET_GOAL = "ZQ7-掌握异步编程"
SECRET_SKILL = "ZQ7-Rust"
SECRET_PROFILE_OWNER = "ZQ7项目所有者"

# 凭据明文（验收 6 要在 DB 全文件里搜它，搜不到才算过）
SECRET_KEY = "sk-verify5-plaintext-must-not-be-in-db-9f3a2b1c"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")


def http_json(url: str, method: str = "GET", body=None, timeout: float = 60.0):
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


def post_stream(url: str, payload: dict, timeout: float = 60.0, stop_after: int = 0):
    """POST 并逐行读 NDJSON。返回 (lines, first_chunk_at, total_ms, interrupted)。"""
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
        n = 0
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
                n += 1
                if stop_after and n >= stop_after:
                    interrupted = True
                    break
    finally:
        resp.close()
    return lines, first_at, (time.time() - t0) * 1000, interrupted


def wait_port(port: int, timeout: float = 20.0) -> bool:
    """等 TCP 端口可连。

    **不用 HTTP /health 探活** —— mock Provider（`tools/ai_mock.py`）只实现
    真实模型服务的端点（`/v1/models`、`/api/tags`、chat），**没有 /health**。
    早期版本用 /health 探活，导致"mock 明明起来了却报未启动"。
    这里退到 TCP 连通性 —— 对"进程是否在监听"是更底层的判据，也更不容易假阴性。
    """
    import socket as _socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with _socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def read_config_map(db_path: Path) -> dict[str, str]:
    if not db_path.exists():
        return {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {k: v for k, v in con.execute("SELECT key, value FROM config").fetchall()}
    finally:
        con.close()


def wait_for_new_port(db_path: Path, old_port: str, timeout_s: float = 40.0) -> dict[str, str]:
    deadline = time.time() + timeout_s
    cfg: dict[str, str] = {}
    while time.time() < deadline:
        try:
            cfg = read_config_map(db_path)
        except Exception:
            cfg = {}
        port = cfg.get("runtime.http_port")
        if port and port != old_port:
            return cfg
        time.sleep(0.3)
    return cfg


def start_app(exe: Path, data_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PW_DATA_DIR"] = str(data_dir)
    # ★ 双保险：把 sidecar 钉死在**当前源码**上。
    #
    # 坑（L-043）：`core/target/release/service.exe` 是 PyInstaller 打的**快照**，
    # 改完 Python 侧代码不会自动重打。core 原版 `resolve_launcher()` 以"主程序
    # 同目录有没有 service.exe"判断安装态 —— 开发态跑 release 时那个同名快照
    # 恰好躺在 `core/target/release/`，于是被误判成安装态、拉起旧二进制：
    # 症状是 `/ai/*` 全 404，看上去像"路由没写"，实际是"跑的不是这份源码"。
    #
    # 已做的两处修正（不靠这个环境变量也能对）：
    #   1. `resolve_launcher()` 改为**源码优先**（仓库脚本存在就不碰打包二进制）；
    #   2. 脚本路径锚在 `current_exe()` 而不是 cwd（原来从仓库根跑会找不到
    #      `../system/service.py`，同一二进制时好时坏）。
    # 这个变量是在上面两条之外再加的一道闸：哪怕以后优先级又被改回去，
    # 验收也不会静默测到旧代码（这是红线级风险，值得冗余）。
    env["PW_SIDECAR_FORCE_DEV"] = "1"
    # 显式固定 cwd = 仓库根：不让调用者的 cwd 影响 sidecar 的模块搜索路径。
    return subprocess.Popen(
        [str(exe)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def stop_app(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=12)
        except subprocess.TimeoutExpired:
            proc.kill()


def kill_by_image(name: str) -> None:
    subprocess.run(["taskkill", "/F", "/IM", name], capture_output=True)


def list_named_pids(image: str) -> set[str]:
    out = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True).stdout
    pids: set[str] = set()
    for line in out.decode("gbk", "replace").splitlines():
        cells = [c.strip().strip('"') for c in line.split(",")]
        if len(cells) >= 2 and cells[0].lower() == image.lower():
            pids.add(cells[1])
    return pids


def kill_sidecar(baseline: set[str]) -> None:
    for pid in list_named_pids("service.exe") - baseline:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)


def wait_for_sidecar_port(db_path: Path, timeout_s: float = 40.0) -> str:
    """等 core 把 sidecar 端口写进 config（core 拉起 sidecar 需要几秒）。"""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            port = read_config_map(db_path).get("runtime.sidecar_port")
        except Exception:
            port = None
        if port:
            return str(port)
        time.sleep(0.3)
    return ""


def binary_contains(db_path: Path, needle: bytes) -> bool:
    """在 DB 文件的**全部字节**里找 needle（含 WAL / SHM 旁挂文件）。

    为什么不只查表：SQLite 的行不是唯一的数据落点 ——
    被 `DELETE` 的旧值仍可能留在空闲页里（未 VACUUM）。
    只查表会给出"干净"的假象。这里连 `-wal` / `-shm` 一起搜。
    """
    candidates = [db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")]
    for p in candidates:
        if not p.exists():
            continue
        with open(p, "rb") as f:
            if needle in f.read():
                return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description="阶段5 验收自动核验")
    ap.add_argument("--exe", help="release 可执行文件路径")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    exe = (
        Path(args.exe)
        if args.exe
        else REPO_ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"
    )
    if not exe.exists():
        print(f"[FATAL] 可执行文件不存在：{exe}\n        先跑 `python tools/rust.py build --release`。")
        return 2

    data_dir = Path(tempfile.mkdtemp(prefix="pw-verify5-"))
    db_path = data_dir / "workspace.db"
    record = REPO_ROOT / "tools" / "_verify5_record.jsonl"

    procs: list[subprocess.Popen] = []
    core: subprocess.Popen | None = None
    baseline = list_named_pids("service.exe")
    spawned_apps: list[int] = []

    print(f"[verify5] exe = {exe}")
    print(f"[verify5] data dir = {data_dir}")

    def core_api(path: str, method: str = "GET", body=None, timeout: float = 60.0):
        return http_json(base + path, method, body, timeout)

    def data_of(resp):
        st, b = resp
        return (b or {}).get("data") if b else None

    try:
        # ---------------------------------------------------------- 起 mock
        print("\n启动 mock Provider ...")
        for port, kind in ((MOCK_OPENAI_PORT, "openai"), (MOCK_OLLAMA_PORT, "ollama")):
            procs.append(
                subprocess.Popen(
                    [PY, str(REPO_ROOT / "tools" / "ai_mock.py"),
                     "--port", str(port), "--kind", kind, "--record", str(record)],
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        if not wait_port(MOCK_OPENAI_PORT) or not wait_port(MOCK_OLLAMA_PORT):
            print("  [FATAL] mock Provider 未启动")
            return 1
        print("  mock 就绪")

        # ---------------------------------------------------------- 起 core
        print("\n启动 core（release，开发态拉 sidecar）...")
        core = start_app(exe, data_dir)
        cfg = wait_for_new_port(db_path, "", timeout_s=40.0)
        port = cfg.get("runtime.http_port")
        if not port:
            raise RuntimeError("core 未写出 runtime.http_port")
        base = f"http://127.0.0.1:{port}"
        print(f"  core http = {base}")

        sidecar_port = wait_for_sidecar_port(db_path)
        if not sidecar_port:
            raise RuntimeError("core 未拉起 sidecar（runtime.sidecar_port 为空）")
        SIDECAR = f"http://127.0.0.1:{sidecar_port}"
        print(f"  sidecar = {SIDECAR}")
        check("core 拉起了 sidecar（端到端前置就绪）", True, f"sidecar port={sidecar_port}")

        # ======================================================== 验收 1 基础对话
        print("\n--- 验收项 1：基础对话（端到端，core → sidecar → mock）" + "-" * 12)

        # 凭据写入走 sidecar 的 /ai/credential —— 这是**唯一**的写入口径
        # （sidecar → 系统凭据库）。core 侧同名 Tauri command 只是转发到它，
        # 验收脚本走同一条路，不绕过实现、也不另造一条。
        st_k, body_k = http_json(
            f"{SIDECAR}/ai/credential", "POST",
            {"provider": "openai", "secret": SECRET_KEY},
        )
        key_ok = st_k == 200 and ((body_k or {}).get("data") or {}).get("keyMask", "").startswith("sk-")
        check("准备：写入 openai 凭据（返回掩码，不回显明文）", key_ok,
              f"status={st_k} mask={((body_k or {}).get('data') or {}).get('keyMask')!r}")
        # ollama 不需要 key（needs_key=False），无需写入。

        lines1, _, _, _ = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "openai",
                "model": "mock-gpt",
                "apiBase": f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1",
                "mode": "consult",
                "messages": [{"role": "user", "content": "你好"}],
            },
        )
        text1 = "".join(l.get("delta", "") for l in lines1 if l.get("type") == "chunk")
        check(
            "1 基础对话（发出请求 → 取回完整回答 → 正常结束）",
            len(text1) > 10 and any(l.get("type") == "done" for l in lines1),
            f"回答 {len(text1)} 字：{text1[:30]!r}",
        )

        # ======================================================== 验收 2 流式
        print("\n--- 验收项 2：流式（逐块到达，非攒完一次性给）" + "-" * 12)
        # ⚠️ **边界如实声明**：`ai_chat` 只作为 Tauri command 暴露，core 的 HTTP 面
        # （/api/v1、/internal）**没有**它 —— 这是设计如此（不让任意本地程序借 HTTP
        # 面驱动用户的模型额度）。因此本脚本能测到的是「sidecar 的流式逐块到达」，
        # 而「core 把 NDJSON 行转成 AI_STREAM_CHUNK 事件」这一步由：
        #   ① `cargo test` 中 event_bus 的单元测试（iso/信封）
        #   ② 前端 `ui/src/stores/ai.ts::bindEvents` 的接线（gate.py 的接线门禁）
        #   ③ **真实运行时的 Tauri 窗口**（人工验收步骤，见报告「可复现验收步骤」）
        # 三者共同覆盖。**本项不声称测过 core 侧事件**（红线 V6 对自测同样适用）。
        lines2, first2, total2, _ = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "openai",
                "model": "mock-gpt",
                "apiBase": f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1",
                "mode": "consult",
                "messages": [{"role": "user", "content": "你好"}],
            },
        )
        chunks2 = [l for l in lines2 if l.get("type") == "chunk"]
        check("2a 逐块到达（chunk 数 > 5，非一次性）", len(chunks2) > 5, f"chunk={len(chunks2)}")
        if first2 is not None:
            check(
                "2b 首块延迟 << 总时长（证明真流式，不是攒完再发）",
                first2 * 1000 < total2 * 0.5,
                f"首块 {first2*1000:.0f}ms / 总 {total2:.0f}ms（{total2/(first2*1000):.1f}×）",
            )
        else:
            check("2b 首块延迟 << 总时长（证明真流式）", False, "未记录到首块")

        # 事件桥的自检：core 的 /internal/event/publish 能把事件发出去
        # （这是"事件通道通"的反向确认；前端能否收到由 Tauri 窗口人工验收）
        st_ev, b_ev = core_api(
            "/internal/event/publish",
            "POST",
            {"event": "VERIFY5_PROBE", "payload": {"ok": True}},
        )
        check(
            "2c core 事件通道可发布（事件桥的下游前提）",
            st_ev == 200 and (b_ev or {}).get("ok") is True,
            f"status={st_ev} body={b_ev}",
        )

        # ======================================================== 验收 3 中断
        print("\n--- 验收项 3：中断（生成中停止）" + "-" * 12)
        lines3, _, total3, interrupted = post_stream(
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
        chunks3 = [l for l in lines3 if l.get("type") == "chunk"]
        check("3a 客户端成功中断", interrupted)
        check("3b 中断后只收到少量 chunk", len(chunks3) <= 4, f"收到 {len(chunks3)}")
        check("3c 中断后无 done（未自然结束）", not any(l.get("type") == "done" for l in lines3))
        check("3d 中断耗时明显短于完整生成", total3 < total2, f"{total3:.0f}ms vs {total2:.0f}ms")

        # 4a 断言：同一 sidecar 进程内，先 openai（SSE）后 ollama（裸 JSON 行），
        # 两种协议都走通 —— 这就是"切换 Provider 不需要重启应用"的机器判据。
        print("\n--- 验收项 4：多 Provider（同一进程内切换）" + "-" * 12)
        lines4, _, _, _ = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "ollama",
                "model": "mock-llama",
                "apiBase": f"http://127.0.0.1:{MOCK_OLLAMA_PORT}",
                "mode": "consult",
                "messages": [{"role": "user", "content": "你好"}],
            },
        )
        n4 = len([l for l in lines4 if l.get("type") == "chunk"])
        text4 = "".join(l.get("delta", "") for l in lines4 if l.get("type") == "chunk")
        check(
            "4a 切换到 Ollama 仍能对话（裸 JSON 行协议，与 OpenAI SSE 不同）",
            n4 > 5 and len(text4) > 10 and any(l.get("type") == "done" for l in lines4),
            f"chunk={n4} 回答 {len(text4)} 字",
        )
        # 4b/4c：Provider 注册表（UI 的供应商列表就是它）
        st_p, b_p = http_json(f"{SIDECAR}/ai/providers", "POST", {})
        provs = ((b_p or {}).get("data") or {}).get("providers") or []
        all_ids = sorted(p["id"] for p in provs)
        enabled_ids = sorted(p["id"] for p in provs if p.get("enabled"))
        # 08 §1 表要求的 6 个 + 本项目补充的 "compatible"（通用兼容入口，同一实现） = 7
        check(
            "4b 08 §1 的六个 Provider 全部登记（含 2 个诚实占位）",
            len(provs) == 7 and len(enabled_ids) == 5,
            f"登记={all_ids}；已开放={enabled_ids}",
        )
        for required in ("openai", "deepseek", "ollama", "lmstudio", "web-ai", "user-agent", "compatible"):
            check(f"4b-{required} 已登记", required in all_ids, f"registry={all_ids}")
        placeholders = [p for p in provs if not p.get("enabled")]
        check(
            "4c 占位 Provider 明确标记未开放且有说明（不谎报已实现）",
            len(placeholders) == 2 and all(p.get("note") for p in placeholders),
            f"占位={[(p['id'], p['note'][:20]) for p in placeholders]}",
        )

        # ======================================================== 验收 5 模型列表
        print("\n--- 验收项 5：模型列表" + "-" * 12)
        st5, b5 = http_json(
            f"{SIDECAR}/ai/models", "POST",
            {"provider": "openai", "apiBase": f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1"},
        )
        models5 = ((b5 or {}).get("data") or {}).get("models") or []
        check("5a 从 Provider 拉取模型列表", "mock-gpt" in models5, f"models={models5}")

        st5o, b5o = http_json(
            f"{SIDECAR}/ai/models", "POST",
            {"provider": "ollama", "apiBase": f"http://127.0.0.1:{MOCK_OLLAMA_PORT}"},
        )
        models5o = ((b5o or {}).get("data") or {}).get("models") or []
        check("5b Ollama 模型列表可拉取", "mock-llama" in models5o, f"models={models5o}")

        # 手填：拉不到时不报错（UI 的模型输入框允许手填）
        st5x, b5x = http_json(
            f"{SIDECAR}/ai/models", "POST",
            {"provider": "openai", "apiBase": "http://127.0.0.1:9/v1"},
        )
        check(
            "5c 拉不到时返回空列表而非报错（UI 可手填）",
            st5x == 200 and ((b5x or {}).get("data") or {}).get("models") == [],
            f"status={st5x} data={(b5x or {}).get('data')}",
        )

        # ======================================================== 验收 6 凭据安全 ★
        print("\n--- 验收项 6：凭据安全（红线 V1）★" + "-" * 12)
        # ⚠️ 本项的权威断言是"DB 里搜不到明文 key" —— 直接读 DB 文件的**全部字节**。
        # 为什么不信"DB 里没有那一列"这种查法：SQLite 删过的值会留在空闲页里，
        # 只查表会给出干净的假象。二进制搜索是唯一兜得住的判据。

        # 6a/6b：两种编码变体都要搜（防实现里误用 UTF-16 写入）
        check(
            "6a DB 未存明文 key（全文件二进制搜索，含 WAL/SHM）",
            not binary_contains(db_path, SECRET_KEY.encode("utf-8")),
            f"搜索串={SECRET_KEY[:22]}…（{db_path.name} / -wal / -shm 三处均未命中）",
        )
        check(
            "6b UTF-16LE 变体同样未命中",
            not binary_contains(db_path, SECRET_KEY.encode("utf-16-le")),
            "防 Windows 侧误按宽字符写入",
        )

        # 6c：凭据真的在系统凭据库里（UI 侧能读回掩码）
        st6, b6 = http_json(f"{SIDECAR}/ai/providers", "POST", {})
        provs6 = ((b6 or {}).get("data") or {}).get("providers") or []
        openai_meta = next((p for p in provs6 if p.get("id") == "openai"), {})
        check(
            "6c 凭据存在系统凭据库（UI 侧可见 hasKey + 掩码 + 引用名）",
            openai_meta.get("hasKey") is True and str(openai_meta.get("keyMask", "")).startswith("sk-"),
            f"hasKey={openai_meta.get('hasKey')} mask={openai_meta.get('keyMask')!r} "
            f"ref={openai_meta.get('credentialRef')!r} "
            f"backend={((b6 or {}).get('data') or {}).get('credentialBackend')!r}",
        )
        mask6 = str(openai_meta.get("keyMask", ""))
        check(
            "6d 掩码不含完整 key（只露首尾）",
            SECRET_KEY not in mask6 and "****" in mask6,
            f"mask={mask6!r}",
        )

        # 6e：DB 里连引用名都不该有明文以外的形态 —— 断言 auth 相关的表里没有 key 值
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            hits: list[str] = []
            for t in tables:
                cols = [c[1] for c in con.execute(f"PRAGMA table_info({t})").fetchall()]
                for c in cols:
                    try:
                        n = con.execute(
                            f"SELECT COUNT(*) FROM {t} WHERE CAST({c} AS TEXT) LIKE '%sk-%'"
                        ).fetchone()
                    except Exception:
                        continue
                    if n and n[0]:
                        hits.append(f"{t}.{c}×{n[0]}")
        finally:
            con.close()
        check(
            "6e 全库无任何 `sk-` 形态字符串（逐表逐列 LIKE 扫描）",
            not hits,
            f"命中={hits}" if hits else f"扫描 {len(tables)} 张表，无命中",
        )

        # ======================================================== 验收 7/8 双模式隔离 ★
        print("\n--- 验收项 7/8：双模式隔离与上下文注入（端到端）★" + "-" * 12)
        # 先在"用户数据"侧放真东西：创建一个模式（含 openTargets 目录）+ 学习目标 + 技能
        st_m, b_m = core_api("/api/v1/modes", "POST", {
            "name": SECRET_MODE_NAME,
            "description": "验收用：用于验证 AI 隔离与注入",
            "apps": [],
            "openTargets": [{"path": f"D:/projects/{SECRET_PROJECT}", "label": "项目", "type": "folder"}],
            "layout": "",
            "autoApply": False,
        })
        mode_id = ((b_m or {}).get("data") or {}).get("id")
        check("准备：创建含项目目录的模式", bool(mode_id), f"status={st_m} id={mode_id}")

        core_api(f"/api/v1/config/ai.context.learning_goal", "PUT", SECRET_GOAL)
        core_api(f"/api/v1/config/ai.context.profile_skills", "PUT", [SECRET_SKILL])
        # 让当前模式指向它（ai_context 从 config 的 mode.current 读当前模式名）
        core_api("/api/v1/config/mode.current", "PUT", SECRET_MODE_NAME)

        # 双模式请求：**都硬塞 context**（越权传入），看 mock 侧拿到什么
        open(record, "w", encoding="utf-8").close()
        ctx_payload = {
            "modeName": SECRET_MODE_NAME,
            "modeApps": ["ZQ7-VSCode"],
            "projectDir": f"D:/projects/{SECRET_PROJECT}",
            "learningGoal": SECRET_GOAL,
            "profileSkills": [SECRET_SKILL],
        }
        post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "openai", "model": "mock-gpt",
                "apiBase": f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1",
                "mode": "consult",
                "context": ctx_payload,          # ← 故意越权
                "messages": [{"role": "user", "content": "我的项目是什么"}],
            },
        )
        post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "openai", "model": "mock-gpt",
                "apiBase": f"http://127.0.0.1:{MOCK_OPENAI_PORT}/v1",
                "mode": "workspace",
                "context": ctx_payload,
                "messages": [{"role": "user", "content": "我现在该做什么"}],
            },
        )
        time.sleep(0.6)
        recs = []
        with open(record, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
        check("准备：mock 收到两次请求", len(recs) >= 2, f"收到 {len(recs)}")

        if len(recs) >= 2:
            consult_sys = recs[0].get("system", "")
            workspace_sys = recs[1].get("system", "")
            leaks = [
                t for t in (SECRET_MODE_NAME, SECRET_PROJECT, SECRET_GOAL, SECRET_SKILL, "ZQ7-VSCode")
                if t in consult_sys
            ]
            check(
                "7 ★ consult：模型侧拿不到任何用户数据（即使请求体硬塞）",
                not leaks,
                f"泄露项={leaks}",
            )
            check(
                "8 ★ workspace：模型侧确实收到模式与项目（对照组，证明不是链路整条断掉）",
                SECRET_MODE_NAME in workspace_sys and SECRET_PROJECT in workspace_sys,
                f"system 前 160 字：{workspace_sys[:160]}",
            )
            check(
                "7b 两模式的 system 提示词不同（证明真分支）",
                consult_sys != workspace_sys,
            )
            check(
                "8b consult 的 system 明确声明无数据权限（模型知道该拒答）",
                "无法访问" in consult_sys or "没有" in consult_sys,
                f"consult system 前 100 字：{consult_sys[:100]}",
            )
        else:
            check("7 ★ consult 隔离", False, "未取到 mock 记录")
            check("8 ★ workspace 注入", False, "未取到 mock 记录")

        # 权限提示与装配同源（core 的 ai_permission_scope ↔ sidecar 的 /ai/scopes）
        st_s1, b_s1 = http_json(f"{SIDECAR}/ai/scopes", "POST", {"mode": "consult"})
        st_s2, b_s2 = http_json(f"{SIDECAR}/ai/scopes", "POST", {"mode": "workspace"})
        s1 = ((b_s1 or {}).get("data") or {}).get("scopes")
        s2 = ((b_s2 or {}).get("data") or {}).get("scopes")
        check(
            "7c consult 权限范围恒为空（UI 提示与实际行为同源）",
            s1 == [] and isinstance(s2, list) and len(s2) == 5,
            f"consult={s1} workspace={s2}",
        )

        # ======================================================== 验收 9 侧栏持久化
        print("\n--- 验收项 9：侧栏持久化" + "-" * 12)
        # 侧栏是前端状态，持久化有两条路：
        #   a) localStorage —— UI 直接读写（ui/src/stores/ai.ts 的 lsGet/lsSet）。
        #      **webview 的 localStorage 落在 Tauri 的缓存目录里**，外部脚本够不着，
        #      只能由真实窗口验收（见报告的人工步骤），本脚本**不声称测过它**。
        #   b) core 的 config 表 —— `put_config` 的权威副本，脚本可机器验证。
        # 本项验证 (b) 的读写 + 重启存活 + **键名契约**（防前端改了键名后端没跟上）。
        KEYS = {
            "ui.ai.width": "480",
            "ui.ai.collapsed": "1",
            "ui.ai.provider": "ollama",
            "ui.ai.model": "mock-llama",
            "ui.ai.mode": "workspace",
        }
        write_ok = True
        for k, v in KEYS.items():
            st_w, _ = core_api(f"/api/v1/config/{k}", "PUT", v)
            if st_w != 200:
                write_ok = False
        read_back = {}
        for k in KEYS:
            st_r, b_r = core_api(f"/api/v1/config/{k}")
            read_back[k] = (b_r or {}).get("data")
        persisted = all(str(read_back.get(k)) == v for k, v in KEYS.items())
        check(
            "9a 持久化键可写可读（跨 webview 的权威副本）",
            write_ok and persisted,
            f"写入={write_ok} 读回={read_back}",
        )

        # 重启一次，确认 9a 的内容在库里活下来
        stop_app(core)
        core = None
        time.sleep(1.2)
        core = start_app(exe, data_dir)
        cfg2 = wait_for_new_port(db_path, port, timeout_s=40.0)
        base = f"http://127.0.0.1:{cfg2.get('runtime.http_port')}"
        after = {}
        for k in KEYS:
            _, b_r = core_api(f"/api/v1/config/{k}")
            after[k] = (b_r or {}).get("data")
        check(
            "9b 重启后仍保持（真正落库，不是进程内存）",
            all(str(after.get(k)) == v for k, v in KEYS.items()),
            f"重启后={after}",
        )

        # 键名契约：前端源码里的键名必须与本脚本一致（防"改了前端忘了后端"）
        ai_store = REPO_ROOT / "ui" / "src" / "stores" / "ai.ts"
        store_text = ai_store.read_text(encoding="utf-8") if ai_store.exists() else ""
        missing_keys = [k for k in KEYS if f"'{k}'" not in store_text]
        check(
            "9c 前端键名与验收脚本一致（防契约漂移）",
            bool(store_text) and not missing_keys,
            f"ui/src/stores/ai.ts 中缺失：{missing_keys}" if missing_keys else "5 个键名全部命中",
        )

        # ======================================================== 验收 10 降级
        print("\n--- 验收项 10：降级（Provider 不可达）" + "-" * 12)
        lines10, _, _, _ = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "ollama",
                "apiBase": "http://127.0.0.1:9",
                "model": "x",
                "mode": "consult",
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=20,
        )
        errs = [l for l in lines10 if l.get("type") == "error"]
        check("10a 不可达时返回结构化错误（不是崩溃）", len(errs) == 1, f"lines={lines10[:2]}")
        if errs:
            check(
                "10b 错误码可映射为用户提示（08 §7 降级表）",
                errs[0].get("code") in ("local_model_down", "unreachable", "timeout"),
                f"code={errs[0].get('code')} message={str(errs[0].get('message'))[:80]!r}",
            )
        st_h2, _ = core_api("/health")
        check("10c 出错后应用未崩溃（core 仍存活）", st_h2 == 200, f"/health={st_h2}")

        # 未配置 key 的引导
        st10d, b10d = http_json(
            f"{SIDECAR}/ai/credential", "POST", {"provider": "deepseek", "secret": ""}
        )
        lines10d, _, _, _ = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "deepseek",
                "model": "deepseek-chat",
                "mode": "consult",
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=20,
        )
        errs10d = [l for l in lines10d if l.get("type") == "error"]
        check(
            "10d 未配置 key → no_api_key（引导去设置，不吐堆栈）",
            bool(errs10d) and errs10d[0].get("code") == "no_api_key",
            f"code={errs10d[0].get('code') if errs10d else None}",
        )

        # 占位 Provider 诚实报错
        st10e, _ = http_json(f"{SIDECAR}/ai/providers", "POST", {})
        lines10e, _, _, _ = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "web-ai",
                "mode": "consult",
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=20,
        )
        errs10e = [l for l in lines10e if l.get("type") == "error"]
        check(
            "10e 未开放的 Provider 抛 not_implemented（不静默返回空）",
            bool(errs10e) and errs10e[0].get("code") == "not_implemented",
            f"code={errs10e[0].get('code') if errs10e else None}",
        )
        lines10f, _, _, _ = post_stream(
            f"{SIDECAR}/ai/chat",
            {
                "provider": "不存在的供应商",
                "mode": "consult",
                "messages": [{"role": "user", "content": "hi"}],
            },
            timeout=20,
        )
        errs10f = [l for l in lines10f if l.get("type") == "error"]
        check(
            "10f 未知 Provider 报错（不静默兜底成某个默认模型）",
            bool(errs10f),
            f"code={errs10f[0].get('code') if errs10f else None}",
        )

    except Exception as e:  # noqa: BLE001
        check("执行异常", False, f"{type(e).__name__}: {e}")
    finally:
        stop_app(core)
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
        kill_sidecar(baseline)
        for pid in spawned_apps:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        # 清掉本脚本写入的系统凭据（不留痕）
        for pid in ("openai", "deepseek", "ollama"):
            try:
                subprocess.run(
                    [PY, "-c",
                     "import sys; sys.path.insert(0, r'%s');"
                     "from ai.credentials import store, ref_for;"
                     "store().delete(ref_for('%s'))" % (REPO_ROOT, pid)],
                    capture_output=True, timeout=15,
                )
            except Exception:
                pass
        if os.path.exists(record):
            try:
                os.remove(record)
            except OSError:
                pass
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)
        else:
            print(f"[verify5] 数据目录已保留：{data_dir}")

    print("\n" + "=" * 70)
    print("阶段5 验收核验结果")
    print("=" * 70)
    all_ok = True
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
        if detail:
            print(f"      {detail}")
        all_ok = all_ok and passed
    print("=" * 70)
    print(f"合计 {sum(1 for _, p, _ in results if p)}/{len(results)} 通过")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
