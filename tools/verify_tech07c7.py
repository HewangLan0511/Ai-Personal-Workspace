"""TECH-07-C7 验收 —— 交互尾巴收口（C7-A~F）

目标冻结依据：docs/tech/TECH-07-C7-implementation-checklist.md Phase 2 冻结决策 A-F。
变更白名单：runtime/actions.ts（常量 + placeWindow 联合收口）、runtime/index.ts（常量再导出）、
views/RunView.vue（Esc 链 / 预览吸附 / MIN 统一 / 卡片补全）。冻结域零改动（S5 hash 证据）。

S 静态：
  S1 常量单一来源（MIN_NORM/SNAP_NORM 唯一定义于 actions.ts；RunView 零私有魔法数）
  S2 C7-A 联合收口（placeWindow x/y-w/h 联合 clamp + 舍入收口；RunView 单一 placeWindow 调用点）
  S3 C7-C Esc 链（挂/摘对称；handler 只取消、零 placeWindow/adapter 调用）
  S4 C7-D 吸附仅预览（SNAP_NORM 只出现在 previewGeometry；actions.ts 零吸附逻辑）
  S5 冻结域 + 基线 hash 8 项不变（boundary/ModeBar/CSS/schema/snapshot.ts）
  S6 C7-E 卡片补全（winBarText 存在；app: 仅 slots 证据；:title 兼容格式保留；零 drawer/exe 猜测）
R 回归（全串行，失败重跑一次消抖）：
  c1 16/16 · c2 25/25 · c3 27/27 · c4 25/25+1 Deferred · c5 24/24 · c6 27/27 ·
  tech02 11/11 · contracts exit 0
D 真实环境（charmap + 真 core + 真 Edge 页面，全部非 mock）：
  D1 Esc 零摆位：拖拽中按 Esc → core rect 不变（零 windows_place）
  D2 交互恢复：Esc 取消后正常拖拽仍生效（无陈旧交互状态）
  D3 monitor edge snap：拖到左缘吸附带内提交 → rect.x == work_x
  D4a se 越界收口：向右下拉出 1.5 倍 → 整窗仍完整落在工作区内（C5-06 关闭证据）
  D4b nw 越界收口：向左上拉出 2 倍 → 贴齐工作区左上，不越界
  D5 卡片补全：归属卡片 bar = app:<slots 证据名>；非归属窗口 bar 带「只读」

用法：python tools/verify_tech07c7.py
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import verify_tech02_workspace as base  # noqa: E402
import verify_tech07c2 as c2  # noqa: E402
import verify_tech07c3 as c3  # noqa: E402
import verify_tech07c4 as c4  # noqa: E402
import verify_tech07c6 as c6  # noqa: E402

UI = ROOT / "ui"
SRC = UI / "src"
RUNTIME = SRC / "workspace" / "runtime"
RUNVIEW = SRC / "views" / "RunView.vue"
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


def func_body(code: str, name: str) -> str:
    """粗粒度函数体截取：从 `function <name>` 到下一个顶层 `function `/`const `。"""
    m = re.search(rf"function {name}\(", code)
    if not m:
        return ""
    rest = code[m.start():]
    nxt = re.search(r"\n(?:function |const |async function )", rest[1:])
    return rest[: nxt.start() + 1] if nxt else rest


# ================================================================ S 段（静态）

def s1_const_single_source() -> None:
    acts = strip_comments(read(RUNTIME / "actions.ts"))
    idx = strip_comments(read(RUNTIME / "index.ts"))
    rv = strip_comments(read(RUNVIEW))
    check("S1a MIN_NORM/SNAP_NORM 唯一定义于 actions.ts（0.02）",
          "export const MIN_NORM = 0.02" in acts and "export const SNAP_NORM = 0.02" in acts
          and acts.count("SNAP_NORM") == 1, "actions.ts")
    check("S1b index.ts 再导出两常量（RunView 不触 actions 内部）",
          "MIN_NORM" in idx and "SNAP_NORM" in idx and "from './actions'" in idx, "index.ts")
    check("S1c RunView 从 adapter 导入常量、零私有魔法数（0.04 已消灭）",
          "import { MIN_NORM, SNAP_NORM, workspaceAdapter }" in rv
          and "const MIN" not in rv and "0.04" not in rv, "RunView.vue")


def s2_joint_clamp() -> None:
    acts = strip_comments(read(RUNTIME / "actions.ts"))
    ok = ("clamp(clamp(intent.x, 0, 1), 0, 1 - w)" in acts
          and "clamp(clamp(intent.y, 0, 1), 0, 1 - h)" in acts
          and "xPx = Math.min(xPx, wa.x + wa.w - wPx)" in acts
          and "yPx = Math.min(yPx, wa.y + wa.h - hPx)" in acts)
    check("S2a placeWindow 联合校验（x∈[0,1-w] / y∈[0,1-h] + 舍入收口，C5-06 关闭）",
          ok, "actions.ts placeWindow")
    rv = strip_comments(read(RUNVIEW))
    n_call = rv.count("placeWindow(")
    check("S2b RunView 恰好 1 处 placeWindow 调用点（commit 边界唯一不变）", n_call == 1,
          f"调用点={n_call}")


def s3_esc_chain() -> None:
    rv = read(RUNVIEW)
    code = strip_comments(rv)
    ok_sym = ("window.addEventListener('keydown', onInteractKey)" in code
              and "window.removeEventListener('keydown', onInteractKey)" in code)
    check("S3a Esc 监听挂/摘对称（与 pointer 监听同进同出）", ok_sym, "RunView.vue")
    body = func_body(code, "onInteractKey")
    ok_h = bool(body) and "cancelInteraction()" in body and "placeWindow" not in body \
        and "workspaceAdapter" not in body and "windows_place" not in body
    check("S3b Esc handler 仅取消（零 placeWindow / 零 adapter / 零 core 请求）", ok_h,
          f"body={body[:80]!r}")


def s4_snap_preview_only() -> None:
    rv = strip_comments(read(RUNVIEW))
    body = func_body(rv, "previewGeometry")
    # 使用点 = SNAP_NORM 出现行，排除 import 行（导入不算使用）
    uses = [ln for ln in rv.splitlines() if "SNAP_NORM" in ln
            and not ln.strip().startswith("import")]
    in_preview = all(ln in body for ln in uses)
    check("S4a SNAP_NORM 只在 previewGeometry 内使用（吸附不进 commit）",
          in_preview and len(uses) >= 4,
          f"使用点={len(uses)} 全部位于 previewGeometry={in_preview}")
    acts = strip_comments(read(RUNTIME / "actions.ts"))
    check("S4b actions.ts 零吸附逻辑（commit 语义不变：单次 windows_place）",
          "SNAP_NORM" not in acts.replace("export const SNAP_NORM = 0.02", ""), "actions.ts")


def s5_frozen_hash() -> None:
    bad = []
    for rel, want in c6.FROZEN.items():
        got = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:16]
        if got != want:
            bad.append(f"{rel}: {got} != {want}")
    check("S5 冻结域 + 基线 hash 8 项不变（C7 零冻结域改动证据）", not bad,
          str(bad or "全部一致"))


def s6_card_completion() -> None:
    rv = read(RUNVIEW)
    code = strip_comments(rv)
    body = func_body(code, "winBarText")
    ok = bool(body) and "app:${p.app}" in body and "只读" in body and "最大化" in body
    check("S6a winBarText：标题前缀 + app:<slots证据> + 状态 + 只读标识", ok, "RunView.vue")
    ok_title = ("非当前模式窗口（只读）" in rv and "当前模式（可拖拽/缩放）" in rv)
    check("S6b 卡片 :title 兼容格式保留（c2/c6 回归断言依赖）", ok_title, ":title 属性")
    guesses = re.findall(r"\.exe\b|toLowerCase\(\)\.contains", code)
    no_drawer = "drawer" not in code.lower()
    check("S6c 零 exe 猜测 / 零 drawer（口径 a：只补全现有卡片）",
          not guesses and no_drawer, f"guess={guesses or '无'} drawer={not no_drawer}")


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
            (TOOLS / f"_r7_fail_{script.replace('verify_', '').replace('.py', '')}.log").write_text(
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
    check_regression("R verify_tech07c6.py（C6）", "verify_tech07c6.py",
                     lambda rc, out: sum_ok(rc, out, "27"))
    check_regression("R verify_tech02_workspace.py（TECH-02）", "verify_tech02_workspace.py",
                     lambda rc, out: (lambda m: rc == 0 and bool(m) and m.group(1) == m.group(2) == "11")(
                         re.search(r"汇总\s*(\d+)/(\d+)", out)))
    rc, out = run_script("verify_contracts.py", timeout=600)
    check("R verify_contracts.py（契约套件）", rc == 0, f"exit={rc}")


# ================================================================ D 段（真实环境）

def charmap_win(port: int) -> dict | None:
    return next((w for w in c4.core_windows(port) if TITLE in (w.get("title") or "")), None)


def wait_rect(port: int, cond, timeout: float = 10.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        w = charmap_win(port)
        if w and cond(w["rect"]):
            return w
        time.sleep(0.5)
    return None


def drag_js(dx: float, dy: float, esc: bool = False, handle: str = "") -> str:
    """拖拽/缩放合成事件。esc=True 时在提交前注入 keydown(Escape)（C7-C 路径）。"""
    sel = f".run-win__rz--{handle}" if handle else ".run-win__bar"
    find = ("[...document.querySelectorAll('.run-win.is-managed " + sel + "')]"
            ".find(b => (b.textContent || '').includes('" + TITLE + "'))"
            if not handle else
            "[...document.querySelectorAll('.run-win.is-managed')]"
            ".map(w => ({w, h: w.querySelector('" + sel + "')}))"
            ".find(x => x.h && (x.w.querySelector('.run-win__bar')?.textContent || '').includes('" + TITLE + "'))"
            "?.h")
    return """
(() => {
  const t = %s;
  if (!t) return 'no-target';
  const r = t.getBoundingClientRect();
  const x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
  const pe = (type, x, y) => new PointerEvent(type, {clientX:x, clientY:y, bubbles:true,
    cancelable:true, isPrimary:true, pointerId:9, pointerType:'mouse', buttons:1});
  t.dispatchEvent(pe('pointerdown', x0, y0));
  window.dispatchEvent(pe('pointermove', x0 + %f, y0 + %f));
  %s
  window.dispatchEvent(pe('pointerup', x0 + %f, y0 + %f));
  return 'ok';
})()
""" % (find, dx, dy,
       "window.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true, cancelable:true}));"
       if esc else "",
       dx, dy)


def d_run() -> None:
    ready, why = c2.d_real_environment()
    if not ready:
        check("D 真实环境", False, f"NOT RUN — {why}")
        return

    import subprocess
    import tempfile
    data_dir = Path(tempfile.mkdtemp(prefix="pw-t7c7-core-"))
    profile = Path(tempfile.mkdtemp(prefix="pw-t7c7-edge-"))
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
                            {"name": "C7验证", "description": None, "icon": None,
                             "apps": ["charmap"], "openTargets": [], "layout": None,
                             "aiProfile": None, "autoApply": False, "switchPolicy": "additive"})
        mode_id = (mode.get("data") or {}).get("id")
        c4.http_json(port, f"/api/v1/modes/{mode_id}/apply", "POST")
        win = None
        deadline = time.time() + 30
        while time.time() < deadline and win is None:
            win = charmap_win(port)
            time.sleep(0.5)
        if not win:
            check("D 真实环境", False, "NOT RUN — 真实窗口未拉起")
            return
        hwnd_unused = win["hwnd"]
        print(f"[c7] charmap hwnd={win['hwnd']} pid={win['pid']} rect={win['rect']} port={port}")

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
        print("[c7] UI 归属窗口就绪")

        stage_w = base.ev(ws, "document.querySelector('[data-pw=\"run-stage\"]').getBoundingClientRect().width", timeout=10)
        stage_h = base.ev(ws, "document.querySelector('[data-pw=\"run-stage\"]').getBoundingClientRect().height", timeout=10)
        mon = c3.core_primary_workarea(port)
        work = mon or {"work_x": 0, "work_y": 0, "work_w": 0, "work_h": 0}

        # ---- D1：Esc 零摆位（C7-C 硬约束：不调用 windows_place）
        before = charmap_win(port)["rect"]
        ret = base.ev(ws, drag_js(60, 40, esc=True), timeout=10)
        moved = wait_rect(port, lambda r: r["x"] != before["x"] or r["y"] != before["y"], timeout=6)
        after1 = (moved["rect"]["x"], moved["rect"]["y"]) if moved else "未变"
        check("D1 Esc 零摆位（拖拽中按 Esc → core rect 不变）",
              ret == "ok" and not moved,
              f"target={ret} before=({before['x']},{before['y']}) after={after1}")

        # ---- D2：交互恢复（Esc 后正常拖拽仍生效 —— 无陈旧交互状态）
        ret2 = base.ev(ws, drag_js(80, 50), timeout=10)
        rec = wait_rect(port, lambda r: r["x"] > before["x"] + 20 and r["y"] > before["y"] + 10, timeout=10)
        check("D2 交互恢复（Esc 取消后正常拖拽仍提交）", ret2 == "ok" and bool(rec),
              f"target={ret2} after={tuple(rec['rect'][k] for k in 'xy') if rec else '未动'}")

        # ---- D3：monitor edge snap（预览吸附带 → 提交 rect.x == work_x）
        cur = charmap_win(port)["rect"]
        sx = (cur["x"] - work["work_x"]) / work["work_w"]
        target = 0.015  # 落在吸附带（0.02）内但不为 0 —— 证明是 snap 而非 clamp 到负值
        dx_px = (target - sx) * stage_w
        ret3 = base.ev(ws, drag_js(dx_px, 0), timeout=10)
        snapped = wait_rect(port, lambda r: abs(r["x"] - work["work_x"]) <= 3, timeout=10)
        check("D3 monitor edge snap（左缘吸附带内提交 → rect.x == work_x）",
              ret3 == "ok" and bool(snapped),
              f"start_x_norm={sx:.4f} dx={dx_px:.1f}px "
              f"after.x={snapped['rect']['x'] if snapped else '?'} work_x={work['work_x']}")

        # ---- D4a：se 越界收口（向右下拉出 1.5 倍 → 整窗完整落在工作区内）
        base_r = charmap_win(port)["rect"]
        ret4 = base.ev(ws, drag_js(stage_w * 1.5, stage_h * 1.2, handle="se"), timeout=10)
        after4 = wait_rect(port, lambda r: r["w"] > base_r["w"], timeout=10)
        inside4 = bool(after4) and (
            after4["rect"]["x"] + after4["rect"]["w"] <= work["work_x"] + work["work_w"] + 3
            and after4["rect"]["y"] + after4["rect"]["h"] <= work["work_y"] + work["work_h"] + 3)
        check("D4a se 越界收口（C5-06 关闭：x+w 恒 ≤ 工作区右缘）",
              ret4 == "ok" and bool(after4) and inside4,
              f"rect={after4['rect'] if after4 else '?'} "
              f"右缘上限={work['work_x'] + work['work_w']} 下缘上限={work['work_y'] + work['work_h']}")

        # ---- D4b：nw 越界收口（向左上拉出 2 倍 → 贴齐左上、不越界）
        ret5 = base.ev(ws, drag_js(-stage_w * 2, -stage_h * 2, handle="nw"), timeout=10)
        after5 = wait_rect(port, lambda r: r["x"] <= work["work_x"] + 3 and r["y"] <= work["work_y"] + 3,
                           timeout=10)
        inside5 = bool(after5) and after5["rect"]["x"] >= work["work_x"] - 3 \
            and after5["rect"]["y"] >= work["work_y"] - 3
        check("D4b nw 越界收口（左上贴齐工作区、整窗在内）",
              ret5 == "ok" and bool(after5) and inside5,
              f"rect={after5['rect'] if after5 else '?'} work=({work['work_x']},{work['work_y']})")

        # ---- D5：卡片补全（app:<slots 证据> / 只读标识）
        bar_txt = base.ev(
            ws,
            "(() => { const bar = [...document.querySelectorAll('.run-win.is-managed .run-win__bar')]"
            ".find(b => (b.textContent || '').includes('" + TITLE + "'));"
            " return bar ? (bar.textContent || '').trim() : 'no-bar'; })()",
            timeout=10,
        )
        managed_ok = isinstance(bar_txt, str) and "app:charmap" in bar_txt and "只读" not in bar_txt
        # 非归属窗口：差集法拉起（charmap 已被模式占用；notepad 优先，Win11 stub 由
        # 差集反查真实 pid 兜底 —— c2 D2 同款模式）
        before_pids = {w.get("pid") for w in c4.core_windows(port)}
        ro_pid = None
        extra = None
        for exe in ("notepad.exe", "winver.exe"):
            extra = subprocess.Popen([exe])
            deadline = time.time() + 12
            while time.time() < deadline and ro_pid is None:
                for w in c4.core_windows(port):
                    if w.get("pid") not in before_pids and w.get("pid") != extra.pid:
                        ro_pid = w["pid"]
                        break
                time.sleep(0.5)
            if ro_pid:
                break
            subprocess.run(["taskkill", "/PID", str(extra.pid), "/F"], capture_output=True, timeout=10)
        ro_ok = False
        if ro_pid:
            deadline = time.time() + 15
            while time.time() < deadline and not ro_ok:
                ro_ok = bool(base.ev(
                    ws,
                    "[...document.querySelectorAll('.run-win:not(.is-managed) .run-win__bar')]"
                    ".some(b => (b.textContent || '').includes('只读'))",
                    timeout=10,
                ))
                time.sleep(0.7)
        subprocess.run(["taskkill", "/PID", str(extra.pid), "/F"], capture_output=True, timeout=10)
        if ro_pid:
            subprocess.run(["taskkill", "/PID", str(ro_pid), "/F"], capture_output=True, timeout=10)
        check("D5 卡片补全（app:<slots证据名> / 非归属窗口带只读标识）",
              managed_ok and ro_ok,
              f"managed_bar={bar_txt!r} ro_pid={ro_pid} ro_marked={ro_ok}")
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        if edge:
            edge.terminate()
            try:
                edge.wait(timeout=10)
            except Exception:
                pass
        if core_proc:
            core_proc.terminate()
            try:
                core_proc.wait(timeout=15)
            except Exception:
                pass
        if srv:
            srv.shutdown()
        subprocess.run(["taskkill", "/IM", "charmap.exe", "/F"], capture_output=True, timeout=10)


# ================================================================ 汇总

def main() -> int:
    s1_const_single_source()
    s2_joint_clamp()
    s3_esc_chain()
    s4_snap_preview_only()
    s5_frozen_hash()
    s6_card_completion()
    s_ok = sum(1 for _, p, _ in RESULTS if p)
    print(f"\n=== S 静态 {s_ok}/{len(RESULTS)} 通过 ===")

    r_start = len(RESULTS)
    r_regression()
    r_ok = sum(1 for _, p, _ in RESULTS[r_start:] if p)
    r_total = len(RESULTS) - r_start
    print(f"=== R 回归 {r_ok}/{r_total} 通过 ===")

    d_start = len(RESULTS)
    d_run()
    d_ok = sum(1 for _, p, _ in RESULTS[d_start:] if p)
    d_total = len(RESULTS) - d_start
    print(f"=== D 真实 {d_ok}/{d_total} 通过 ===")

    total_ok = sum(1 for _, p, _ in RESULTS if p)
    print(f"\n汇总 {total_ok}/{len(RESULTS)} 通过")
    if total_ok < len(RESULTS):
        print("\n未通过项：")
        for name, p, detail in RESULTS:
            if not p:
                print(f"  FAIL {name} — {detail}")
    return 0 if total_ok == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
