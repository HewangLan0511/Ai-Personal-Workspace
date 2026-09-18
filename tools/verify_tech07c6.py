"""TECH-07-C6 验收 —— 恢复语义收敛（方案 1：并存 + 豁免登记 + 三链语义锁死）

目标冻结依据：docs/tech/TECH-07-C6-implementation-checklist.md（方向 B / 方案 1，零产品代码变更）。

S 静态：
  S1 三链互不污染（snapshot/layout/actions/冻结域 零 mode_restore）
  S2 豁免唯一性（modeApi.restore 全 UI 恰好 1 处 = ModeBar.vue；RunView 零 @/api）
  S3 冻结域 hash（纯函数域 + 四 CSS + schema + boundary + ModeBar）
  S4 视觉基线（RunView/ModeBar 零私造 token/动画/硬编码色）
  S5 禁止能力未误开放（FORBIDDEN 8 项全在；ALLOWED 零禁区；adapter 四文件零禁区名）
  S6 RunView 交互状态锁死（C3/C4/C5 按钮与 chip 全集在位）
R 回归（全串行，真实环境项失败重跑一次消抖）：
  c1 16/16 · c2 25/25 · c3 27/27 · c4 25/25+1 Deferred · c5 24/24 · tech02 11/11 · contracts exit 0
D 真实环境（charmap + 真 core + 真 Edge 页面，全部非 mock）：
  D1 快照链（实例还原）：capture → 挪走 → restore → rect 回归
  D2 快照链失败路径：杀软件 → restore → skip missing + 零摆位 + 零启动
  D3 布局链（模板）：杀软件 → layout_apply → skipped_not_running + 零摆位 + 零启动
  D4 模式链（重建）：/mode/restore → 软件真实回归且 pid 变化（唯一启动链证据）
  D5 offline fail-closed：杀 core → 快照/布局恢复均为失败态，无伪成功 chip
  D6 不产生伪事实：UI 投影 ⊆ core 真实窗口

用法：python tools/verify_tech07c6.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import verify_tech02_workspace as base  # noqa: E402
import verify_tech07c2 as c2  # noqa: E402
import verify_tech07c4 as c4  # noqa: E402
import verify_tech07c5 as c5  # noqa: E402

UI = ROOT / "ui"
SRC = UI / "src"
RUNTIME = SRC / "workspace" / "runtime"
RUNVIEW = SRC / "views" / "RunView.vue"
MODEBAR = SRC / "components" / "ModeBar.vue"
SCHEMA = ROOT / "database" / "schema.sql"
TITLE = c4.TITLE

RESULTS: list[tuple[str, object, str]] = []


def check(name: str, passed: bool, detail: str) -> None:
    RESULTS.append((name, bool(passed), detail))
    print(f"{'PASS' if passed else 'FAIL'} {name} — {detail}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


# ================================================================ S 段（静态）

FROZEN = {
    "ui/src/workspace/snapshot.ts": "604fe010e0d3f980",
    "ui/src/styles/tokens.css": "4741eed584a8b589",
    "ui/src/styles/motion-tokens.css": "adee6b0380a7b04d",
    "ui/src/components/ui/primitives.css": "37a8ff2d375f61c4",
    # 2026-09-18 动效对接批次有意更新（121b562804633520 → ee7d92615121cd45 → 07e79a756e1657c1）：
    # ① resync 并入设计稿 Press 反馈规则；② 并入 `.mt-*` 动效规范层（/motion 消费）；
    # ③ 段前新增「壳层折叠动画的连续性补齐」块（④ 为该块同权重失效的更正）。视觉取值本身未改 ——
    # 理由与逐项说明见 verify_tech07c2.py 的 A3b。
    "ui/src/styles/base.css": "07e79a756e1657c1",
    "database/schema.sql": "d95ca49cc3285166",
    # C6 新增基线（零改动证据：本阶段不碰边界与豁免点）
    "ui/src/workspace/runtime/boundary.ts": "19dfb41e2df31ccd",
    "ui/src/components/ModeBar.vue": "eccb9c10727d3d30",
}

FORBIDDEN_CMDS = ("windows_activate", "windows_close", "windows_find", "windows_rect",
                  "mode_restore", "modes_capture_current", "apps_launch", "apps_terminate")


def s1_chain_isolation() -> None:
    snap_rt = strip_comments(read(RUNTIME / "snapshot.ts"))
    layout_rt = strip_comments(read(RUNTIME / "layout.ts"))
    actions_rt = strip_comments(read(RUNTIME / "actions.ts"))
    frozen_snap = strip_comments(read(SRC / "workspace" / "snapshot.ts"))
    check("S1a runtime/snapshot.ts 零 mode_restore / 不 import modeService",
          "mode_restore" not in snap_rt and "modeService" not in snap_rt, "snapshot.ts")
    check("S1b runtime/layout.ts 零 mode_restore / 零 snapshot 持久化键",
          "mode_restore" not in layout_rt
          and "workspace.snapshot.last" not in layout_rt
          and "SNAPSHOT_CONFIG_KEY" not in layout_rt, "layout.ts")
    check("S1c runtime/actions.ts 零 mode_restore", "mode_restore" not in actions_rt, "actions.ts")
    check("S1d 冻结域 snapshot.ts 零 mode_restore（恢复语义不串线）",
          "mode_restore" not in frozen_snap, "workspace/snapshot.ts")


def s2_exemption_unique() -> None:
    """modeApi.restore 调用点全 UI 恰好 1 处（ModeBar 豁免点）；adapter 内零出现。"""
    hits: list[str] = []
    for p in sorted(SRC.rglob("*")):
        if p.suffix not in (".vue", ".ts") or not p.is_file():
            continue
        if p.name == "modeService.ts":
            continue  # 定义处
        if re.search(r"modeApi\.restore\s*\(", read(p)):
            hits.append(str(p.relative_to(SRC)))
    ok = hits == ["components\\ModeBar.vue"] or hits == ["components/ModeBar.vue"]
    check("S2a 豁免唯一性：modeApi.restore 全 UI 恰好 1 处（ModeBar）", ok, str(hits or "无"))
    rv = read(RUNVIEW)
    api_imports = re.findall(r"from '@/api/[\w]+'", rv)
    check("S2b RunView 零 @/api 直连 / 零 mode_restore",
          not api_imports and "mode_restore" not in rv, f"api={api_imports[:2]}")


def s3_frozen_hash() -> None:
    bad = []
    for rel, want in FROZEN.items():
        got = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16]
        if got != want:
            bad.append(f"{rel}: {got} != {want}")
    check("S3 冻结域 + C6 新增基线 hash（boundary/ModeBar 零改动证据）", not bad,
          str(bad or "全部一致"))


def s4_visual_baseline() -> None:
    rv = read(RUNVIEW)
    tokens = re.findall(r"(--[\w-]+)\s*:", rv)
    motion = re.findall(r"@keyframes|animation\s*:|transition\s*:", rv)
    hexes = re.findall(r"#[0-9a-fA-F]{3,8}\b", re.sub(r"/\*.*?\*/", "", rv, flags=re.S))
    extra = [f.name for f in (SRC / "styles").glob("*.css")
             if f.name not in ("base.css", "motion-tokens.css", "tokens.css")]
    check("S4a RunView 零新 token / 零动画 / 零硬编码色 / 无新样式文件", not tokens and not motion and not hexes and not extra,
          f"token={tokens[:3]} motion={motion[:2]} hex={hexes[:2]} extra={extra}")
    mb = read(MODEBAR)
    mb_hex = re.findall(r"#[0-9a-fA-F]{3,8}\b", mb)
    check("S4b ModeBar（豁免点）零硬编码色", not mb_hex, str(mb_hex[:3] or "无"))


def s5_no_capability_leak() -> None:
    code = read(RUNTIME / "boundary.ts")
    allowed = code.split("export const ALLOWED_COMMANDS", 1)[1].split("]", 1)[0]
    forbidden = code.split("export const FORBIDDEN_COMMANDS", 1)[1].split("]", 1)[0]
    ok_f = all(f"'{w}'" in forbidden for w in FORBIDDEN_CMDS)
    check("S5a FORBIDDEN 8 项全部仍在（未误删）", ok_f, "boundary.ts")
    leaked = [w for w in ("windows_activate", "windows_close", "mode_restore",
                          "apps_launch", "modes_capture_current") if f"'{w}'" in allowed]
    check("S5b 白名单零禁区命令（activate/close/mode_restore/launch/capture 未开放）",
          not leaked, str(leaked or "无"))
    adapter_code = "".join(strip_comments(read(RUNTIME / f))
                           for f in ("facts.ts", "actions.ts", "snapshot.ts", "layout.ts"))
    hits = [w for w in FORBIDDEN_CMDS if w in adapter_code]
    check("S5c adapter 四文件（facts/actions/snapshot/layout）零禁区命令名", not hits, str(hits or "无"))
    check("S5d 段位仍为 actuate（未借 C6 变更段位）",
          "ADAPTER_MODE: AdapterMode = 'actuate'" in code, "boundary.ts")


def s6_runview_state_lock() -> None:
    code = read(RUNVIEW)
    need = ("run-layout-save", "run-layout-apply", "run-layout-chip", "run-layout-name-chip",
            "run-snap-save", "run-snap-restore", "run-snap-chip", "run-placement",
            ':disabled="layoutBusy"', ':disabled="snapBusy"')
    missing = [x for x in need if x not in code]
    check("S6 RunView C3/C4/C5 交互状态全集在位（按钮/chip/disabled 绑定）", not missing,
          str(missing or "全集在位"))


# ================================================================ R 段（回归）

def r_regression() -> None:
    import subprocess

    def run_script(script: str, timeout: int = 3600) -> tuple[int, str]:
        p = subprocess.run([sys.executable, str(TOOLS / script)], cwd=ROOT,
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout

    def check_regression(name: str, script: str, judge, timeout: int = 3600) -> None:
        rc, out = run_script(script, timeout)
        ok = judge(rc, out)
        attempt = "首跑"
        if not ok:
            rc, out = run_script(script, timeout)
            ok = judge(rc, out)
            attempt = "重跑"
        if not ok:
            (TOOLS / f"_r6_fail_{script.replace('verify_', '').replace('.py', '')}.log").write_text(
                out, encoding="utf-8")
        check(name, ok, f"{attempt} exit={rc} 判定={'通过' if ok else '不通过'}")

    def sum_ok(rc: int, out: str, expect: str) -> bool:
        sums = re.findall(r"(\d+)/(\d+)\s*通过", out)
        return rc == 0 and bool(sums) and sums[-1][0] == sums[-1][1] == expect

    check_regression("R verify_tech07c.py（C1）", "verify_tech07c.py",
                     lambda rc, out: sum_ok(rc, out, "16"))
    check_regression("R verify_tech07c2.py（C2）", "verify_tech07c2.py",
                     lambda rc, out: sum_ok(rc, out, "25"))
    check_regression("R verify_tech07c3.py（C3）", "verify_tech07c3.py",
                     lambda rc, out: sum_ok(rc, out, "27"))
    check_regression("R verify_tech07c4.py（C4，25/25+1 Deferred）", "verify_tech07c4.py",
                     lambda rc, out: rc == 0 and bool(re.search(r"25/25 通过", out))
                     and "1 项 Deferred" in out)
    check_regression("R verify_tech07c5.py（C5）", "verify_tech07c5.py",
                     lambda rc, out: sum_ok(rc, out, "24"))
    check_regression("R verify_tech02_workspace.py（TECH-02）", "verify_tech02_workspace.py",
                     lambda rc, out: (lambda m: rc == 0 and bool(m) and m.group(1) == m.group(2) == "11")(
                         re.search(r"汇总\s*(\d+)/(\d+)", out)))
    rc, out = run_script("verify_contracts.py", timeout=600)
    check("R verify_contracts.py（契约套件）", rc == 0, f"exit={rc}")


# ================================================================ D 段（真实环境）

def d_run() -> None:
    ready, why = c2.d_real_environment()
    if not ready:
        check("D 真实环境", False, f"NOT RUN — {why}")
        return

    import tempfile
    data_dir = Path(tempfile.mkdtemp(prefix="pw-t7c6-core-"))
    profile = Path(tempfile.mkdtemp(prefix="pw-t7c6-edge-"))
    import subprocess
    subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)
    time.sleep(1.0)
    core_proc = edge = srv = None
    ws = None
    try:
        core_proc = c4.start_core(data_dir)
        port = c2.wait_core_port(data_dir / "workspace.db")
        if not port:
            check("D 真实环境", False, "NOT RUN — core 启动失败")
            return
        c4.ProxyHandler.core_port = port
        c4.http_json(port, "/api/v1/apps", "POST",
                     {"name": "charmap", "path": c4.CHARMAP, "args": "", "icon": None,
                      "type": None, "category": None})
        mode = c4.http_json(port, "/api/v1/modes", "POST",
                            {"name": "C6验证", "description": None, "icon": None,
                             "apps": ["charmap"], "openTargets": [], "layout": None,
                             "aiProfile": None, "autoApply": False, "switchPolicy": "additive"})
        mode_id = (mode.get("data") or {}).get("id")
        c4.http_json(port, f"/api/v1/modes/{mode_id}/apply", "POST")
        win = None
        deadline = time.time() + 30
        while time.time() < deadline and win is None:
            for w in c4.core_windows(port):
                if TITLE in (w.get("title") or ""):
                    win = w
                    break
            time.sleep(0.5)
        if not win:
            check("D 真实环境", False, "NOT RUN — 真实窗口未拉起")
            return
        hwnd, pid_old = win["hwnd"], win["pid"]
        p_orig = dict(win["rect"])
        print(f"[c6] charmap hwnd={hwnd} pid={pid_old} rect={p_orig} port={port}")

        srv = base.QuietServer(("127.0.0.1", base.free_port()), c4.ProxyHandler)
        import threading
        threading.Thread(target=srv.serve_forever, daemon=True).start()
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
            check("D 真实环境", False, "NOT RUN — Edge CDP 连不上")
            return
        ws = base.CDPWebSocket(ws_url)
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{srv.server_address[1]}/run"}, timeout=15)
        base.wait_for(ws, "!!document.querySelector('[data-pw=\"run-stage\"]')", timeout=25)
        base.wait_for(ws, f"[...document.querySelectorAll('.run-win.is-managed .run-win__bar')]"
                          f".some(b => (b.textContent||'').includes('{TITLE}'))", timeout=25)
        print("[c6] UI 归属窗口就绪")

        # ---- D1 快照链（实例还原）：capture → 挪走 → restore → rect 回归
        p_move = {"x": 900, "y": 500, "w": p_orig["w"], "h": p_orig["h"]}
        chip_cap = c4.ui_click_and_wait(ws, '[data-pw="run-snap-save"]', "已保存")
        c4.place_via_core(port, hwnd, p_move)
        time.sleep(2.0)
        chip_res = c4.ui_click_and_wait(ws, '[data-pw="run-snap-restore"]', "已恢复")
        back = c4.wait_rect(port, hwnd, p_orig, tol=14, timeout=20.0)
        check("D1 快照链=实例还原（capture→挪走→restore→rect 回归，零启动）",
              "已保存" in chip_cap and "已恢复" in chip_res and bool(back),
              f"chip={chip_res.strip()[:36]!r} 回归={back}")

        # ---- 布局准备（窗口在位时保存 + 绑定），供 D3 用
        chip_lsave = c5.ui_click_and_wait(ws, '[data-pw="run-layout-save"]', "已保存")
        layout_name = None
        try:
            with sqlite3.connect(f"file:{data_dir / 'workspace.db'}?mode=ro", uri=True) as conn:
                row = conn.execute("SELECT name FROM layouts WHERE name LIKE 'run-C6验证-%' "
                                   "ORDER BY id DESC LIMIT 1").fetchone()
                layout_name = row[0] if row else None
        except sqlite3.Error as e:
            print("[c6] db 读失败：", e)
        bound = False
        if layout_name:
            up = c4.http_json(port, f"/api/v1/modes/{mode_id}", "PUT", {"layout": layout_name})
            bound = (up.get("data") or {}).get("layout") == layout_name

        # ---- D2 快照链失败路径：杀软件 → restore → skip missing + 零启动
        subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)
        time.sleep(3.0)
        before2 = len([w for w in c4.core_windows(port) if TITLE in (w.get("title") or "")])
        chip_miss = c4.ui_click_and_wait(ws, '[data-pw="run-snap-restore"]', "跳过")
        after2 = len([w for w in c4.core_windows(port) if TITLE in (w.get("title") or "")])
        check("D2 快照链失败路径（missing：skip + 零摆位 + 零启动）",
              "跳过" in chip_miss and before2 == after2 == 0,
              f"chip={chip_miss.strip()[:44]!r} 窗口 before={before2} after={after2}")

        # ---- D3 布局链（模板）：杀软件 → layout_apply → skipped_not_running + 零启动
        chip_lay = c5.ui_click_and_wait(ws, '[data-pw="run-layout-apply"]', "跳过", "未运行")
        after3 = len([w for w in c4.core_windows(port) if TITLE in (w.get("title") or "")])
        check("D3 布局链=模板摆位（未运行 skip，零摆位 + 零启动）",
              bound and "跳过" in chip_lay and after3 == 0,
              f"绑定={bound} chip={chip_lay.strip()[:44]!r} 窗口={after3}")

        # ---- D4 模式链（重建）：/mode/restore → 软件真实回归且 pid 变化（唯一启动链）
        # 前提保险：mode.current（"上次使用的模式"）必须已配置 —— 与 ModeBar 恢复按钮的产品前提一致
        c4.http_json(port, "/api/v1/config/mode.current", "PUT", "C6验证")
        c4.http_json(port, "/api/v1/mode/restore", "POST")
        win2 = None
        deadline = time.time() + 40
        while time.time() < deadline and win2 is None:
            for w in c4.core_windows(port):
                if TITLE in (w.get("title") or ""):
                    win2 = w
                    break
            time.sleep(0.8)
        pid_new = win2["pid"] if win2 else None
        check("D4 模式链=重建（restore 真实拉起软件，pid 变化 = 唯一启动链证据）",
              win2 is not None and pid_new != pid_old,
              f"pid_old={pid_old} pid_new={pid_new} hwnd_old={hwnd} hwnd_new={win2['hwnd'] if win2 else None}")
        hwnd = win2["hwnd"] if win2 else hwnd

        # ---- D6 不产生伪事实：UI 投影 ⊆ core 真实窗口
        wins = c4.core_windows(port)
        real_titles = {w.get("title") for w in wins if w.get("title")}
        ui_titles = set(base.ev(
            ws,
            "[...document.querySelectorAll('[data-pw=\"run-stage\"] .run-win')]"
            ".map(el => el.getAttribute('title').replace(' · 非当前模式窗口（只读）','').replace(' · 当前模式',''))",
            timeout=10,
        ) or [])
        forged = {t for t in ui_titles if t not in real_titles
                  and not any(t and (t in rt or rt in t) for rt in real_titles)}
        check("D6 不产生伪事实（UI 投影 ⊆ core 真实窗口）",
              ui_titles <= real_titles or not forged,
              f"ui={len(ui_titles)} core={len(real_titles)} 伪造={sorted(forged) or '无'}")

        # ---- D5 offline fail-closed：杀 core → 快照/布局恢复均失败态，无伪成功
        core_proc.terminate()
        core_proc.wait(timeout=15)
        core_proc = None
        core_dead = False
        try:
            import urllib.request
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2)
        except OSError:
            core_dead = True
        time.sleep(9.0)  # ≥3 个轮询周期 → offline
        chip_off_r = c4.ui_click_and_wait(ws, '[data-pw="run-snap-restore"]', "offline")
        chip_off_l = c5.ui_click_and_wait(ws, '[data-pw="run-layout-apply"]', "未连接")
        check("D5 offline fail-closed（快照/布局恢复均如实失败，无伪成功 chip）",
              core_dead and "offline" in chip_off_r and "未连接" in chip_off_l,
              f"coreDead={core_dead} 快照chip={chip_off_r.strip()[:40]!r} 布局chip={chip_off_l.strip()[:40]!r}")
    finally:
        if ws is not None:
            ws.close()
        if edge is not None:
            edge.terminate()
            try:
                edge.wait(timeout=8)
            except subprocess.TimeoutExpired:
                edge.kill()
        if core_proc is not None:
            core_proc.terminate()
            try:
                core_proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                core_proc.kill()
        subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)
        if srv is not None:
            srv.shutdown()
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


# ================================================================ main

def main() -> int:
    print("=" * 68)
    print("TECH-07-C6 验收（恢复语义收敛：三链锁死 + 豁免登记 + 全量回归）")
    print("=" * 68)
    for fn in (s1_chain_isolation, s2_exemption_unique, s3_frozen_hash,
               s4_visual_baseline, s5_no_capability_leak, s6_runview_state_lock):
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
        check("R 回归", False, "EXCEPTION: " + " | ".join(
            traceback.format_exc().strip().splitlines()[-3:]))
    try:
        d_run()
    except Exception:
        import traceback
        check("D 真实环境", False, "EXCEPTION: " + " | ".join(
            traceback.format_exc().strip().splitlines()[-3:]))

    failed = sum(1 for _, ok, _ in RESULTS if ok is False)
    passed = sum(1 for _, ok, _ in RESULTS if ok is True)
    print("-" * 68)
    print(f"{passed}/{passed + failed} 通过")
    if failed:
        print(f"红灯 {failed} 项 —— C6 验收不通过")
        return 1
    print("C6 验收全绿（三链语义锁死 + 豁免唯一 + 全量回归 + 真实三链区分证据）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
