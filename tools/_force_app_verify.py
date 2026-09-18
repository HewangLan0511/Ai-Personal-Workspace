"""真实 Tauri App 实机验证（WebView2 CDP + 真实鼠标点击）。

用途：UI-FUSION-FORCE §八 —— 不靠静态截图，直接在正式 App 上点击全部导航项，
逐项读取 location.pathname + main 区文案 + DOM 标记，并截图存档。

环境事实（本项目实测，勿删）：
  * WebView2 的 DevTools HTTP 端点很脆：一次超时/半开连接就会卡死后续请求 →
    只在需要时**单次**取 /json/list，取到即刻连 ws。
  * ws 握手**不能带 Origin 头**（带了返回 403）。
  * App 窗口的 page 靶标在导航完成前就已列出（此时 location 仍是 about:blank）→
    必须等 href 变成 tauri.localhost 且 .app-nav 出现；连上后帧一旦被换掉，ws 会被 RST，
    因此 call() 必须支持重连重试。

用法：
    python tools/_force_app_verify.py <exe 路径>
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\baiyu\Desktop\Personal Workspace")
OUT = ROOT / "tools" / "_fusion_shots"
NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def free_port() -> int:
    """每次运行取一个空闲端口 —— WebView2 孤儿进程会长期占住上一个端口，
    固定端口会让后续运行全部连不上（本项目实测踩过）。"""
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def list_page_targets(port: int, want: str = "tauri"):
    # 必须绕沙箱代理：环境里的 HTTP(S)_PROXY 会把 127.0.0.1 的请求也劫走 → 502 / 超时。
    # want 用于区分 WebView2（tauri.localhost）与 Edge 无头（127.0.0.1）两类靶标。
    with NO_PROXY_OPENER.open(f"http://127.0.0.1:{port}/json/list", timeout=10) as r:
        tabs = json.loads(r.read().decode())
    return [t for t in tabs if t.get("type") == "page" and want in t.get("url", "")]


class CDP:
    """极简 CDP 客户端（无 Origin 头 + 自动重连）。"""

    def __init__(self, port: int, want: str = "tauri"):
        self.port = port
        self.want = want
        self.sock = None
        self.mid = 0
        self.target_url = ""
        self.reconnects = 0
        self._attach()
        self.call("Page.enable")
        self.call("Runtime.enable")

    # ---------- 连接 ----------
    def _attach(self, wait=45):
        target = None
        deadline = time.time() + wait
        while time.time() < deadline and target is None:
            try:
                hit = list_page_targets(self.port, self.want)
                if hit:
                    target = hit[0]
            except Exception:
                time.sleep(1.5)
        if target is None:
            raise RuntimeError("CDP 未就绪（WebView2 远程调试未开启？）")
        self.target_url = target.get("url", "")
        path = target["webSocketDebuggerUrl"].split(f":{self.port}", 1)[-1]
        self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("handshake eof")
            resp += chunk
        if b"101" not in resp.split(b"\r\n")[0]:
            raise RuntimeError(f"handshake failed: {resp[:120]!r}")

    def wait_ready(self, timeout=45):
        """等 App 真正渲染：href 是 tauri.localhost 且 .app-nav 存在。"""
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            try:
                last = self.js("({h: location.href, rs: document.readyState,"
                               " nav: document.querySelectorAll('.app-nav a').length})()")
                if last and "tauri" in str(last.get("h", "")) and last.get("nav"):
                    return last
            except Exception:
                pass
            time.sleep(1.5)
        raise RuntimeError(f"App 未就绪，最后状态={last}")

    # ---------- 调用 ----------
    def call(self, method, params=None, timeout=30, retry=True):
        try:
            return self._call_once(method, params, timeout)
        except (ConnectionResetError, ConnectionAbortedError, ConnectionError, RuntimeError, TimeoutError, OSError):
            if not retry:
                raise
            self.reconnects += 1
            time.sleep(2.5)
            self._attach()
            self._call_once("Page.enable", None, 15)
            self._call_once("Runtime.enable", None, 15)
            return self._call_once(method, params, timeout)

    def _call_once(self, method, params=None, timeout=30):
        self.mid += 1
        mid = self.mid
        payload = json.dumps({"id": mid, "method": method, "params": params or {}}).encode()
        n = len(payload)
        if n < 126:
            header = struct.pack("!BB", 0x81, 0x80 | n)
        elif n < 65536:
            header = struct.pack("!BBH", 0x81, 0x80 | 126, n)
        else:
            header = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
        self.sock.sendall(header + b"\x00\x00\x00\x00" + payload)
        deadline = time.time() + timeout
        buf = b""
        while time.time() < deadline:
            hdr = self._recv(2)
            op = hdr[0] & 0x0F
            ln = hdr[1] & 0x7F
            if ln == 126:
                ln = struct.unpack("!H", self._recv(2))[0]
            elif ln == 127:
                ln = struct.unpack("!Q", self._recv(8))[0]
            data = self._recv(ln) if ln else b""
            if op == 0x9:
                self.sock.sendall(struct.pack("!BBH", 0x8A, 0x80 | 7, len(data)) + b"\x00" * 4 + data)
                continue
            if op == 0x8:
                raise RuntimeError("peer closed")
            if op != 0x1:
                continue
            buf += data
            try:
                msg = json.loads(buf.decode("utf-8", "replace"))
            except Exception:
                continue
            buf = b""
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(str(msg["error"]))
                return msg.get("result", {})
        raise TimeoutError(method)

    def _recv(self, n):
        out = b""
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise RuntimeError("eof")
            out += chunk
        return out

    def js(self, expr, timeout=25):
        r = self.call("Runtime.evaluate",
                      {"expression": expr, "returnByValue": True, "awaitPromise": True},
                      timeout=timeout)
        if r.get("exceptionDetails"):
            return {"__error__": str(r["exceptionDetails"])[:200]}
        return r.get("result", {}).get("value")

    def shot(self, name: str):
        r = self.call("Page.captureScreenshot", {"format": "png"}, timeout=40)
        (OUT / f"{name}.png").write_bytes(base64.b64decode(r["data"]))

    def click_selector(self, selector: str, drain: float = 1.5):
        """真实鼠标点击：取元素中心 → Input.dispatchMouseEvent（移动/按下/抬起）。"""
        box = self.js(
            "(() => { const el = document.querySelector(%s); if (!el) return null;"
            "const r = el.getBoundingClientRect();"
            "return {x: r.left + r.width/2, y: r.top + r.height/2,"
            " t: (el.textContent||'').trim().replace(/\\s+/g,' ').slice(0,24)}; })()"
            % json.dumps(selector)
        )
        if not box or box.get("x") is None:
            return None
        x, y = box["x"], box["y"]
        for typ in ("mouseMoved", "mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent",
                      {"type": typ, "x": x, "y": y, "button": "left",
                       "clickCount": 1 if typ != "mouseMoved" else 0})
            time.sleep(0.1)
        time.sleep(drain)
        return box.get("t")


STATE_JS = (
    "(() => ({ path: location.pathname,"
    " nav: [...document.querySelectorAll('.app-nav a')].map(a => a.getAttribute('href')),"
    " set_layout: !!document.querySelector('.set-layout, .set-subnav'),"
    " main: (document.querySelector('main')?.innerText || '').replace(/\\s+/g,' ').slice(0,120)"
    "}))()"
)


def kill_leaked():
    subprocess.run(["taskkill", "/F", "/IM", "personal-workspace-core.exe"], capture_output=True)
    time.sleep(1.5)


def main():
    exe = sys.argv[1] if len(sys.argv) > 1 else str(ROOT / "core" / "target" / "release" / "personal-workspace-core.exe")
    tag = "installed" if ("D:\\" in exe or "D:/" in exe) else "built"
    data_dir = tempfile.mkdtemp(prefix=f"pw-force-{tag}-")
    port = free_port()
    report = {"exe": exe, "tag": tag, "data_dir": data_dir, "cdp_port": port, "steps": []}
    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={port}"
    env["PW_DATA_DIR"] = data_dir

    cdp = None
    proc = None
    # WebView2 只允许一个调试客户端，且端点对半开连接敏感 —— 连接失败一律杀进程重启 App 重试。
    for attempt in range(1, 4):
        kill_leaked()
        proc = subprocess.Popen([exe], cwd=str(Path(exe).parent), env=env,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(8)  # 等窗口出现 + SPA 首屏加载（导航完成前连上会踩帧替换，靠 wait_ready 兜底）
        try:
            cdp = CDP(port)
            break
        except Exception as e:  # noqa: BLE001
            report.setdefault("attach_attempts", []).append(f"attempt{attempt}: {type(e).__name__}: {e}")
            proc.terminate()
            time.sleep(3)
    if cdp is None:
        report["error"] = "无法连接 WebView2 调试端点"
        (ROOT / "tools" / f"_force_verify_{tag}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    try:
        report["target"] = cdp.target_url
        report["ready"] = cdp.wait_ready()
        report["first_screen"] = cdp.js(STATE_JS)
        cdp.shot(f"force-{tag}-01-home")

        for href, label in [("/dashboard", "首页"), ("/mode", "工作空间"), ("/software", "软件"),
                            ("/learning", "学习"), ("/project", "项目"), ("/life", "生活"),
                            ("/ai", "AI助手"), ("/profile", "档案"), ("/plugins", "插件"),
                            ("/device", "设备"), ("/settings", "设置")]:
            txt = cdp.click_selector(f'.app-nav a[href="{href}"]')
            st = cdp.js(STATE_JS)
            report["steps"].append({"step": f"nav {label}", "href": href, "clicked": txt,
                                    "path": st.get("path") if st else None,
                                    "ok": bool(st and st.get("path") == href),
                                    "main": (st or {}).get("main", "")})
            cdp.shot(f"force-{tag}-nav-{href.strip('/')}")

        # 设置页 → AI 与模型 → Model Center
        tabs = cdp.js("[...document.querySelectorAll('.set-subnav a, .set-nav a, .set-tabs a')]"
                      ".map(a => ({h: a.getAttribute('href'), t: (a.textContent||'').trim()}))")
        report["settings_subnav"] = tabs
        clicked = None
        if isinstance(tabs, list):
            for t in tabs:
                if t.get("t") and ("AI" in t["t"] or "模型" in t["t"]):
                    if t.get("h"):
                        cdp.js(f"document.querySelector('.set-subnav a[href=\"{t['h']}\"]')?.click()")
                    clicked = t
                    break
        else:
            clicked = cdp.click_selector(".set-subnav > *:nth-child(3)")
        time.sleep(1.2)
        st = cdp.js(STATE_JS)
        report["steps"].append({"step": "设置 → AI 与模型", "clicked": clicked, "main": (st or {}).get("main", "")})

        mc = cdp.click_selector('a[href^="/models"]')
        st = cdp.js(STATE_JS)
        report["steps"].append({"step": "设置 → Model Center", "clicked": mc,
                                "path": st.get("path") if st else None,
                                "ok": bool(st and st.get("path") == "/models"),
                                "main": (st or {}).get("main", "")})
        cdp.shot(f"force-{tag}-models-from-settings")
        report["reconnects"] = cdp.reconnects
    except Exception as e:  # noqa: BLE001
        report["error"] = f"{type(e).__name__}: {e}"
    finally:
        report["proc_pid"] = proc.pid
        (ROOT / "tools" / f"_force_verify_{tag}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
