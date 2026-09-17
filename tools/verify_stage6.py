#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段6 验收自动核验：把 09「验收标准」8 项做成机器可判。

覆盖（docs/agent-dev/09-阶段指令-学习成长.md §验收标准）：

| # | 验收项 | 本脚本怎么判 |
|---|--------|--------------|
| 1 | 生成路线 | 真 release core → 真 sidecar → mock 返回固定路线 JSON：**端到端**走通，解析出 3~7 个节点 |
| 2 | 路线可编辑 | 采纳 → 增 / 删 / 改名 / 调序，每一步都**回读**断言落库（不是只看返回值） |
| 3 | 状态更新 | 改节点状态 → 进度 done/total/percent 由 core 重算；**重启 core** 后仍在 |
| 4 | 提醒 | `remind_after_days=0` → `reminders/check` 立刻命中 |
| 5 | 提醒动作 | 暂停的目标不再命中；**改回 learning 又命中**（对照组，证明是状态判据而链路没断）；紧接再扫 → 冷却期不重复 |
| 6 | AI 只建议 ★ | suggest 调用**前后对学习/项目表做全行快照比对**，必须逐字节一致 |
| 7 | 联动 | 项目绑定工作模式 → `by-mode` 命中；完成项目只**提议**完成目标、**不自动改**目标状态 |
| 8 | 解析降级 | mock 返回非法 JSON → `degraded=true` + 200 + 界面数据仍可读；围栏包裹的 JSON 仍能捞回 |

## 边界如实声明（红线 V6：不夸大自测覆盖）

 - **验收项 1 的"节点是否合理"是人工判据**，机器只能判"链路通、结构合法、数量在 3~7"。
   mock 输出的是**固定夹具** —— 这样做的理由：真调云端模型同一次生成节点数会变、
   且要花用户的钱，无法作为可复现判据。把"链路通不通"与"模型答得好不好"分开，
   前者机器判定，后者留给人工验收（见报告「可复现验收步骤」）。
 - **事件投递到 webview 一步没测**：core 的 `/internal/*` 面只有 `event/publish`，
   没有订阅入口；事件走 tokio broadcast + Tauri emit，外部脚本读不到。
   本脚本对事件只做**接线级**断言（常量登记 / 发布点存在 / 前端订阅点存在），
   运行时投递由真实 Tauri 窗口人工验收。**本项不声称测过运行时事件**。
 - 验收项 3 的"重启后保持"是**真重启进程**（不是重新建连接），与 verify_stage5 同口径。

## 与其它脚本的分工

 - `tools/ai_mock.py`：本脚本的模型端（`--reply roadmap|fenced|invalid` 三种夹具）。
 - `cargo test`：`parse_roadmap` 的 6 个解析用例、`should_remind` 的 7 个纯函数用例
   （阈值 / 冷却 / 暂停 / 坏时间戳），属**单元级**，本脚本不重复。
 - `tools/gate.py --stage 6 --build`：静态门禁（结构/卫生/编译）。

用法：
  python tools/verify_stage6.py
  python tools/verify_stage6.py --exe core/target/release/personal-workspace-core.exe
  python tools/verify_stage6.py --keep      # 保留临时数据目录供排查

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
import urllib.parse
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# 三个 mock 实例：正常路线 / 围栏包裹 / 非法 JSON。
# 用 ollama（needs_key=False）——避免为了跑验收去动用户的系统凭据库（无语义副作用）。
MOCK_ROADMAP_PORT = 18831
MOCK_FENCED_PORT = 18832
MOCK_INVALID_PORT = 18833
# 阶段6 要的是**内容**而非流式节奏，把块间隔调小（默认 0.08 会把一个 ~400 字的
# JSON 拖成 30 秒，三个用例就超时）。
MOCK_CHUNK_DELAY = "0.004"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")


def http_json(url: str, method: str = "GET", body=None, timeout: float = 60.0):
    """返回 (status, envelope)。envelope 形如 `{ok:true,data:…}` / `{ok:false,error:{…}}`。"""
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
        return 0, {"ok": False, "error": {"code": "transport", "message": str(e)}}


def data_of(resp):
    st, body = resp
    if not body:
        return None
    d = body.get("data")
    # 有些端点（by-mode）的 data 本身可能就是 null —— 与"失败"区分开
    return d if body.get("ok") is True else None


def err_of(resp):
    _st, body = resp
    if not body:
        return ""
    e = body.get("error") or {}
    return f"{e.get('code')}: {e.get('message')}"


def wait_port(port: int, timeout: float = 20.0) -> bool:
    """等 TCP 端口可连（mock 没有 /health，不能用 HTTP 探活）。"""
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
        except Exception:  # noqa: BLE001
            cfg = {}
        port = cfg.get("runtime.http_port")
        if port and port != old_port:
            return cfg
        time.sleep(0.3)
    return cfg


def sidecar_alive(port: str, timeout: float = 2.0) -> bool:
    """直接问 sidecar 的 `/health`（TCP 连通还不够：端口可能被别的东西占着）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def wait_for_new_sidecar_port(db_path: Path, old_port: str, timeout_s: float = 60.0) -> str:
    """等 **新的** sidecar 端口（与 `old_port` 不同）**且**该端口能响应 `/health`。

    为什么不能只判"`runtime.sidecar_port` 非空"：它是**持久化**的 config 键，
    core 重启时**不会**先清空 —— 旧值会一直留到新 sidecar 宣告端口为止。
    于是"等它非空"会**立刻返回旧端口**，后续 AI 调用打到已经死掉的端口上
    （症状还是 400，但换了个马甲）。这类"假就绪"是本脚本最该防的：
    AI 用例全红，看上去像"AI 功能坏了"，实际是脚本自己的前置判断不够严密。
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            port = read_config_map(db_path).get("runtime.sidecar_port")
        except Exception:  # noqa: BLE001
            port = None
        if port and str(port) != str(old_port) and sidecar_alive(str(port)):
            return str(port)
        time.sleep(0.3)
    return ""


def start_app(exe: Path, data_dir: Path) -> subprocess.Popen:
    env = dict(os.environ)
    env["PW_DATA_DIR"] = str(data_dir)
    # ★ 双保险：把 sidecar 钉死在**当前源码**上（详见 verify_stage5.py 的 L-043 说明）。
    # 不设它的话，开发态 release 目录里的 service.exe 快照会被当成安装态被拉起，
    # 于是"跑了但跑的不是这份源码"——静默失真，比编译失败危险得多。
    env["PW_SIDECAR_FORCE_DEV"] = "1"
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


# ---------------------------------------------------------------- 数据快照

# 验收项 6 的判据：这些表是"学习数据"的全部落点。少了任何一张，
# "AI 没写库"就可能只是"没写到我查的那张表"。
SNAPSHOT_TABLES = (
    "learning_goals",
    "learning_roadmap",
    "learning_updates",
    "projects",
)


def snapshot_db(db_path: Path) -> dict[str, list[tuple]]:
    """全表快照（只读打开 —— 验收脚本不得成为第二个写入者）。

    **用 `SELECT *` 而不是列名清单**：列名清单一旦写错（比如给没有 `deleted_at`
    的表带上该列），`sqlite3.Error` 会让两张快照都变成同一个错误占位符，
    于是"前后一致"**假通过** —— 这是本脚本最该防的一类自欺。
    这里改为缺表即**大声失败**，缺列则自动纳入（快照更全，不漏字段）。
    """
    snap: dict[str, list[tuple]] = {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for table in SNAPSHOT_TABLES:
            try:
                snap[table] = con.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            except sqlite3.Error as e:
                raise RuntimeError(f"快照失败：表 {table} 不可读（{e}）") from e
    finally:
        con.close()
    return snap


def snapshot_diff(a: dict[str, list[tuple]], b: dict[str, list[tuple]]) -> str:
    for table in a:
        if a[table] != b[table]:
            return f"{table} 变化：{len(a[table])} 行 → {len(b[table])} 行"
    return ""


def read_src(rel: str) -> str:
    p = REPO_ROOT / rel
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description="阶段6 验收自动核验")
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

    data_dir = Path(tempfile.mkdtemp(prefix="pw-verify6-"))
    db_path = data_dir / "workspace.db"

    procs: list[subprocess.Popen] = []
    core: subprocess.Popen | None = None
    baseline = list_named_pids("service.exe")
    base = ""
    http_port = ""

    print(f"[verify6] exe = {exe}")
    print(f"[verify6] data dir = {data_dir}")

    def api(path: str, method: str = "GET", body=None, timeout: float = 60.0):
        return http_json(base + path, method, body, timeout)

    try:
        # ---------------------------------------------------------- 起 mock
        print("\n启动 mock Provider（roadmap / fenced / invalid 三种夹具）...")
        for port, reply in (
            (MOCK_ROADMAP_PORT, "roadmap"),
            (MOCK_FENCED_PORT, "fenced"),
            (MOCK_INVALID_PORT, "invalid"),
        ):
            procs.append(
                subprocess.Popen(
                    [PY, str(REPO_ROOT / "tools" / "ai_mock.py"),
                     "--port", str(port), "--kind", "ollama",
                     "--reply", reply, "--chunk-delay", MOCK_CHUNK_DELAY],
                    cwd=str(REPO_ROOT),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            )
        if not all(wait_port(p) for p in (MOCK_ROADMAP_PORT, MOCK_FENCED_PORT, MOCK_INVALID_PORT)):
            print("  [FATAL] mock Provider 未全部启动")
            return 1
        print("  三个 mock 就绪")

        # ---------------------------------------------------------- 起 core
        print("\n启动 core（release，开发态拉 sidecar）...")
        core = start_app(exe, data_dir)
        cfg = wait_for_new_port(db_path, "", timeout_s=40.0)
        http_port = cfg.get("runtime.http_port", "")
        if not http_port:
            raise RuntimeError("core 未写出 runtime.http_port")
        base = f"http://127.0.0.1:{http_port}"
        print(f"  core http = {base}")

        st_h, _ = api("/health")
        check("前置：core 存活", st_h == 200, f"/health={st_h}")

        sc_port = wait_for_new_sidecar_port(db_path, "")
        check(
            "前置：core 拉起了 sidecar 且 /health 可用（AI 建议的必要前置）",
            bool(sc_port),
            f"sidecar port={sc_port or '（未就绪）'}",
        )

        # 阶段6 新登记的两个 config 键必须已就位且有默认值（09 §5）
        st_d, b_d = api("/api/v1/config/learning.remind_after_days")
        st_e, b_e = api("/api/v1/config/learning.remind_enabled")
        check(
            "前置：提醒配置键已登记且默认值正确（30 天 / 开启）",
            data_of((st_d, b_d)) == 30 and data_of((st_e, b_e)) is True,
            f"remind_after_days={data_of((st_d, b_d))} remind_enabled={data_of((st_e, b_e))}",
        )

        # ======================================================== 验收 1 目标输入 + 生成路线
        print("\n--- 验收项 1：目标输入 + AI 生成路线（端到端）" + "-" * 12)
        st_g, b_g = api("/api/v1/learning/goals", "POST", {
            "title": "学习计算机视觉并完成项目",
            "description": "从 Python 基础到能独立完成一个 CV 小项目",
            "expectedAt": "2026-12-31",
            "priority": "high",
        })
        goal = data_of((st_g, b_g))
        check(
            "1a 创建学习目标（标题/描述/期望时间/优先级）",
            st_g == 200 and bool(goal) and goal.get("title") == "学习计算机视觉并完成项目"
            and goal.get("expectedAt") == "2026-12-31" and goal.get("priority") == "high",
            f"status={st_g} goal={ {k: goal.get(k) for k in ('id','status','priority')} if goal else None }",
        )
        if not goal:
            raise RuntimeError(f"创建目标失败：{err_of((st_g, b_g))}")
        gid = goal["id"]

        st_s, b_s = api("/api/v1/learning/suggest", "POST", {
            "goalId": gid,
            "kind": "roadmap",
            "provider": "ollama",
            "model": "mock-llama",
            "apiBase": f"http://127.0.0.1:{MOCK_ROADMAP_PORT}",
        }, timeout=120)
        sug = data_of((st_s, b_s))
        nodes_ai = (sug or {}).get("nodes") or []
        check(
            "1b 端到端生成路线（core → sidecar → mock → 解析）",
            st_s == 200 and bool(sug) and sug.get("degraded") is False,
            f"status={st_s} degraded={(sug or {}).get('degraded')} "
            f"reason={(sug or {}).get('reason')} err={err_of((st_s, b_s))}",
        )
        check(
            "1c 结构合法：3~7 个节点、每个都有标题",
            len(nodes_ai) >= 3 and len(nodes_ai) <= 7
            and all(str(n.get("title", "")).strip() for n in nodes_ai),
            f"节点={[n.get('title') for n in nodes_ai]}",
        )
        check(
            "1d 建议态：advisory=true + promptKey=roadmap_generate（09 §禁止事项 2）",
            (sug or {}).get("advisory") is True and sug.get("promptKey") == "roadmap_generate",
            f"advisory={(sug or {}).get('advisory')} promptKey={(sug or {}).get('promptKey')}",
        )
        # ★ 关键：AI 生成完，**数据库里不能有任何节点**（红线 V3 的第一道证明）
        st_n, b_n = api(f"/api/v1/learning/goals/{gid}/nodes")
        check(
            "1e ★ AI 生成后未落库（仍需用户采纳）",
            st_n == 200 and data_of((st_n, b_n)) == [],
            f"节点表={data_of((st_n, b_n))}",
        )

        # ---- 后续用例不依赖"AI 是否成功" ----
        # 否则 AI 侧一个失败会级联成一片 FAIL（第一版实测：1b 挂了 → 2a/2e/2f/3x 全崩），
        # 报告就再也看不出"路线 CRUD / 状态 / 提醒到底通不通"。
        # AI 失败时退回本地草稿**并显式注明**，让每个用例各自独立成立。
        FALLBACK_DRAFTS = [
            {"title": "Python 基础", "estimated": "2周", "resources": ["官方教程"]},
            {"title": "OpenCV", "estimated": "3周", "resources": ["图像处理基础"]},
            {"title": "CNN", "estimated": "3周"},
            {"title": "深度学习", "estimated": "4周"},
            {"title": "项目实践", "estimated": "3周"},
        ]
        drafts_to_confirm = nodes_ai if len(nodes_ai) >= 3 else FALLBACK_DRAFTS
        if len(nodes_ai) < 3:
            print("  [注] AI 路线为空/不足 → 后续用例改用**本地草稿**"
                  "（采纳/编辑/状态/提醒路径仍各自独立判定）")

        # ======================================================== 验收 2 采纳 + 路线可编辑
        print("\n--- 验收项 2：路线可编辑（增删改名调序，每步回读）" + "-" * 12)
        st_c, b_c = api(f"/api/v1/learning/goals/{gid}/roadmap", "POST", {
            "nodes": drafts_to_confirm,
            "replace": True,
            "raw": (sug or {}).get("raw", ""),
        })
        confirmed = data_of((st_c, b_c)) or []
        check(
            "2a 采纳路线（用户动作 → 落库，sort_order 连续）",
            st_c == 200 and len(confirmed) == len(drafts_to_confirm)
            and [n["sortOrder"] for n in confirmed] == list(range(1, len(confirmed) + 1)),
            f"status={st_c} orders={[n['sortOrder'] for n in confirmed]}"
            f" 来源={'AI 建议' if len(nodes_ai) >= 3 else '本地草稿'}",
        )
        # 覆盖保护：非 replace 再来一次应被拒（防"重新生成"静默重置用户已标的进度）
        st_c2, b_c2 = api(f"/api/v1/learning/goals/{gid}/roadmap", "POST", {
            "nodes": drafts_to_confirm, "replace": False,
        })
        check(
            "2b 覆盖保护：未显式 replace 时拒绝覆盖已有路线",
            st_c2 != 200, f"status={st_c2} err={err_of((st_c2, b_c2))}",
        )

        st_a, b_a = api("/api/v1/learning/nodes", "POST", {
            "goalId": gid, "input": {"title": "线性代数补强", "estimated": "1周"},
        })
        added = data_of((st_a, b_a))
        check(
            "2c 新增节点 → 追加到末尾",
            st_a == 200 and bool(added) and added.get("sortOrder") == len(confirmed) + 1,
            f"status={st_a} sortOrder={(added or {}).get('sortOrder')}",
        )
        n_added = (added or {}).get("id")

        st_r, b_r = api(f"/api/v1/learning/nodes/{n_added}", "PUT", {"title": "线性代数（补强）"})
        check(
            "2d 改名生效",
            st_r == 200 and data_of((st_r, b_r))["title"] == "线性代数（补强）",
            f"title={(data_of((st_r, b_r)) or {}).get('title')}",
        )

        st_m, b_m = api(f"/api/v1/learning/nodes/{n_added}/move", "POST", {"delta": -1})
        moved = data_of((st_m, b_m)) or []
        orders = [n["sortOrder"] for n in moved]
        check(
            "2e 调序（上移一位）→ 重排后仍连续",
            st_m == 200 and orders == list(range(1, len(moved) + 1))
            and not moved[-1]["id"] == n_added,
            f"orders={orders} 末位节点={moved[-1]['title'] if moved else None}",
        )

        st_dl, b_dl = api(f"/api/v1/learning/nodes/{n_added}", "DELETE")
        st_l, b_l = api(f"/api/v1/learning/goals/{gid}/nodes")
        after_del = data_of((st_l, b_l)) or []
        check(
            "2f 删除节点 → 回读确认已删且序号重排连续",
            st_dl == 200 and len(after_del) == len(confirmed)
            and [n["sortOrder"] for n in after_del] == list(range(1, len(after_del) + 1)),
            f"删除后 {len(after_del)} 个节点，orders={[n['sortOrder'] for n in after_del]}",
        )

        # ======================================================== 验收 3 状态管理
        print("\n--- 验收项 3：状态更新（用户手动）+ 进度派生 + 重启保持" + "-" * 12)
        # 前置兜底：验收3 需要 ≥2 个节点。2a 正常时已落 5 个；若上游异常导致节点不足，
        # 这里补齐**并注明**，避免一个失败把后面用例连坐（第一版实测：1b 挂了 → 3x/4/5/6/7 全塌）。
        if len(after_del) < 2:
            for _ in range(6):
                if len(after_del) >= max(2, len(drafts_to_confirm)):
                    break
                api("/api/v1/learning/nodes", "POST",
                    {"goalId": gid, "input": {"title": f"补位节点{len(after_del) + 1}"}})
                st_l, b_l = api(f"/api/v1/learning/goals/{gid}/nodes")
                after_del = data_of((st_l, b_l)) or []
            print(f"  [注] 上游节点不足 → 已补齐到 {len(after_del)} 个"
                  f"（3a/3b/3e 的结论仅在此前提下成立）")
        if len(after_del) < 2:
            check("3 状态更新（前置：至少 2 个节点）", False,
                  f"节点数={len(after_del)} —— 路线落库路径整体不可用，本项及后续依赖项无法判定")
            raise RuntimeError("验收3 前置不满足：节点不足")

        first, second = after_del[0], after_del[1]
        st_u, b_u = api(f"/api/v1/learning/nodes/{first['id']}", "PUT", {"status": "done"})
        check(
            "3a 标记第一个节点完成 → completedAt 自动补写",
            st_u == 200 and bool(data_of((st_u, b_u))) and data_of((st_u, b_u))["completedAt"],
            f"status={(data_of((st_u, b_u)) or {}).get('status')} "
            f"completedAt={(data_of((st_u, b_u)) or {}).get('completedAt')}",
        )
        st_u2, _ = api(f"/api/v1/learning/nodes/{second['id']}", "PUT", {"status": "learning"})
        st_g3, b_g3 = api(f"/api/v1/learning/goals/{gid}")
        g3 = data_of((st_g3, b_g3))
        total = len(after_del)
        check(
            "3b 进度由 core 派生（1/total，percent 一致）",
            bool(g3) and g3["progress"]["done"] == 1 and g3["progress"]["total"] == total
            and g3["progress"]["percent"] == int(1 * 100 / total),
            f"progress={g3['progress'] if g3 else None}（='学习中'不计入完成）",
        )
        # 备注：应写 learning_updates（09 §3）
        st_up, b_up = api("/api/v1/learning/updates", "POST", {
            "goalId": gid, "nodeId": first["id"], "content": "跟完了第 1 章，画出卷积示意图",
        })
        st_ul, b_ul = api(f"/api/v1/learning/goals/{gid}/updates?limit=20")
        ups = data_of((st_ul, b_ul)) or []
        check(
            "3c 备注写入更新记录（learning_updates）",
            st_up == 200 and any("卷积示意图" in u["content"] for u in ups),
            f"status={st_up} 记录数={len(ups)}",
        )
        if len(nodes_ai) >= 3:
            check(
                "3d 采纳后保留 AI 原文快照（roadmapRaw —— 降级展示 / 重新生成对比的依据）",
                bool(g3) and bool(g3.get("roadmapRaw")),
                f"roadmapRaw 长度={len((g3 or {}).get('roadmapRaw') or '')}",
            )
        else:
            # 上游 AI 失败时不该往库里写伪造的"AI 原文" —— 空就是空
            check(
                "3d 无 AI 原文时不写垃圾快照（roadmapRaw 保持为空）",
                bool(g3) and not g3.get("roadmapRaw"),
                f"roadmapRaw={(g3 or {}).get('roadmapRaw')!r}"
                f"（上游 AI 未成功，本项按「无原文」口径判定）",
            )

        # 真重启：进程级的持久化证明（不是"重新建连接"）
        print("  ↻ 重启 core 验证持久化 ...")
        stop_app(core)
        core = None
        time.sleep(1.2)
        core = start_app(exe, data_dir)
        cfg2 = wait_for_new_port(db_path, http_port, timeout_s=40.0)
        http_port = cfg2.get("runtime.http_port", "")
        base = f"http://127.0.0.1:{http_port}"
        # ★ 重启后必须**重新等 sidecar**：core 是异步拉起 sidecar 的，
        # http_port 先写好、sidecar_port 后写好（且旧值不会被清空 —— 见
        # `wait_for_new_sidecar_port` 的说明）。只等 http_port 就往下走的话，
        # 后面的 AI 用例会全部拿到 400「sidecar 尚未就绪」，症状像"AI 功能坏了"。
        sc_new = wait_for_new_sidecar_port(db_path, sc_port)
        check(
            "3f 重启后 sidecar 重新就绪（AI 用例的前置）",
            bool(sc_new),
            f"旧端口={sc_port} 新端口={sc_new or '（未就绪）'}",
        )
        sc_port = sc_new or sc_port
        st_g4, b_g4 = api(f"/api/v1/learning/goals/{gid}")
        st_l4, b_l4 = api(f"/api/v1/learning/goals/{gid}/nodes")
        g4 = data_of((st_g4, b_g4))
        nodes4 = data_of((st_l4, b_l4)) or []
        check(
            "3e ★ 重启后目标/节点状态/进度全部保持",
            bool(g4) and g4["progress"]["done"] == 1 and g4["progress"]["total"] == total
            and len(nodes4) == total
            and any(n["id"] == first["id"] and n["status"] == "done" for n in nodes4),
            f"progress={g4['progress'] if g4 else None} 节点={len(nodes4)}",
        )

        # ======================================================== 验收 4 / 5 提醒
        print("\n--- 验收项 4/5：提醒（阈值 0 立刻触发 / 暂停不再打扰）" + "-" * 12)
        # 第二个目标：用于"暂停"对照（第一个目标会被冷却节流，不能用来证明状态判据）
        st_gb, b_gb = api("/api/v1/learning/goals", "POST", {"title": "复习概率论"})
        gid_b = (data_of((st_gb, b_gb)) or {}).get("id")

        # 对照目标**必须在阈值改动前就置为 paused**：
        # 若它先被验收4 那一轮提醒过，7 天冷却会把它盖住，5a/5b 就成了
        # 「冷却的假通过」——看上去验证了状态判据，其实只是没到冷却期（第一版实测踩到）。
        api(f"/api/v1/learning/goals/{gid_b}", "PUT", {"status": "paused"})

        api("/api/v1/config/learning.remind_after_days", "PUT", 0)
        st_ck, b_ck = api("/api/v1/learning/reminders/check", "POST", {})
        hits = data_of((st_ck, b_ck)) or []
        hit_ids = {h["goalId"] for h in hits}
        check(
            "4 阈值改为 0 天 → 立刻触发提醒（含刚创建的目标）",
            st_ck == 200 and gid in hit_ids,
            f"命中={[(h['title'], h['idleDays']) for h in hits]}",
        )
        check(
            "5a 同一轮扫描里「暂停」的目标被排除（该目标从未被提醒过，无冷却干扰）",
            gid_b not in hit_ids,
            f"本轮命中={sorted(hit_ids)}（暂停的目标 {gid_b} 不在其中）",
        )
        # 对照组：改回 learning → 应**立刻**命中。
        # 没有这一步的话，"不提醒"可能只是查询整条断了（假通过）。
        st_ck3, b_ck3 = api(f"/api/v1/learning/goals/{gid_b}", "PUT", {"status": "learning"})
        st_ck3b, b_ck3b = api("/api/v1/learning/reminders/check", "POST", {})
        hits3 = data_of((st_ck3b, b_ck3b)) or []
        check(
            "5b 对照组：改回 learning 立刻又能命中（排除「查询断了」的假通过）",
            gid_b in {h["goalId"] for h in hits3},
            f"本轮命中={sorted(h['goalId'] for h in hits3)}",
        )
        st_ck4, b_ck4 = api("/api/v1/learning/reminders/check", "POST", {})
        check(
            "5c 7 天冷却：紧接着再扫不重复打扰",
            data_of((st_ck4, b_ck4)) == [],
            f"再扫命中={data_of((st_ck4, b_ck4))}",
        )
        api("/api/v1/config/learning.remind_enabled", "PUT", False)
        st_ck5, b_ck5 = api("/api/v1/learning/reminders/check", "POST", {})
        check(
            "5d 总开关关闭后完全静默（09 §禁止事项：不做强制提醒）",
            data_of((st_ck5, b_ck5)) == [],
            f"命中={data_of((st_ck5, b_ck5))}",
        )
        # 复位：后续用例不该受提醒配置影响
        api("/api/v1/config/learning.remind_enabled", "PUT", True)
        api("/api/v1/config/learning.remind_after_days", "PUT", 30)

        # ======================================================== 验收 6 ★ AI 只建议
        print("\n--- 验收项 6：AI 只建议不写库 ★（调用前后全表快照比对）" + "-" * 12)
        before = snapshot_db(db_path)
        st_s6, b_s6 = api("/api/v1/learning/suggest", "POST", {
            "goalId": gid,
            "kind": "roadmap",
            "provider": "ollama",
            "model": "mock-llama",
            "apiBase": f"http://127.0.0.1:{MOCK_ROADMAP_PORT}",
        }, timeout=120)
        # 连"基于现状给优化建议"这条最容易顺手写库的路径一起验
        st_s6b, b_s6b = api("/api/v1/learning/suggest", "POST", {
            "goalId": gid,
            "kind": "optimize",
            "provider": "ollama",
            "model": "mock-llama",
            "apiBase": f"http://127.0.0.1:{MOCK_FENCED_PORT}",
            "extra": "顺便把线性代数补进去",
        }, timeout=120)
        after = snapshot_db(db_path)
        diff = snapshot_diff(before, after)
        check(
            "6 ★ suggest（roadmap + optimize）调用前后学习/项目表逐行一致",
            st_s6 == 200 and st_s6b == 200 and not diff,
            f"diff={diff or '无变化'}（目标 {len(before['learning_goals'])} 行 / 节点 "
            f"{len(before['learning_roadmap'])} 行 / 记录 {len(before['learning_updates'])} 行）"
            f" roadmap={st_s6} optimize={st_s6b}"
            f" err1={err_of((st_s6, b_s6))} err2={err_of((st_s6b, b_s6b))}",
        )
        # 静态防线：AI 建议函数体内不得出现任何写语句（函数边界保证，不只靠调用者自觉）
        ai_body = read_src("core/src/learning/mod.rs")
        i0 = ai_body.find("pub fn ai_suggest")
        i1 = ai_body.find("fn build_question")
        body = ai_body[i0:i1] if i0 >= 0 and i1 > i0 else ""
        check(
            "6b 静态防线：ai_suggest 函数体内无写库调用（INSERT/exec/goal_add/node_add）",
            bool(body) and not any(
                k in body for k in ("INSERT", ".exec(", "goal_add", "node_add", "roadmap_confirm")
            ),
            f"扫描 {len(body)} 字符，未发现写入口径",
        )

        # ======================================================== 验收 8 解析降级
        print("\n--- 验收项 8：解析降级（模型返回非法 JSON）" + "-" * 12)
        before8 = snapshot_db(db_path)
        st_s8, b_s8 = api("/api/v1/learning/suggest", "POST", {
            "goalId": gid,
            "kind": "roadmap",
            "provider": "ollama",
            "model": "mock-llama",
            "apiBase": f"http://127.0.0.1:{MOCK_INVALID_PORT}",
        }, timeout=120)
        sug8 = data_of((st_s8, b_s8))
        check(
            "8a 非法 JSON → 200 + degraded=true + 有降级原因（不抛错给用户）",
            st_s8 == 200 and (sug8 or {}).get("degraded") is True
            and bool((sug8 or {}).get("reason")) and (sug8 or {}).get("nodes") == [],
            f"status={st_s8} degraded={(sug8 or {}).get('degraded')} "
            f"reason={str((sug8 or {}).get('reason'))[:60]!r} err={err_of((st_s8, b_s8))}",
        )
        check(
            "8b 降级仍保留模型原文（文本展示 + 手动录入的素材）",
            bool((sug8 or {}).get("raw")),
            f"raw 前 60 字={str((sug8 or {}).get('raw'))[:60]!r}",
        )
        st_g8, _ = api(f"/api/v1/learning/goals/{gid}")
        st_l8, b_l8 = api(f"/api/v1/learning/goals/{gid}/nodes")
        check(
            "8c 降级后界面数据仍可读（目标与路线都没被破坏）",
            st_g8 == 200 and st_l8 == 200 and len(data_of((st_l8, b_l8)) or []) == total,
            f"goal={st_g8} nodes={st_l8} 节点数={len(data_of((st_l8, b_l8)) or [])}",
        )
        check(
            "8d 降级路径全程未写库",
            not snapshot_diff(before8, snapshot_db(db_path)),
            "快照一致",
        )
        # 容错：围栏包裹的 JSON 不该被判为降级（真实模型常这么答）
        st_s9, b_s9 = api("/api/v1/learning/suggest", "POST", {
            "goalId": gid,
            "kind": "roadmap",
            "provider": "ollama",
            "model": "mock-llama",
            "apiBase": f"http://127.0.0.1:{MOCK_FENCED_PORT}",
        }, timeout=120)
        sug9 = data_of((st_s9, b_s9))
        check(
            "8e 围栏 + 前后废话包裹的 JSON 仍能解析（不误判为降级）",
            st_s9 == 200 and (sug9 or {}).get("degraded") is False
            and len((sug9 or {}).get("nodes") or []) >= 3,
            f"degraded={(sug9 or {}).get('degraded')} 节点数={len((sug9 or {}).get('nodes') or [])}"
            f" status={st_s9} err={err_of((st_s9, b_s9))}",
        )

        # ======================================================== 验收 7 项目 ↔ 模式联动
        print("\n--- 验收项 7：项目与工作模式联动" + "-" * 12)
        st_md, b_md = api("/api/v1/modes", "POST", {
            "name": "验收-开发模式",
            "description": "verify_stage6 用",
            "apps": [],
            "openTargets": [],
            "layout": "",
            "autoApply": False,
        })
        mode_ok = st_md == 200
        st_pj, b_pj = api("/api/v1/projects", "POST", {
            "name": "CV 小项目",
            "role": "独立开发",
            "summary": "图像分类 demo",
            "techStack": ["python", "opencv", "pytorch"],
            "status": "ongoing",
            "directory": "D:/projects/cv-demo",
            "modeName": "验收-开发模式",
            "goalId": gid,
        })
        proj = data_of((st_pj, b_pj))
        check(
            "7a 项目绑定工作模式 + 关联学习目标（含技术栈/目录）",
            mode_ok and st_pj == 200 and bool(proj) and proj.get("modeName") == "验收-开发模式"
            and proj.get("goalId") == gid and proj.get("techStack") == ["python", "opencv", "pytorch"],
            f"status={st_pj} err={err_of((st_pj, b_pj))} project={ {k: (proj or {}).get(k) for k in ('name','modeName','goalId')} }",
        )
        if not proj:
            raise RuntimeError(f"创建项目失败：{err_of((st_pj, b_pj))}")

        st_bm, b_bm = api(f"/api/v1/project/by-mode?modeName={urllib.parse.quote('验收-开发模式')}")
        hit = data_of((st_bm, b_bm))
        check(
            "7b 进入模式时能取到当前项目（侧栏 Widget 的数据源）",
            st_bm == 200 and bool(hit) and hit.get("id") == proj["id"]
            and hit.get("goalTitle") == "学习计算机视觉并完成项目",
            f"status={st_bm} 命中={ (hit or {}).get('name') } goalTitle={(hit or {}).get('goalTitle')}",
        )
        # 同模式再挂一个"已完成"的项目 → by-mode 应仍返回未完成的那个
        api("/api/v1/projects", "POST", {
            "name": "旧 CV 练习", "status": "done",
            "modeName": "验收-开发模式", "goalId": gid,
        })
        st_bm2, b_bm2 = api(f"/api/v1/project/by-mode?modeName={urllib.parse.quote('验收-开发模式')}")
        hit2 = data_of((st_bm2, b_bm2))
        check(
            "7c 同模式多项目时优先返回「未完成」（core 单一判据）",
            bool(hit2) and hit2.get("status") != "done" and hit2.get("id") == proj["id"],
            f"返回={ (hit2 or {}).get('name') }/{(hit2 or {}).get('status')}",
        )
        # 完成项目 = 达成学习目标：只**提议**，绝不自动改目标状态（红线 V3 的邻居）
        st_gd, b_gd = api(f"/api/v1/projects/{proj['id']}", "PUT", {"status": "done"})
        gd = data_of((st_gd, b_gd))
        st_ga, b_ga = api(f"/api/v1/learning/goals/{gid}")
        ga = data_of((st_ga, b_ga))
        check(
            "7d 完成项目只提议完成目标（linkedGoalDone=true），目标状态不被自动改",
            st_gd == 200 and (gd or {}).get("linkedGoalDone") is True
            and (ga or {}).get("status") != "done",
            f"linkedGoalDone={(gd or {}).get('linkedGoalDone')} 目标状态={(ga or {}).get('status')}",
        )

        # ======================================================== 接线检查（静态）
        print("\n--- 接线检查：文件存在 ≠ 功能存在（REVIEW-003 口径）" + "-" * 12)
        wiring = [
            ("core/src/event_bus/events.rs", "LEARNING_PROGRESS_UPDATED", "事件常量登记"),
            ("core/src/event_bus/events.rs", "LEARNING_REMINDER", "提醒事件常量登记"),
            ("core/src/learning/mod.rs", "LEARNING_PROGRESS_UPDATED", "写入口发布进度事件"),
            ("core/src/learning/reminder.rs", "LEARNING_REMINDER", "提醒调度发布提醒事件"),
            ("ui/src/stores/learning.ts", "LEARNING_PROGRESS_UPDATED", "前端订阅进度事件"),
            ("ui/src/stores/learning.ts", "LEARNING_REMINDER", "前端订阅提醒事件"),
            ("ui/src/views/LearningView.vue", "roadmapConfirm", "学习页接采纳动作"),
            ("ui/src/views/LearningView.vue", "advisory", "学习页区分「建议态」"),
            ("ui/src/views/ProjectView.vue", "modeName", "项目页可绑定模式"),
            ("ui/src/widgets/LearningProgressWidget.vue", "useLearningStore", "学习 Widget 消费 store"),
            ("ui/src/widgets/CurrentProjectWidget.vue", "byMode", "当前项目 Widget 走 by-mode"),
            ("ui/src/widgets/CurrentProjectWidget.vue", "MODE_CHANGED", "切模式即刷新项目"),
            ("ui/src/widgets/index.ts", "learning-progress", "学习 Widget 已注册"),
            ("ui/src/widgets/index.ts", "current-project", "项目 Widget 已注册"),
            ("core/src/main.rs", "spawn_reminder_watcher", "后台提醒调度已装配"),
            ("core/src/learning/mod.rs", "advisory", "建议恒带 advisory 标记"),
        ]
        missing = []
        for rel, needle, why in wiring:
            text = read_src(rel)
            if needle not in text:
                missing.append(f"{rel}↛{why}({needle})")
        check(
            f"接线：{len(wiring)} 条订阅/注册关系全部成立",
            not missing,
            "全部命中" if not missing else f"缺失：{missing}",
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
        if not args.keep:
            shutil.rmtree(data_dir, ignore_errors=True)
        else:
            print(f"[verify6] 数据目录已保留：{data_dir}")

    print("\n" + "=" * 70)
    print("阶段6 验收核验结果")
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
