"""V0.1-RELEASE runtime smoke: launch INSTALLED exe, CDP-verify UI + core."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LOGS = Path(__file__).resolve().parent
EXE = r"D:\Personal Workspace\personal-workspace-core.exe"
import verify_tech02_workspace as _base
DBG = _base.free_port()

sys.path.insert(0, str(LOGS))
import verify_tech02_workspace as base  # noqa: E402

RESULTS = []


def check(name, ok, detail):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} — {detail}", flush=True)


def pick_page_url(port: int) -> str | None:
    """挑 webview 主页面（tauri.localhost）的 ws url。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
            pages = [t for t in json.loads(r.read().decode()) if t.get("type") == "page"]
    except OSError:
        return None
    for p in pages:
        if "tauri.localhost" in (p.get("url") or ""):
            return p.get("webSocketDebuggerUrl")
    return pages[0].get("webSocketDebuggerUrl") if pages else None


def main() -> int:
    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={DBG}"
    # 不设 PW_DATA_DIR —— 验证默认数据目录机制
    proc = subprocess.Popen([EXE], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[launch] installed app pid={proc.pid}", flush=True)
    ws = None
    try:
        ws_url = None
        deadline = time.time() + 40
        while time.time() < deadline and not ws_url:
            ws_url = pick_page_url(DBG)
            if not ws_url:
                time.sleep(0.5)
        check("S-launch 安装版应用启动 + WebView2 CDP 可连", bool(ws_url), f"pid={proc.pid}")
        if not ws_url:
            return 1
        # 应用启动后 webview 可能随 core 就绪重载一次 —— 等稳定 + 连接前重取最新 ws url
        time.sleep(10)
        ws = None
        last_err = None
        for attempt in range(4):
            fresh = pick_page_url(DBG) or ws_url
            try:
                ws = base.CDPWebSocket(fresh)
                break
            except (ConnectionError, OSError) as e:
                last_err = e
                print(f"[cdp] 握手重试 {attempt + 1}/4：{e}", flush=True)
                time.sleep(4)
        if ws is None:
            check("S-cdp CDP WebSocket 连接", False, f"4 次重试均失败：{last_err}")
            return 1
        check("S-cdp CDP WebSocket 连接稳定", True, "ok")
        ws.call("Page.enable")
        time.sleep(3)

        # inTauri + 首页渲染
        base.wait_for(ws, "!!document.querySelector('.run-page, #app, main, .dashboard-page')", timeout=30)
        tauri = base.ev(ws, "('__TAURI_INTERNALS__' in window)", timeout=10)
        check("S-tauri 运行在 Tauri WebView（invoke 主路径可用）", tauri is True, f"inTauri={tauri}")
        marker = base.ev(
            ws,
            "(() => { const t = document.body.innerText || '';"
            " return { dash: t.includes('仪表') || t.includes('Dashboard') || t.includes('工作'),"
            " len: t.length }; })()",
            timeout=10,
        )
        check("S-home 首页渲染（首页内容非空）", bool(marker) and marker.get("len", 0) > 100,
              json.dumps(marker or {}, ensure_ascii=False))
        online = base.ev(
            ws,
            "(() => { const c = window.__pw_conn ? window.__pw_conn.online : null;"
            " return c; })()",
            timeout=10,
        )
        # connection 不一定暴露到 window —— 用 UI 文案判断：非"未连接"告警即在线
        off = base.ev(
            ws,
            "(() => { const t = document.body.innerText || '';"
            " return { offlineMarks: (t.match(/未连接/g) || []).length }; })()",
            timeout=10,
        )
        check("S-core Core 在线（页面无『未连接』标记）",
              bool(off) and off.get("offlineMarks", 1) == 0, json.dumps(off or {}))

        # 路由冒烟：/run /models /profile（Windows Tauri 2 webview origin = http://tauri.localhost）
        for route, kw in (("/run", "舞台"), ("/models", "模型"), ("/profile", "档案")):
            ws.call("Page.navigate", {"url": f"http://tauri.localhost{route}"}, timeout=15)
            time.sleep(2.5)
            ok = base.ev(
                ws,
                f"(() => {{ const t = document.body.innerText || ''; return t.length > 100 }})()",
                timeout=10,
            )
            check(f"S-route {route} 渲染（{kw}链路页面非空）", bool(ok), f"rendered={ok}")
        # 回首页
        ws.call("Page.navigate", {"url": "http://tauri.localhost/"}, timeout=15)
        time.sleep(2)
    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    total = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"SMOKE {total}/{len(RESULTS)}", flush=True)
    return 0 if total == len(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
