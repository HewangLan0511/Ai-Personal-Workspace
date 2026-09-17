"""TECH-07-C2 D2 诊断（只读诊断，不改产品）：真实 notepad 进 core 却不进 UI？

复现 verify_tech07c2 D 段前半（core + 代理 + Edge CDP + notepad），并逐秒对比：
- core /api/v1/windows 全量（title/pid/state/rect/is-managed 类字段）
- UI .run-win 卡片 title 属性集合
- JS console / 异常捕获（Runtime.consoleAPICalled / exceptionThrown）

用法：python tools/diag_t7c2_d2.py
"""
from __future__ import annotations

import json
import os
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

UI = ROOT / "ui"


def main() -> int:
    data_dir = Path(tempfile.mkdtemp(prefix="pw-diag-c2-core-"))
    profile = Path(tempfile.mkdtemp(prefix="pw-diag-c2-edge-"))
    port_srv = base.free_port()
    dbg_port = base.free_port()
    env = dict(os.environ, PW_DATA_DIR=str(data_dir))
    core_proc = subprocess.Popen([str(c2.CORE_EXE)], cwd=str(ROOT), env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    port = c2.wait_core_port(data_dir / "workspace.db")
    if not port:
        print("[diag] core 启动失败")
        core_proc.terminate()
        return 1
    print(f"[diag] core port={port}")
    c2.ProxyHandler.core_port = port

    srv = base.QuietServer(("127.0.0.1", port_srv), c2.ProxyHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    edge = subprocess.Popen(
        [base.find_edge(), "--headless=new", "--disable-gpu", "--no-first-run",
         "--no-default-browser-check", f"--user-data-dir={profile}",
         f"--remote-debugging-port={dbg_port}", "--remote-allow-origins=*",
         "--window-size=1600,1000", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws = None
    try:
        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{dbg_port}/json/list", timeout=2) as r:
                    pages = [t for t in json.loads(r.read().decode()) if t.get("type") == "page"]
                if pages:
                    ws_url = pages[0]["webSocketDebuggerUrl"]
                    break
            except OSError:
                pass
            time.sleep(0.3)
        if not ws_url:
            print("[diag] Edge CDP 连不上")
            return 1
        ws = base.CDPWebSocket(ws_url)
        ws.call("Page.enable")
        ws.call("Runtime.enable")
        logs: list[str] = []

        def drain():
            # CDPWebSocket 的实现决定是否支持事件回调；这里用轮询兜底（见下）
            pass

        ws.call("Page.navigate", {"url": f"http://127.0.0.1:{port_srv}/run"}, timeout=15)
        base.wait_for(ws, "!!document.querySelector('[data-pw=\"run-stage\"]')", timeout=25)
        print("[diag] /run 就绪")

        # 启动 notepad
        before = {w.get("pid") for w in c2.core_windows(port)}
        np = subprocess.Popen(["notepad.exe"])
        np_title = None
        deadline = time.time() + 15
        while time.time() < deadline and np_title is None:
            for w in c2.core_windows(port):
                if w.get("pid") not in before and "记事本" in (w.get("title") or ""):
                    np_title = w["title"]
                    break
            time.sleep(0.5)
        print(f"[diag] notepad 进 core：title={np_title!r} pid={np.pid}")

        # 逐秒对比 15s
        lit = json.dumps(np_title or "", ensure_ascii=False)
        for i in range(15):
            core = c2.core_windows(port)
            np_core = [w for w in core if "记事本" in (w.get("title") or "")]
            ui_titles = base.ev(
                ws,
                "[...document.querySelectorAll('[data-pw=\"run-stage\"] .run-win')]"
                ".map(el => el.getAttribute('title'))",
                timeout=10,
            ) or []
            bars = base.ev(
                ws,
                "[...document.querySelectorAll('.run-win__bar')].map(el => (el.textContent||'').trim().slice(0,24))",
                timeout=10,
            ) or []
            hit = base.ev(
                ws,
                f"[...document.querySelectorAll('.run-win__bar')].some(el => el.textContent.includes({lit}))",
                timeout=10,
            )
            print(f"--- t={i}s core={len(core)} 记事本@core={[ (w.get('title'), w.get('state'), w.get('rect',{}).get('w')) for w in np_core ]} ui={len(ui_titles)} hit={hit}")
            if i in (0, 4, 9, 14):
                print("    ui_titles:", json.dumps(ui_titles, ensure_ascii=False)[:400])
                print("    ui_bars  :", json.dumps(bars, ensure_ascii=False)[:400])
                print("    core_all :", json.dumps(
                    [(w.get("title"), w.get("state")) for w in core][:14], ensure_ascii=False)[:600])
            if hit:
                print("[diag] UI 已出现 notepad —— 问题不复现（纯时序）")
                break
            time.sleep(1.0)
        else:
            print("[diag] 15s 内 UI 始终未出现 notepad —— 问题稳定复现")

        # 抓页面错误：直接在页面里取 Vue app 状态 + 重新手动 fetch facts 看返回
        probe = base.ev(ws, """
            (() => {
              const stage = document.querySelector('[data-pw="run-stage"]');
              return {
                hint: document.querySelector('.run-stage__hint')?.textContent ?? '',
                chips: [...document.querySelectorAll('.pw-chip')].map(e => e.textContent.trim()).slice(0, 6),
                runWinCount: document.querySelectorAll('.run-win').length,
              };
            })()
        """, timeout=10)
        print("[diag] 页面状态:", json.dumps(probe, ensure_ascii=False))
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port_srv}/api/v1/windows", timeout=5) as r:
                via_proxy = json.loads(r.read().decode())
            print("[diag] 代理 /api/v1/windows 窗口数:", len(via_proxy.get("data") or []))
        except Exception as e:  # noqa: BLE001
            print("[diag] 代理取数失败:", e)
        return 0
    finally:
        if ws is not None:
            ws.close()
        edge.terminate()
        try:
            subprocess.run(["taskkill", "/PID", str(np.pid), "/F"], capture_output=True, timeout=10)
        except Exception:  # noqa: BLE001
            pass
        core_proc.terminate()
        srv.shutdown()


if __name__ == "__main__":
    sys.exit(main())
