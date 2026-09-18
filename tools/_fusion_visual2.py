"""CDP 截图（真实时间等待，绕过 virtual-time 与过渡动画的相容问题）。"""
import base64
import http.server
import json
import functools
import socket
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path

DIST = Path(r"C:\Users\baiyu\Desktop\Personal Workspace\ui\dist")
OUT = Path(r"C:\Users\baiyu\Desktop\Personal Workspace\tools\_fusion_shots")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT_HTTP = 4801
PORT_CDP = 9333


class SPAHandler(http.server.SimpleHTTPRequestHandler):
    def send_head(self):
        p = Path(self.translate_path(self.path))
        if (not p.exists() or p.is_dir()) and "." not in p.name:
            self.path = "/index.html"
        return super().send_head()

    def log_message(self, *a):
        pass


class CDP:
    def __init__(self, port: int):
        m = None
        for _ in range(40):
            try:
                import urllib.request
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                    tabs = json.loads(r.read().decode())
                page = next(t for t in tabs if t.get("type") == "page")
                m = page["webSocketDebuggerUrl"].split(f":{port}")[-1]
                break
            except Exception:
                time.sleep(0.5)
        if m is None:
            raise SystemExit("CDP 未就绪")
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=30)
        self.path = m
        self.mid = 0
        # HTTP Upgrade 握手（CDP ws 必需）
        import os as _os
        key = base64.b64encode(_os.urandom(16)).decode()
        req = (
            f"GET {m} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
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

    def call(self, method, params=None, timeout=30):
        self.mid += 1
        mid = self.mid
        payload = json.dumps({"id": mid, "method": method, "params": params or {}}).encode()
        mask = b"\x00\x00\x00\x00"
        masked = bytes(b ^ 0 for b in payload)
        n = len(payload)
        if n < 126:
            header = struct.pack("!BB", 0x81, 0x80 | n)
        elif n < 65536:
            header = struct.pack("!BBH", 0x81, 0x80 | 126, n)
        else:
            header = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
        self.sock.sendall(header + mask + masked)
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
                raise RuntimeError("closed")
            if op != 0x1:
                continue
            buf += data
            msg = json.loads(buf.decode("utf-8", "replace"))
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


def shot(cdp: CDP, url: str, name: str):
    cdp.call("Page.navigate", {"url": url})
    time.sleep(4)
    r = cdp.call("Page.captureScreenshot", {"format": "png"})
    (OUT / f"{name}.png").write_bytes(base64.b64decode(r["data"]))
    print("shot", name)


if __name__ == "__main__":
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT_HTTP),
                                          functools.partial(SPAHandler, directory=str(DIST)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    prof = tempfile.mkdtemp(prefix="pw-fusion-cdp-")
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--no-first-run",
         "--window-size=1440,900", "--force-device-scale-factor=1",
         f"--user-data-dir={prof}", f"--remote-debugging-port={PORT_CDP}",
         f"http://127.0.0.1:{PORT_HTTP}/settings"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(6)
    cdp = CDP(PORT_CDP)
    cdp.call("Page.enable")
    cdp.call("Emulation.setDeviceMetricsOverride",
             {"width": 1440, "height": 900, "deviceScaleFactor": 1, "mobile": False})
    base = f"http://127.0.0.1:{PORT_HTTP}"
    for route, name in [("settings", "cdp-settings"), ("software", "cdp-software"),
                        ("mode", "cdp-mode"), ("run", "cdp-run"),
                        ("ai", "cdp-ai"), ("profile", "cdp-profile"),
                        ("models", "cdp-models"), ("learning", "cdp-learning"),
                        ("life", "cdp-life"), ("device", "cdp-device"),
                        ("plugins", "cdp-plugins"), ("project", "cdp-project")]:
        try:
            shot(cdp, f"{base}/{route}", name)
        except Exception as e:
            print("ERR", name, e)
    proc.terminate()
    srv.shutdown()
    print("done")
