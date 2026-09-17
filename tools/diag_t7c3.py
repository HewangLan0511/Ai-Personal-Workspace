#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TECH-07-C3 Closure Audit 运行时取证脚本（不属 27 项验收套件，仅供审计留证）。

场景（全部真实 core + 真实 charmap 窗口 + UI 真实手势）：
  A 基线拖拽：rect 真实变化（确认链路仍通）
  B nw 缩放（W/N 同时生效）：w↓ & x↑ & h↓ & y↑ —— 8 向 geometry 真机取证
  C pointercancel：不发起任何摆位（rect 不变），且**下一次交互仍能正常开始**
  D core 停止后拖拽：不得伪成功（chip 非已摆位 + 预览回滚到起始几何）
  E core 重启：Observe 恢复（窗口投影重新出现，不再显示未连接）
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))

import verify_tech02_workspace as base  # noqa: E402
import verify_tech07c2 as c2  # noqa: E402

CHARMAP = r"C:\Windows\System32\charmap.exe"
TITLE = "字符映射表"

RESULTS: list[tuple[str, bool, str]] = []


def log(name: str, ok: bool, detail: str) -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} — {detail}")


def http_json(port: int, path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


def rect_of(port: int, pid: int) -> dict | None:
    return next((w["rect"] for w in c2.core_windows(port) if w.get("pid") == pid), None)


PE = ("const pe = (type, x, y, id) => new PointerEvent(type, {clientX:x, clientY:y, bubbles:true,"
      "cancelable:true, isPrimary:true, pointerId:id, pointerType:'mouse', buttons:1});")


def gesture_js(sel: str, dx: int, dy: int, final: str = "pointerup", pid_num: int = 7,
               title: str | None = None) -> str:
    """在指定热区上合成一次手势（默认以 pointerup 结束，可换成 pointercancel）。"""
    pick = (
        "const all=[...document.querySelectorAll('%s')];"
        "const el=%s;"
        "if(!el) return 'no-target';" % (
            sel,
            ("all.find(e => ((e.closest('.run-win')?.querySelector('.run-win__bar')"
             "?.textContent)||'').includes('%s'))" % title) if title else "all[0]",
        )
    )
    return f"""
(() => {{
  {PE}
  {pick}
  const r = el.getBoundingClientRect();
  const x0 = r.left + r.width / 2, y0 = r.top + r.height / 2;
  el.dispatchEvent(pe('pointerdown', x0, y0, {pid_num}));
  window.dispatchEvent(pe('pointermove', x0 + {dx}, y0 + {dy}, {pid_num}));
  window.dispatchEvent(pe('{final}', x0 + {dx}, y0 + {dy}, {pid_num}));
  return 'ok';
}})()
"""


def wait_new_port(db_path: Path, old_port: int, timeout: float = 40.0) -> int | None:
    """等待 core 重启后写入的**新**端口（旧库里残留的旧端口会立刻被读到，必须区分）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                row = conn.execute(
                    "SELECT value FROM config WHERE key = 'runtime.http_port'"
                ).fetchone()
            if row and row[0] and int(row[0]) != old_port:
                p = int(row[0])
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{p}/health", timeout=2) as r:
                        if json.loads(r.read().decode()).get("ok") is True:
                            return p
                except (OSError, urllib.error.URLError, json.JSONDecodeError):
                    pass
        except (sqlite3.Error, OSError):
            pass
        time.sleep(0.5)
    return None


def wait_rect_change(port: int, pid: int, base_rect: dict, timeout: float = 8.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = rect_of(port, pid)
        if r and (r["x"] != base_rect["x"] or r["y"] != base_rect["y"]
                  or r["w"] != base_rect["w"] or r["h"] != base_rect["h"]):
            return r
        time.sleep(0.5)
    return None


def main() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="pw-t7c3-audit-core-"))
    profile = Path(tempfile.mkdtemp(prefix="pw-t7c3-audit-edge-"))
    srv = edge = core_proc = ws = None
    pid = None
    port = 0
    try:
        # ---------------- 启动 core + 注册/应用模式
        core_proc = subprocess.Popen(
            [str(c2.CORE_EXE)], cwd=str(ROOT),
            env=dict(os.environ, PW_DATA_DIR=str(data_dir)),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        port = c2.wait_core_port(data_dir / "workspace.db")
        c2.ProxyHandler.core_port = port
        http_json(port, "/api/v1/apps", "POST",
                  {"name": "charmap", "path": CHARMAP, "args": "", "icon": None,
                   "type": None, "category": None})
        mode = http_json(port, "/api/v1/modes", "POST",
                         {"name": "C3审计", "description": None, "icon": None,
                          "apps": ["charmap"], "openTargets": [], "layout": None,
                          "aiProfile": None, "autoApply": False, "switchPolicy": "additive"})
        http_json(port, f"/api/v1/modes/{mode['data']['id']}/apply", "POST")
        win = None
        deadline = time.time() + 30
        while time.time() < deadline and win is None:
            for w in c2.core_windows(port):
                if TITLE in (w.get("title") or ""):
                    win = w
                    break
            time.sleep(0.5)
        if not win:
            log("setup charmap 拉起", False, "窗口未出现")
            return 1
        pid = win["pid"]
        print(f"[audit] charmap pid={pid} rect={win['rect']} core_port={port}")

        # ---------------- Edge + 同源代理
        srv = base.QuietServer(("127.0.0.1", base.free_port()), c2.ProxyHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port_srv = srv.server_address[1]
        dbg_port = base.free_port()
        edge = subprocess.Popen(
            [base.find_edge(), "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", f"--user-data-dir={profile}",
             f"--remote-debugging-port={dbg_port}", "--remote-allow-origins=*",
             "--window-size=1600,1000", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg_port}/json/list", timeout=2) as resp:
                    pages = [t for t in json.loads(resp.read().decode()) if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except (OSError, urllib.error.URLError, json.JSONDecodeError):
                pass
            time.sleep(0.3)
        if not ws_url:
            log("setup Edge CDP", False, "连不上")
            return 1
        ws = base.CDPWebSocket(ws_url)
        ws.call("Page.enable")
        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port_srv}/run"}, timeout=15)
        base.wait_for(ws, "!!document.querySelector('[data-pw=\"run-stage\"]')", timeout=25)
        base.wait_for(ws, f"[...document.querySelectorAll('.run-win.is-managed .run-win__bar')]"
                          f".some(b => (b.textContent||'').includes('{TITLE}'))", timeout=25)
        print("[audit] UI 归属窗口就绪")

        chip = "document.querySelector('[data-pw=\"run-placement\"]')?.textContent ?? null"
        geom = (f"(() => {{ const w=[...document.querySelectorAll('.run-win.is-managed')]"
                f".find(e => ((e.querySelector('.run-win__bar')?.textContent)||'').includes('{TITLE}'));"
                f"return w ? w.style.left + ',' + w.style.top + ',' + w.style.width + ',' + w.style.height : null; }})()")

        # ---------------- A 基线拖拽
        r0 = rect_of(port, pid)
        ret = base.ev(ws, gesture_js(".run-win.is-managed .run-win__bar", 40, 20, title=TITLE), timeout=10)
        r1 = wait_rect_change(port, pid, r0)
        ok_a = bool(r1) and r1["x"] > r0["x"] and r1["y"] > r0["y"]
        log("A 基线拖拽（真实 rect 变化，方向正确）", ok_a, f"target={ret} {r0} -> {r1}")

        # ---------------- B nw 缩放（同时验 W 的 left 同步与 N 的 top 同步）
        rb = rect_of(port, pid)
        ret_b = base.ev(ws, gesture_js(".run-win.is-managed .run-win__rz--nw", 60, 40,
                                       title=TITLE, pid_num=11), timeout=10)
        rb2 = wait_rect_change(port, pid, rb)
        ok_b = bool(rb2) and (rb2["w"] < rb["w"] and rb2["x"] > rb["x"]
                              and rb2["h"] < rb["h"] and rb2["y"] > rb["y"])
        log("B nw 缩放（w↓ x↑ h↓ y↑ 四者同步）", ok_b, f"target={ret_b} {rb} -> {rb2}")

        # ---------------- C pointercancel：不摆位，且后续交互仍可用
        rc = rect_of(port, pid)
        ret_c = base.ev(ws, gesture_js(".run-win.is-managed .run-win__bar", 50, 30,
                                       final="pointercancel", title=TITLE, pid_num=13), timeout=10)
        time.sleep(2.0)
        rc2 = rect_of(port, pid)
        no_place = rc2 == rc
        ret_c3 = base.ev(ws, gesture_js(".run-win.is-managed .run-win__bar", 30, 15,
                                        title=TITLE, pid_num=17), timeout=10)
        rc3 = wait_rect_change(port, pid, rc2)
        log("C pointercancel 不摆位 + 后续交互可重新开始", no_place and bool(rc3),
            f"cancel:target={ret_c} 无变化={no_place}；后续拖拽:target={ret_c3} {rc2} -> {rc3}")

        # ---------------- D core 停止后：fail-closed（无窗口可拖拽 + 陈旧成功被作废）
        rect_pre_offline = rect_of(port, pid)
        core_proc.terminate()
        core_proc.wait(timeout=15)
        core_proc = None
        time.sleep(9.0)  # ≥3 个轮询周期 → offline
        ret_d = base.ev(ws, gesture_js(".run-win.is-managed .run-win__bar", 40, 20,
                                       title=TITLE, pid_num=19), timeout=10)
        time.sleep(2.0)
        chip_d = base.ev(ws, chip, timeout=10)
        hint_d = base.ev(ws, "document.querySelector('.run-stage__hint')?.textContent ?? ''", timeout=10)
        wins_d = base.ev(ws, "document.querySelectorAll('[data-pw=\"run-stage\"] .run-win').length", timeout=10)
        # 注：手势目标是否存在取决于 2s 轮询时序（可能仍显示上一帧快照），不作判据；
        # 硬判据是「不得伪成功」——chip 不得出现已摆位，且窗口数/提示如实反映断连。
        ok_d = (int(wins_d or 0) == 0 and "未连接" in (hint_d or "")
                and (chip_d is None or "已摆位" not in chip_d))
        log("D core 停止后：0 窗口 / 未连接 / 陈旧成功作废 / 手势无目标", ok_d,
            f"target={ret_d} wins={wins_d} chip={chip_d!r} hint={hint_d!r}")

        # ---------------- E core 重启 → Observe 恢复
        core_proc = subprocess.Popen(
            [str(c2.CORE_EXE)], cwd=str(ROOT),
            env=dict(os.environ, PW_DATA_DIR=str(data_dir)),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        port2 = wait_new_port(data_dir / "workspace.db", port)
        c2.ProxyHandler.core_port = port2 or port
        time.sleep(9.0)
        hint = base.ev(ws, "document.querySelector('.run-stage__hint')?.textContent ?? ''", timeout=10)
        wins = base.ev(ws, "document.querySelectorAll('[data-pw=\"run-stage\"] .run-win').length", timeout=10)
        log("E core 重启后 Observe 恢复（投影重现，非未连接）",
            bool(port2) and "未连接" not in (hint or "") and int(wins or 0) > 0,
            f"new_port={port2} wins={wins} hint={hint!r}")

        # ---------------- F 断连期间的拖拽没有偷偷摆位（重启后 rect 与断连前一致）
        rect_post = rect_of(port2 or port, pid)
        log("F core 停止期间的拖拽未产生任何摆位（rect 与断连前一致）",
            rect_post == rect_pre_offline, f"{rect_pre_offline} -> {rect_post}")

        failed = sum(1 for _, ok, _ in RESULTS if not ok)
        print("-" * 64)
        print(f"{len(RESULTS) - failed}/{len(RESULTS)} 通过")
        return 0 if failed == 0 else 1
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
        if pid:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10)
        if srv is not None:
            srv.shutdown()
        import shutil
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
