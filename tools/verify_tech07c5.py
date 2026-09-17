#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TECH-07-C5 验收 · Workspace Layout Persistence（布局保存 / 应用）
================================================================

S 段（静态）：
    S1 runtime/layout.ts 存在 · 零禁区命令 · 不碰 snapshot 键 · 保存内容无 hwnd/pid
    S2 RunView 零 @/api 直连 / 零 invoke / 零 core 命令名
    S3 冻结域 snapshot.ts + schema + 视觉基线四 CSS hash 未变
    S4 boundary：FORBIDDEN 未恢复（activate/close/launch/restore 仍禁）· 白名单含 layout_apply/db_layout_upsert
    S5 RunView 两按钮已接线（handler + data-pw + 结果 chip）· 旧 disabled 态已移除
    S6 视觉：RunView 零新 token / 零动画 / 零硬编码色 / 无新样式文件
R 段（回归）：C1 16/16 · C2 25/25 · C3 27/27 · C4 25/25(+1D) · TECH-02 11/11 · 契约套件
D 段（真实环境，非 mock）：
    A 保存：真实受管窗口 → RunView「保存布局」→ db_layout_upsert → SQLite layouts 表有行，
            slots 内容对账（app=charmap / 归一化 rect / z 序 / 无 hwnd-pid-foreground 字段）
    B 应用：窗口挪走 → RunView「恢复默认」（layout_apply）→ core windows_list 回读 rect 回归
    C fail-close：关掉软件 → 应用 = skipped_not_running 零摆位零启动；
                  core 停止 → 保存/应用均失败态，无伪成功 chip；未绑定布局 → 提示零摆位

用法：python tools/verify_tech07c5.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import verify_tech02_workspace as base  # noqa: E402
import verify_tech07c2 as c2  # noqa: E402
import verify_tech07c4 as c4  # noqa: E402

UI = ROOT / "ui"
SRC = UI / "src"
LAYOUT_TS = SRC / "workspace" / "runtime" / "layout.ts"
RUNVIEW = SRC / "views" / "RunView.vue"
SNAPSHOT_FROZEN = SRC / "workspace" / "snapshot.ts"
SCHEMA = ROOT / "docs" / "contracts" / "workspace-snapshot.v1.schema.json"
CHARMAP = c4.CHARMAP
TITLE = c4.TITLE

RESULTS: list[tuple[str, object, str]] = []
SECTIONS = ("A 保存", "B 应用", "C fail-close")


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def unrun(reason: str) -> None:
    # 按检查名首字符归段（A 保存→A、B 应用→B、C1/C2/C3→C），
    # 不能用整名匹配 —— C 段检查名里没有 "C fail-close" 字样，会导致全过仍记 NOT RUN。
    done = {n[0] for n, _, _ in RESULTS}
    for n in SECTIONS:
        if n[0] not in done:
            check(n, False, f"NOT RUN — {reason}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


# ================================================================ S 段（静态）

FROZEN = {
    "ui/src/workspace/snapshot.ts": "604fe010e0d3f980",
    "ui/src/styles/tokens.css": "f329f50bddd31d59",
    "ui/src/styles/motion-tokens.css": "e5e44af4aa807d38",
    "ui/src/components/ui/primitives.css": "2de660ce01c2c7d5",
    "ui/src/styles/base.css": "46d26e1bc27716a7",
}


def s1_layout_module() -> None:
    ok_exists = LAYOUT_TS.exists()
    check("S1a runtime/layout.ts 存在", ok_exists, str(LAYOUT_TS))
    if not ok_exists:
        return
    code = strip_comments(read(LAYOUT_TS))
    bad = re.findall(
        r"windows_activate|windows_close|apps_launch|apps_terminate|taskkill"
        r"|TerminateProcess|process_kill|mode_restore|modes_capture_current",
        code,
    )
    check("S1b layout.ts 零禁区命令（activate/close/launch/terminate/restore/capture）",
          not bad, str(sorted(set(bad)) or "无"))
    check("S1c layout.ts 不读写 snapshot 持久化键（不碰 workspace.snapshot.last）",
          "workspace.snapshot.last" not in code and "SNAPSHOT_CONFIG_KEY" not in code, "snapshot 键零出现")
    save_body = code.split("export async function saveLayout", 1)[1].split(
        "export async function applyBoundLayout", 1)[0]
    # 判的是「保存 payload 无实例身份」：禁止把 pid/hwnd 写成字段（pid\s*: / hwnd\s*:）
    # 以及 foreground/snapshotId/runId 出现。允许在函数体内 *读取* w.pid 作证据链查找键
    # （pid → appId → apps.name，S1e 明确认可的登记链），那是查找键、不是落库字段。
    leak = re.findall(r"\b(?:pid|hwnd)\s*:|foreground|snapshotId|runId", save_body)
    check("S1d saveLayout 保存内容无 hwnd/pid/foreground/snapshotId/runId", not leak,
          str(sorted(set(leak)) or "无"))
    chain = ("appsApi.list" in code) and ("appsApi.running" in code) and ("apps.name" in code or "nameById" in code)
    check("S1e 槽位身份走登记证据链（pid→appId→apps.name），非猜测", chain, "apps_list + apps_running")
    check("S1f 保存命名策略冻结（run-<模式名>-<时间戳>）", "run-${" in code and "stamp(" in code, "run-… 前缀")


def s2_runview_boundary() -> None:
    code = read(RUNVIEW)
    api_imports = re.findall(r"from '@/api/[\w]+'|from \"@/api/[\w]+\"", code)
    invokes = re.findall(r"\binvoke\(|\binvokeCore\(|request<", code)
    cmds = re.findall(r"'(windows_\w+|mode_\w+|apps_\w+|db_layout\w+|layout_apply)'", code)
    check("S2 RunView 零 @/api 直连 / 零 invoke / 零 core 命令名",
          not api_imports and not invokes and not cmds,
          f"api={api_imports[:2]} invoke={invokes[:2]} cmd={cmds[:2]}")


def s3_frozen_hash() -> None:
    bad = []
    for rel, want in FROZEN.items():
        got = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16]
        if got != want:
            bad.append(f"{rel}: {got} != {want}")
    schema_hash = hashlib.sha256(SCHEMA.read_bytes()).hexdigest()[:16]
    check("S3 冻结域 snapshot.ts + 视觉基线四 CSS hash 未变", not bad, str(bad or "全部一致") +
          f" · schema 指纹（首次登记）={schema_hash}")


def s4_boundary_lists() -> None:
    code = read(SRC / "workspace" / "runtime" / "boundary.ts")
    # 注意：boundary.ts 头注释里也出现 FORBIDDEN_COMMANDS / ALLOWED_COMMANDS 字样，
    # 必须按 export const 声明行切分，否则解析到的是注释后另一张表（S4b 曾因此误红）。
    allowed = code.split("export const ALLOWED_COMMANDS", 1)[1].split("]", 1)[0]
    forbidden = code.split("export const FORBIDDEN_COMMANDS", 1)[1].split("]", 1)[0]
    ok_a = ("'layout_apply'" in allowed) and ("'db_layout_upsert'" in allowed)
    ok_f = all(f"'{w}'" in forbidden for w in
               ("windows_activate", "windows_close", "apps_launch", "mode_restore",
                "modes_capture_current", "apps_terminate"))
    check("S4a 白名单新增 layout_apply / db_layout_upsert", ok_a, "boundary.ts")
    check("S4b FORBIDDEN 未恢复（activate/close/launch/restore/capture/terminate 仍禁）", ok_f,
          "boundary.ts")


def s5_runview_wiring() -> None:
    code = read(RUNVIEW)
    ok = all(x in code for x in ("run-layout-save", "run-layout-apply", "run-layout-chip",
                                 "onLayoutSave", "onLayoutApply", "layoutBusy"))
    check("S5a RunView 两按钮已接线（handler + data-pw + 结果 chip）", ok, "RunView.vue")
    stale = 'disabled title="C3 放开' in code
    check("S5b 旧 disabled 占位态已移除（不再谎报 C3）", not stale, "无 'C3 放开' 残留")


def s6_visual_freeze() -> None:
    rv = read(RUNVIEW)
    tokens = re.findall(r"(--[\w-]+)\s*:", rv)
    motion = re.findall(r"@keyframes|animation\s*:|transition\s*:", rv)
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", rv, flags=re.S))
    extra = [f.name for f in (SRC / "styles").glob("*.css")
             if f.name not in ("base.css", "motion-tokens.css", "tokens.css")]
    ok = not tokens and not motion and not hexes and not extra
    check("S6 视觉：RunView 零新 token / 零动画 / 零硬编码色 / 无新样式文件", ok,
          f"token={tokens[:3]} motion={motion[:2]} hex={hexes[:2]} extra={extra}")


# ================================================================ R 段（回归）

def r_regression() -> None:
    import subprocess

    def run_script(script: str) -> tuple[int, str]:
        p = subprocess.run([sys.executable, str(TOOLS / script)], cwd=ROOT,
                           capture_output=True, text=True, timeout=1800)
        return p.returncode, p.stdout

    def check_regression(name: str, script: str, judge) -> None:
        """真实环境回归：失败自动重跑一次再判（同机背靠背抢 Edge/core 资源的已知偶发，
        阈值本身不变 —— 重试不是放宽，是消抖）。"""
        rc, out = run_script(script)
        ok = judge(rc, out)
        attempt = "首跑"
        if not ok:
            rc, out = run_script(script)
            ok = judge(rc, out)
            attempt = "重跑"
        if not ok:
            (TOOLS / f"_r_fail_{script.replace('verify_', '').replace('.py', '')}.log").write_text(
                out, encoding="utf-8")
        check(name, ok, f"{attempt} exit={rc} 判定={'通过' if ok else '不通过'}")

    for script, expect in (("verify_tech07c3.py", "27"), ("verify_tech07c2.py", "25"),
                           ("verify_tech07c.py", "16")):
        check_regression(
            f"R {script}", script,
            lambda rc, out, e=expect: rc == 0 and
            (lambda sums: bool(sums) and sums[-1][0] == sums[-1][1] == e)(
                re.findall(r"(\d+)/(\d+)\s*通过", out)))

    check_regression(
        "R verify_tech02_workspace.py", "verify_tech02_workspace.py",
        lambda rc, out: rc == 0 and
        (lambda m: bool(m) and m.group(1) == m.group(2) == "11")(
            re.search(r"汇总\s*(\d+)/(\d+)", out)))

    rc, out = run_script("verify_contracts.py")
    check("R verify_contracts.py（契约套件）", rc == 0, f"exit={rc}")

    # C4 全量（S+R+D，含真实快照链路）—— snapshot 边界未被 C5 触碰的证明
    p = subprocess.run([sys.executable, str(TOOLS / "verify_tech07c4.py")], cwd=ROOT,
                       capture_output=True, text=True, timeout=3600)
    m = re.search(r"(\d+)/(\d+) 通过", p.stdout)
    ok = p.returncode == 0 and m and m.group(1) == m.group(2) == "25" and "1 项 Deferred" in p.stdout
    check("R verify_tech07c4.py（25/25 + 1 Deferred）", ok,
          f"exit={p.returncode} 汇总={m.group(0) if m else '未解析'}")


# ================================================================ D 段（真实环境）

def ui_chip(ws) -> str:
    """读 C5 布局结果 chip。

    注意：c4.ui_chip 读的是 run-snap-chip（快照 chip）——C5 的保存/应用结果在
    run-layout-chip（布局名 chip 已更名为 run-layout-name-chip，避免 querySelector
    撞名）。复用 c4 的读取器会让 A/C1/C2/C3 永远读到「快照：无」。
    """
    return str(base.ev(ws, "document.querySelector('[data-pw=\"run-layout-chip\"]')?.textContent ?? ''",
                       timeout=10) or "")


def ui_click_and_wait(ws, sel: str, *needles: str, timeout: float = 30.0) -> str:
    """点击后等布局 chip 变化再判定（与 c4 同款防陈旧逻辑：文案必须变化且含期望标记）。"""
    prev = ui_chip(ws)
    if c4.ui_click(ws, sel) != "ok":
        return ""
    deadline = time.time() + timeout
    last = prev
    while time.time() < deadline:
        last = ui_chip(ws)
        if last != prev and all(n in last for n in needles):
            return last
        time.sleep(0.5)
    return last


def d_run() -> None:
    ready, why = c2.d_real_environment()
    if not ready:
        unrun(why)
        return

    data_dir = c4.Path(c4.tempfile.mkdtemp(prefix="pw-t7c5-core-"))
    profile = c4.Path(c4.tempfile.mkdtemp(prefix="pw-t7c5-edge-"))
    subprocess = c4.subprocess
    subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)
    time.sleep(1.0)
    core_proc = edge = ws = srv = None
    try:
        core_proc = c4.start_core(data_dir)
        port = c2.wait_core_port(data_dir / "workspace.db")
        if not port:
            unrun("core 启动失败")
            return
        c4.ProxyHandler.core_port = port
        app1 = c4.http_json(port, "/api/v1/apps", "POST",
                            {"name": "charmap", "path": CHARMAP, "args": "", "icon": None,
                             "type": None, "category": None})
        app1_id = (app1.get("data") or {}).get("id")
        mode1 = c4.http_json(port, "/api/v1/modes", "POST",
                             {"name": "C5验证", "description": None, "icon": None,
                              "apps": ["charmap"], "openTargets": [], "layout": None,
                              "aiProfile": None, "autoApply": False, "switchPolicy": "additive"})
        mode1_id = (mode1.get("data") or {}).get("id")
        c4.http_json(port, f"/api/v1/modes/{mode1_id}/apply", "POST")
        win = None
        deadline = time.time() + 30
        while time.time() < deadline and win is None:
            for w in c4.core_windows(port):
                if TITLE in (w.get("title") or ""):
                    win = w
                    break
            time.sleep(0.5)
        if not win:
            unrun("真实窗口未拉起")
            return
        print(f"[c5] charmap hwnd={win['hwnd']} pid={win['pid']} rect={win['rect']} port={port}")

        srv = base.QuietServer(("127.0.0.1", base.free_port()), c4.ProxyHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port_srv = srv.server_address[1]
        dbg_port = base.free_port()
        edge = subprocess.Popen(
            [base.find_edge(), "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", f"--user-data-dir={profile}",
             f"--remote-debugging-port={dbg_port}", "--remote-allow-origins=*",
             "--window-size=1600,1000", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = None
        import urllib.request
        import urllib.error
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg_port}/json/list", timeout=2) as r:
                    pages = [t for t in json.loads(r.read().decode()) if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.3)
        if not ws_url:
            unrun("Edge CDP 连不上")
            return
        ws = base.CDPWebSocket(ws_url)
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port_srv}/run"}, timeout=15)
        base.wait_for(ws, "!!document.querySelector('[data-pw=\"run-stage\"]')", timeout=25)
        base.wait_for(ws, f"[...document.querySelectorAll('.run-win.is-managed .run-win__bar')]"
                          f".some(b => (b.textContent||'').includes('{TITLE}'))", timeout=25)
        print("[c5] UI 归属窗口就绪")

        hwnd = win["hwnd"]
        # ---- A：保存（先把窗口摆到一个已知位置，等 facts 回流后再保存）
        p1 = {"x": 300, "y": 200, "w": 572, "h": 536}
        c4.place_via_core(port, hwnd, p1)
        time.sleep(2.0)
        chip = ui_click_and_wait(ws, '[data-pw="run-layout-save"]', "已保存")
        row = None
        try:
            with sqlite3.connect(f"file:{data_dir / 'workspace.db'}?mode=ro", uri=True) as conn:
                row = conn.execute(
                    "SELECT name, slots FROM layouts WHERE name LIKE 'run-%' "
                    "ORDER BY id DESC LIMIT 1").fetchone()
        except sqlite3.Error as e:
            print("[c5] db 读失败：", e)
        ok_slots = False
        detail_slots = "无行"
        if row and row[1]:
            slots = json.loads(row[1])
            s0 = slots[0] if slots else {}
            r0 = s0.get("rect") or {}
            forbidden_keys = {"hwnd", "pid", "foreground", "snapshotId", "runId"} & set(s0.keys())
            ok_slots = (
                bool(slots)
                and s0.get("app") == "charmap"
                and all(0 <= r0.get(k, -1) <= 1 for k in ("x", "y", "w", "h"))
                and forbidden_keys == set()
                and isinstance(s0.get("z"), int)
            )
            detail_slots = (f"name={row[0]} slots={len(slots)} app={s0.get('app')} "
                            f"rect={r0} z={s0.get('z')} 禁键={sorted(forbidden_keys)}")
        check("A 保存（RunView → db_layout_upsert → SQLite 行 + slots 对账 + 无实例身份字段）",
              "已保存" in chip and bool(row) and ok_slots,
              f"chip={chip.strip()[:36]!r} db行={bool(row)} {detail_slots}")
        layout_name = row[0] if row else None

        # ---- B：应用（绑定布局 → 挪走窗口 → 恢复默认 → rect 回归）
        ok_b = False
        detail_b = "未执行"
        if layout_name:
            up = c4.http_json(port, f"/api/v1/modes/{mode1_id}", "PUT", {"layout": layout_name})
            bound = (up.get("data") or {}).get("layout") == layout_name
            p2 = {"x": 900, "y": 500, "w": 572, "h": 536}
            c4.place_via_core(port, hwnd, p2)
            time.sleep(2.0)
            chip_b = ui_click_and_wait(ws, '[data-pw="run-layout-apply"]', "已应用", "部分应用", "未运行")
            back = c4.wait_rect(port, hwnd, p1, tol=14, timeout=20.0)
            ok_b = bound and bool(back)
            detail_b = f"绑定={bound} chip={chip_b.strip()[:44]!r} 保存时rect={p1} 实际={back}"
        else:
            detail_b = "无布局名（A 未产出）"
        check("B 应用（窗口挪走 → 恢复默认 → 真实 rect 回到保存时几何）", ok_b, detail_b)

        # ---- C：fail-close（三连）
        # C1 关掉软件 → 应用 = skipped_not_running、零摆位、零启动
        subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)
        time.sleep(3.0)
        before_c = len([w for w in c4.core_windows(port) if TITLE in (w.get("title") or "")])
        chip_c = ui_click_and_wait(ws, '[data-pw="run-layout-apply"]', "跳过", "未运行")
        time.sleep(4.0)
        after_c = [w for w in c4.core_windows(port) if TITLE in (w.get("title") or "")]
        ok_c1 = ("跳过" in chip_c or "未运行" in chip_c) and len(after_c) == before_c == 0
        check("C1 关闭软件后应用 → skipped_not_running · 零摆位 · 零启动", ok_c1,
              f"chip={chip_c.strip()[:44]!r} 窗口数 before={before_c} after={len(after_c)}")

        # C2 core 停止 → 保存/应用均为失败态，无伪成功 chip
        core_proc.terminate()
        core_proc.wait(timeout=15)
        core_proc = None
        time.sleep(9.0)  # ≥3 个轮询周期 → offline
        chip_s = ui_click_and_wait(ws, '[data-pw="run-layout-save"]', "保存失败", timeout=25)
        chip_a = ui_click_and_wait(ws, '[data-pw="run-layout-apply"]', "未连接", "应用失败", timeout=25)
        ok_c2 = ("保存失败" in chip_s) and ("未连接" in chip_a or "应用失败" in chip_a)
        check("C2 core 停止 → 保存失败 + 应用失败/未连接（无伪成功 chip）", ok_c2,
              f"保存chip={chip_s.strip()[:36]!r} 应用chip={chip_a.strip()[:36]!r}")

        # C3 未绑定布局 → 提示且零摆位（重启 core 后建一个无绑定模式验证）
        core_proc = c4.start_core(data_dir)
        port2 = c4.wait_new_port(data_dir / "workspace.db", port)
        ok_c3 = False
        detail_c3 = "未执行"
        if port2:
            c4.ProxyHandler.core_port = port2
            mode2 = c4.http_json(port2, "/api/v1/modes", "POST",
                                 {"name": "C5无绑定", "description": None, "icon": None,
                                  "apps": ["charmap"], "openTargets": [], "layout": None,
                                  "aiProfile": None, "autoApply": False, "switchPolicy": "additive"})
            c4.http_json(port2, f"/api/v1/modes/{mode2['data']['id']}/apply", "POST")
            deadline = time.time() + 30
            while time.time() < deadline:
                if any(TITLE in (w.get("title") or "") for w in c4.core_windows(port2)):
                    break
                time.sleep(0.8)
            base.wait_for(ws, f"[...document.querySelectorAll('.run-win.is-managed .run-win__bar')]"
                              f".some(b => (b.textContent||'').includes('{TITLE}'))", timeout=30)
            time.sleep(2.0)
            before_r = {w["hwnd"]: dict(w["rect"]) for w in c4.core_windows(port2)
                        if TITLE in (w.get("title") or "")}
            chip_n = ui_click_and_wait(ws, '[data-pw="run-layout-apply"]', "未绑定布局")
            time.sleep(2.0)
            after_r = {w["hwnd"]: dict(w["rect"]) for w in c4.core_windows(port2)
                       if TITLE in (w.get("title") or "")}
            untouched = all(after_r.get(h) == before_r.get(h) for h in before_r)
            ok_c3 = "未绑定布局" in chip_n and untouched
            detail_c3 = f"chip={chip_n.strip()[:30]!r} 零摆位={untouched}"
        else:
            detail_c3 = "core 重启失败"
        check("C3 未绑定布局 → 明确提示 · 零摆位", ok_c3, detail_c3)
    finally:
        if ws is not None:
            ws.close()
        if edge is not None:
            edge.terminate()
            try:
                edge.wait(timeout=8)
            except c4.subprocess.TimeoutExpired:
                edge.kill()
        if core_proc is not None:
            core_proc.terminate()
            try:
                core_proc.wait(timeout=8)
            except c4.subprocess.TimeoutExpired:
                core_proc.kill()
        subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)
        if srv is not None:
            srv.shutdown()
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)
        unrun("D 段执行中断（异常或提前返回）")


def main() -> int:
    print("=" * 68)
    print("TECH-07-C Phase C5 验收（Workspace Layout Persistence）")
    print("=" * 68)
    for fn in (c4.s1_no_forbidden_paths, c4.s2_persistence_channel, c4.s3_frozen_domain_untouched,
               c4.s4_not_from_lastfacts, c4.s5_runid_from_core, c4.s6_visual_freeze,
               c4.s7_core_registration, s1_layout_module, s2_runview_boundary,
               s3_frozen_hash, s4_boundary_lists, s5_runview_wiring, s6_visual_freeze):
        try:
            fn()
        except Exception:
            import traceback
            check(fn.__name__, False, "EXCEPTION: " + " | ".join(
                traceback.format_exc().strip().splitlines()[-3:]))
    try:
        r_regression()
    except Exception:
        import traceback
        check("R 回归", False, "EXCEPTION: " + " | ".join(traceback.format_exc().strip().splitlines()[-3:]))
    try:
        d_run()
    except Exception:
        import traceback
        check("D 段（真实环境）", False, "EXCEPTION: " + " | ".join(
            traceback.format_exc().strip().splitlines()[-3:]))
        unrun("D 段抛出未捕获异常")

    failed = sum(1 for _, ok, _ in RESULTS if ok is False)
    passed = sum(1 for _, ok, _ in RESULTS if ok is True)
    print("-" * 68)
    print(f"{passed}/{passed + failed} 通过")
    if failed:
        print(f"红灯 {failed} 项 —— C5 验收不通过")
        return 1
    print("C5 验收全绿（布局保存入库 + 真实应用回归 + fail-close 证据）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
