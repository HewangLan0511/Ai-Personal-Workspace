#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段7 验收自动核验：把 10「验收标准」8 项做成机器可判。

覆盖（docs/agent-dev/10-阶段指令-个人档案.md §验收标准）：

| # | 验收项 | 本脚本怎么判 |
|---|--------|--------------|
| 1 | 基础信息 | PUT basic → GET 回读一致；**重启 core** 后仍在 |
| 2 | 技能树 | 添加技能 → 调等级 → 回读（可视化数据源同步）；非法等级/分类被拒 |
| 3 | AI 建议不自动生效 ★ | 触发全部采集链（新增项目/项目完成/目标完成/高频软件）**前后对档案四表做全行快照比对**，必须逐行一致 |
| 4 | 确认后生效 | 确认建议 → profile_projects / profile_timeline 出现新条目（confirmed=1, source=ai_suggested）；重复确认被拒 |
| 5 | 时间线 | 手动加不同月份条目 → 列表按日期倒序（前端按年月分组的排序依据） |
| 6 | 项目同步 | 「项目管理」里完成项目 → 待确认队列出现"是否加入档案"建议（3b 单列断言） |
| 7 | 权限 ★ | consult 模式硬塞 profileSkills → mock 记录的 system 提示词**不含**技能名；workspace 对照组**含**（证明是隔离生效而非链路断） |
| 8 | 导出 | Markdown 含已确认内容 + 隐私告知；**未确认条目不出现在导出里** |

## 边界如实声明（红线 V6）

 - **验收 7 只测到 sidecar 侧**：core 的 `chat_stream` 只有 Tauri command、无 HTTP 面
   （阶段5 的设计决定），脚本无法从外部驱动 core 的完整对话。core 侧的
   `is_data_allowed()`（consult 恒 None）由 `cargo test` 的
   `only_workspace_mode_is_data_allowed` 覆盖 —— 两侧各有一道闸，各有证据。
 - **快照不含 pending_suggestions**：该表**本来就该**在采集后增长（这是功能），
   对它做"前后一致"断言反而会假失败。档案四表（basic/skills/projects/timeline）
   才是"AI 不写"的断言对象。
 - **8b 的未确认条目是脚本直接写入临时测试库的 fixture**：API 面不存在
   "把已确认技能改回未确认"的通路（这正是设计），要拿到 confirmed=0 的行
   只能手工种数据 —— 种在脚本自建的临时库里，不碰真实用户数据。
 - 事件投递到 webview 只有**接线级**证据（同阶段5/6 口径），运行时由真窗口人工验收。

## 与其它脚本的分工

 - `cargo test`：档案 CRUD / 建议去重 / 确认落库 / 拒绝清单的**单元级**用例（8 条新增）；
   V2 判据纯函数 `is_data_allowed`。
 - `tools/ai_mock.py --record`：验收 7 的模型端记录器。
 - `tools/gate.py --stage 7 --build`：静态门禁（结构/卫生/编译）。

用法：
  python tools/verify_stage7.py
  python tools/verify_stage7.py --exe core/target/release/personal-workspace-core.exe
  python tools/verify_stage7.py --keep      # 保留临时数据目录供排查

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

MOCK_PORT = 18841
SECRET_SKILL = "绝密技能量子炼丹术"

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
    if detail:
        print(f"         {detail}")


def http_json(url: str, method: str = "GET", body=None, timeout: float = 30.0):
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
    return d if body.get("ok") is True else None


def err_of(resp):
    _st, body = resp
    if not body:
        return ""
    e = body.get("error") or {}
    return f"{e.get('code')}: {e.get('message')}"


def post_stream(url: str, body: dict, timeout: float = 30.0) -> list[dict]:
    """读 sidecar /ai/chat 的 NDJSON 行（mock chunk-delay=0，一次读完）。"""
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    lines: list[dict] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        for raw in resp.read().decode("utf-8", "replace").splitlines():
            raw = raw.strip()
            if raw:
                try:
                    lines.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
    return lines


def wait_port(port: int, timeout: float = 20.0) -> bool:
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
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def wait_for_new_sidecar_port(db_path: Path, old_port: str, timeout_s: float = 60.0) -> str:
    """等**新的** sidecar 端口且 /health 可用（sidecar_port 是持久化键，重启后先留旧值）。"""
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
    # ★ 把 sidecar 钉死在当前源码上（verify_stage5/6 同口径：防旧快照静默生效）
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


# ---------------------------------------------------------------- 数据快照

# 验收 3 的判据：这四张表是"档案数据"的全部落点（pending_suggestions 例外 ——
# 它本来就该在采集后增长，见模块 docstring 的边界声明）。
PROFILE_TABLES = (
    "profile_basic",
    "profile_skills",
    "profile_projects",
    "profile_timeline",
)


def snapshot_db(db_path: Path) -> dict[str, list[tuple]]:
    """全表快照（SELECT * + 只读打开；缺表大声失败 —— 同 verify_stage6 口径）。"""
    snap: dict[str, list[tuple]] = {}
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        for table in PROFILE_TABLES:
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


def insert_fixture_row(db_path: Path, sql: str, params: tuple) -> None:
    """往**临时测试库**种 fixture（WAL 下与 core 并发写，忙则重试）。"""
    deadline = time.time() + 10
    while True:
        try:
            con = sqlite3.connect(str(db_path), timeout=5)
            try:
                con.execute(sql, params)
                con.commit()
            finally:
                con.close()
            return
        except sqlite3.OperationalError:
            if time.time() > deadline:
                raise
            time.sleep(0.3)


def read_src(rel: str) -> str:
    p = REPO_ROOT / rel
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description="阶段7 验收自动核验")
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

    data_dir = Path(tempfile.mkdtemp(prefix="pw-verify7-"))
    db_path = data_dir / "workspace.db"

    procs: list[subprocess.Popen] = []
    core: subprocess.Popen | None = None
    base = ""
    http_port = ""
    record_path = data_dir / "mock_record.jsonl"

    print(f"[verify7] exe = {exe}")
    print(f"[verify7] data dir = {data_dir}")

    def api(path: str, method: str = "GET", body=None, timeout: float = 30.0):
        return http_json(base + path, method, body, timeout)

    def start_core_and_wait(old_port: str, old_sidecar: str) -> tuple[str, str]:
        proc = start_app(exe, data_dir)
        procs.append(proc)
        cfg = wait_for_new_port(db_path, old_port, timeout_s=40.0)
        port = cfg.get("runtime.http_port", "")
        if not port:
            raise RuntimeError("core 未写出 runtime.http_port")
        new_base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 15
        while time.time() < deadline:
            st, _ = http_json(new_base + "/health", timeout=3)
            if st == 200:
                break
            time.sleep(0.3)
        sc = wait_for_new_sidecar_port(db_path, old_sidecar)
        return new_base, sc

    try:
        # ---------------------------------------------------------- 起 mock（验收 7 用）
        print("\n启动 mock Provider（带 --record，供隔离断言）...")
        procs.append(
            subprocess.Popen(
                [PY, str(REPO_ROOT / "tools" / "ai_mock.py"),
                 "--port", str(MOCK_PORT), "--kind", "ollama",
                 "--reply", "text", "--chunk-delay", "0",
                 "--record", str(record_path)],
                cwd=str(REPO_ROOT),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )
        if not wait_port(MOCK_PORT):
            print("  [FATAL] mock Provider 未启动")
            return 1
        print("  mock 就绪")

        # ---------------------------------------------------------- 起 core
        print("\n启动 core（release，开发态拉 sidecar）...")
        base, sc_port = start_core_and_wait("", "")
        http_port = base.rsplit(":", 1)[-1]
        print(f"  core http = {base}")
        check("前置：core 存活 + sidecar /health 可用", bool(sc_port),
              f"sidecar port={sc_port or '（未就绪）'}")

        # 契约版本：0006 迁移已执行 ⇒ 契约版本**至少** v9。
        # 注（TECH-04/TECH-05-C）：契约版本是**单调递增**的（TECH-04 升到 v12 登记
        # canonical 的 L1 键，TECH-05-C 只加 config 键、无表结构变更）。
        # 本断言的意图是"迁移 0006 已生效"，故用 `>=` 表达该意图，
        # 而不是钉死一个后续会继续增长的常量 —— 与 `verify_stage9.py:301`
        # 在 TECH-04 时的处置口径一致（属**修过期前置**，不放松任何产品断言）。
        st_v, b_v = api("/api/v1/config/schema_version")
        check("前置：契约版本 ≥ v9（迁移 0006 生效）",
              (data_of((st_v, b_v)) or 0) >= 9, f"schema_version={data_of((st_v, b_v))}")

        # ======================================================== 验收 1 基础信息
        print("\n--- 验收项 1：基础信息（填写 → 展示 → 重启保持）" + "-" * 12)
        put_basic = {"name": "白宇", "direction": "AI 工程", "motto": "少废话",
                     "interests": ["Rust", "本地优先"]}
        st_b, b_b = api("/api/v1/profile/basic", "PUT", put_basic)
        got_b = data_of((st_b, b_b)) or {}
        check("1a 填写基础信息（3 字段引导的数据落点）",
              st_b == 200 and got_b.get("name") == "白宇"
              and got_b.get("interests") == ["Rust", "本地优先"],
              f"status={st_b} name={got_b.get('name')!r}")

        stop_app(core)
        procs = [p for p in procs if p is not core]
        print("  重启 core ...")
        base, sc_port = start_core_and_wait(http_port, sc_port or "")
        http_port = base.rsplit(":", 1)[-1]
        st_b2, b_b2 = api("/api/v1/profile/basic")
        got_b2 = data_of((st_b2, b_b2)) or {}
        check("1b 重启后基础信息仍在（重启持久化）",
              got_b2.get("name") == "白宇" and got_b2.get("motto") == "少废话",
              f"name={got_b2.get('name')!r} motto={got_b2.get('motto')!r}")

        # ======================================================== 验收 2 技能树
        print("\n--- 验收项 2：技能树（添加 / 调等级 / 可视化数据同步）" + "-" * 12)
        st_s, b_s = api("/api/v1/profile/skills", "POST",
                        {"name": "Python", "level": 70, "category": "lang"})
        skill = data_of((st_s, b_s)) or {}
        check("2a 添加技能（confirmed=1，进档案展示）",
              st_s == 200 and skill.get("confirmed") is True and skill.get("level") == 70,
              f"status={st_s} level={skill.get('level')} confirmed={skill.get('confirmed')}")
        sid = skill.get("id")
        st_u, b_u = api(f"/api/v1/profile/skills/{sid}", "PUT", {"level": 85})
        check("2b 调整等级 → 列表（可视化数据源）同步变化",
              data_of((st_u, b_u)) is not None
              and (data_of((st_u, b_u)) or {}).get("level") == 85,
              f"level={(data_of((st_u, b_u)) or {}).get('level')}")
        st_bad, _ = api("/api/v1/profile/skills", "POST",
                        {"name": "越界", "level": 120, "category": "lang"})
        st_cat, _ = api("/api/v1/profile/skills", "POST",
                        {"name": "坏分类", "level": 10, "category": "magic"})
        check("2c 非法等级（>100）与非法分类被拒",
              st_bad == 400 and st_cat == 400, f"level120→{st_bad} category→{st_cat}")

        # ======================================================== 验收 3 AI 建议不自动生效 ★
        print("\n--- 验收项 3：AI 建议不自动生效（全采集链触发 + 四表快照比对）★" + "-" * 12)
        snap_before = snapshot_db(db_path)

        # 触发点①：新增项目（项目管理）→ project_new 建议
        st_p, b_p = api("/api/v1/projects", "POST",
                        {"name": "CV 小项目", "summary": "演示同步链路",
                         "techStack": ["Python"], "directory": "D:/demo/cv",
                         "startDate": "2026-09-01", "status": "ongoing"})
        proj = data_of((st_p, b_p)) or {}
        check("3b-① 新增项目 → 产生「加入项目经历」建议（不写入）",
              st_p == 200 and proj.get("id"), f"status={st_p} id={proj.get('id')}")
        pid = proj.get("id")

        # 触发点②：项目完成 → project_done + project_done_tl 建议
        st_d, _ = api(f"/api/v1/projects/{pid}", "PUT", {"status": "done"})
        check("3b-② 完成项目 → 产生「项目经历 + 时间线」建议（不写入）",
              st_d == 200, f"status={st_d}")

        # 触发点③：学习目标完成 → goal_done 建议
        st_g, b_g = api("/api/v1/learning/goals", "POST", {"title": "验收目标G7"})
        goal = data_of((st_g, b_g)) or {}
        st_gd, _ = api(f"/api/v1/learning/goals/{goal.get('id')}", "PUT", {"status": "done"})
        check("3b-③ 学习目标完成 → 产生时间线建议（不写入）",
              st_gd == 200, f"status={st_gd}")

        # 触发点④：高频软件 → 技能建议（fixture 种一条 launch_count=50 的 app）
        insert_fixture_row(
            db_path,
            "INSERT INTO apps (name, path, launch_count, created_at, updated_at) "
            "VALUES (?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))",
            ("演示高频软件", "C:/demo/hot.exe", 50),
        )
        st_scan, b_scan = api("/api/v1/profile/suggestions/scan", "POST")
        added = (data_of((st_scan, b_scan)) or {}).get("added")
        check("3b-④ 高频软件扫描 → 产生技能建议（不写入）",
              st_scan == 200 and added == 1, f"added={added}")

        st_pend, b_pend = api("/api/v1/profile/suggestions?status=pending")
        pend = data_of((st_pend, b_pend)) or []
        kinds = sorted({p.get("kind") for p in pend})
        check("3c 待确认队列收到全部 4 类触发（6 条：project×2 + timeline×2 + skill×1…按去重键）",
              len(pend) >= 5 and {"project", "timeline", "skill"} <= set(kinds),
              f"待确认 {len(pend)} 条，类型 {kinds}")

        snap_after = snapshot_db(db_path)
        diff = snapshot_diff(snap_before, snap_after)
        check("3d ★ 触发前后档案四表快照逐行一致（AI/系统未写任何档案数据）",
              diff == "", diff or "快照一致")

        # ======================================================== 验收 6 项目同步（独立断言）
        print("\n--- 验收项 6：项目管理 → 档案同步" + "-" * 12)
        titles = [p.get("title", "") for p in pend]
        check("6 完成项目后出现「是否加入档案」建议（验收项 3 的独立验收口径）",
              any("CV 小项目" in t for t in titles),
              f"建议标题示例：{next((t for t in titles if 'CV' in t), '（无）')!r}")

        # ======================================================== 验收 4 确认后生效
        print("\n--- 验收项 4：确认后生效" + "-" * 12)
        proj_sug = next((p for p in pend if p["kind"] == "project" and "CV" in p.get("title", "")), None)
        goal_sug = next((p for p in pend if p["kind"] == "timeline" and p.get("refKey", "").startswith("goal_done")), None)
        st_c1, b_c1 = api("/api/v1/profile/suggestions/confirm", "POST",
                          {"ids": [proj_sug["id"]]})
        st_pl, b_pl = api("/api/v1/profile/projects?confirmedOnly=true")
        entries = data_of((st_pl, b_pl)) or []
        new_entry = next((e for e in entries if e.get("name") == "CV 小项目"), None)
        check("4a 确认「项目」建议 → 档案项目经历出现新条目（confirmed + ai_suggested）",
              st_c1 == 200 and new_entry is not None
              and new_entry.get("confirmed") is True
              and new_entry.get("source") == "ai_suggested",
              f"条目={new_entry is not None} confirmed={(new_entry or {}).get('confirmed')} "
              f"source={(new_entry or {}).get('source')}")

        st_c2, _ = api("/api/v1/profile/suggestions/confirm", "POST",
                       {"ids": [goal_sug["id"]]})
        st_tl, b_tl = api("/api/v1/profile/timeline?confirmedOnly=true")
        events = data_of((st_tl, b_tl)) or []
        check("4b 确认「时间线」建议 → 时间线出现学习里程碑（type=learning）",
              st_c2 == 200 and any(e.get("type") == "learning" and "验收目标G7" in e.get("title", "")
                                   for e in events),
              f"时间线 {len(events)} 条")

        st_dup, _ = api("/api/v1/profile/suggestions/confirm", "POST",
                        {"ids": [proj_sug["id"]]})
        check("4c 重复确认同一条建议被拒（状态机只允许一次）",
              st_dup == 400, f"status={st_dup}")

        # ======================================================== 验收 5 时间线
        print("\n--- 验收项 5：时间线分组排序" + "-" * 12)
        api("/api/v1/profile/timeline", "POST",
            {"eventDate": "2026-01-05", "title": "早的", "type": "cert"})
        api("/api/v1/profile/timeline", "POST",
            {"eventDate": "2026-06-20", "title": "中的", "type": "skill"})
        st_t, b_t = api("/api/v1/profile/timeline?confirmedOnly=true")
        tl = data_of((st_t, b_t)) or []
        dates = [e.get("eventDate") for e in tl]
        check("5 时间线按日期倒序（前端按年月分组的排序依据）",
              dates == sorted(dates, reverse=True) and len(tl) >= 3,
              f"dates={dates}")

        # ======================================================== 验收 7 权限 ★
        print("\n--- 验收项 7：咨询模式读不到档案 ★" + "-" * 12)
        ctx = {"profileSkills": [SECRET_SKILL]}
        lines_c = post_stream(f"http://127.0.0.1:{sc_port}/ai/chat",
                              {"provider": "ollama", "model": "mock",
                               "apiBase": f"http://127.0.0.1:{MOCK_PORT}",
                               "mode": "consult",
                               "context": ctx,
                               "messages": [{"role": "user", "content": "我的技能有哪些？"}]})
        _ = lines_c  # 回答内容不判 —— 判据在 mock 收到的 system 提示词
        lines_w = post_stream(f"http://127.0.0.1:{sc_port}/ai/chat",
                              {"provider": "ollama", "model": "mock",
                               "apiBase": f"http://127.0.0.1:{MOCK_PORT}",
                               "mode": "workspace",
                               "context": ctx,
                               "messages": [{"role": "user", "content": "我的技能有哪些？"}]})
        time.sleep(0.5)  # mock 落盘是同步的，稍等刷盘
        records = []
        if record_path.exists():
            records = [json.loads(l) for l in record_path.read_text(encoding="utf-8").splitlines()
                       if l.strip()]
        sys_prompts = [r.get("system", "") for r in records]
        consult_leak = any(SECRET_SKILL in p for p in sys_prompts[:1])
        workspace_has = len(sys_prompts) > 1 and SECRET_SKILL in sys_prompts[1]
        check("7a consult 模式 + 硬塞档案上下文 → system 提示词不含技能（sidecar 侧闸门）",
              len(sys_prompts) >= 1 and not consult_leak,
              f"记录 {len(sys_prompts)} 条")
        check("7b 对照组：workspace 模式 → system 提示词含技能（证明隔离非'链路断'假通过）",
              workspace_has, f"workspace 注入={'是' if workspace_has else '否'}")

        # ======================================================== 验收 8 导出
        print("\n--- 验收项 8：Markdown 导出" + "-" * 12)
        # fixture：种一条未确认技能（API 面没有"改回未确认"的通路 —— 这是设计）
        insert_fixture_row(
            db_path,
            "INSERT INTO profile_skills (name, level, category, source, confirmed, updated_at) "
            "VALUES (?, 40, 'tool', 'ai_suggested', 0, datetime('now','localtime'))",
            ("未确认技能不应导出",),
        )
        st_e, b_e = api("/api/v1/profile/export/markdown")
        md = (data_of((st_e, b_e)) or {}).get("markdown", "")
        check("8a 导出内容完整（基础信息/技能/项目/时间线 + 隐私告知）",
              st_e == 200 and all(k in md for k in
                                  ["# 个人档案", "白宇", "少废话", "Python", "CV 小项目",
                                   "验收目标G7", "仅含你已确认的档案内容"]),
              f"markdown {len(md)} 字")
        check("8b 未确认条目不出现在导出里（confirmed=0 被过滤）",
              "未确认技能不应导出" not in md, "未确认技能名未出现")

        # ======================================================== 拒绝清单
        print("\n--- 附加：永久拒绝某类建议" + "-" * 12)
        api("/api/v1/profile/suggestions/reject-kind", "POST", {"kind": "timeline"})
        # 再触发一次目标完成 → 不应产生新的 timeline 建议
        st_g2, b_g2 = api("/api/v1/learning/goals", "POST", {"title": "验收目标G7b"})
        goal2 = data_of((st_g2, b_g2)) or {}
        api(f"/api/v1/learning/goals/{goal2.get('id')}", "PUT", {"status": "done"})
        st_p2, b_p2 = api("/api/v1/profile/suggestions?status=pending")
        pend2 = data_of((st_p2, b_p2)) or []
        no_new_tl = not any(p.get("kind") == "timeline" and "G7b" in p.get("title", "")
                            for p in pend2)
        st_cfg, b_cfg = api("/api/v1/config/profile.rejected_kinds")
        cfg_val = data_of((st_cfg, b_cfg))
        check("9 永久拒绝 timeline 类：清 pending + 后续不再产生 + 拒绝清单落库",
              no_new_tl and cfg_val is not None and "timeline" in str(cfg_val),
              f"rejected_kinds={cfg_val!r} 新时间线建议={not no_new_tl}")

        # ======================================================== 接线检查
        print("\n--- 接线检查（调用点检索的机器部分）" + "-" * 12)
        events_src = read_src("core/src/event_bus/events.rs")
        store_src = read_src("ui/src/stores/profile.ts")
        cmd_src = read_src("core/src/api/commands.rs")
        main_src = read_src("core/src/main.rs")
        api_src = read_src("core/src/api/mod.rs")
        ctx_src = read_src("core/src/scheduler/ai_context.rs")
        check("W1 PROFILE_UPDATED 常量已登记（events.rs）",
              "PROFILE_UPDATED" in events_src)
        check("W2 前端订阅 PROFILE_UPDATED（stores/profile.ts）",
              "PROFILE_UPDATED" in store_src and "on(" in store_src)
        check("W3 profile_* command 已注册（main.rs generate_handler）",
              main_src.count("api::commands::profile_") >= 22,
              f"注册 {main_src.count('api::commands::profile_')} 个")
        check("W4 HTTP 路由已挂（api/mod.rs /api/v1/profile）",
              api_src.count("/api/v1/profile") >= 14)
        check("W5 AI 上下文只取 confirmed=1 的技能（ai_context.rs）",
              "confirmed = 1" in ctx_src and "profile_skills" in ctx_src)
        check("W6 建议确认的统一落点（apply_suggestion_confirm 存在且发事件）",
              "apply_suggestion_confirm" in cmd_src and "publish_update" in read_src("core/src/profile/mod.rs"))

    except Exception as exc:  # noqa: BLE001
        print(f"\n[FATAL] 脚本异常：{exc}")
        import traceback

        traceback.print_exc()
        return 1
    finally:
        stop_app(core)
        for p in procs:
            p.terminate()
        if not args.keep:
            time.sleep(0.5)
            shutil.rmtree(data_dir, ignore_errors=True)

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        if not ok:
            print(f"  FAIL  {name}  {detail}")
    print(f"合计 {passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
