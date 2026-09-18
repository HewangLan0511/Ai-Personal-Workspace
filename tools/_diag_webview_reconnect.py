"""诊断 4：早连 + 导航后就绪等待 + 重连恢复的可行性。"""
import base64, json, os, socket, struct, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

EXE = r"C:\Users\baiyu\Desktop\Personal Workspace\core\target\release\personal-workspace-core.exe"


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def list_targets(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=6) as r:
        return [t for t in json.loads(r.read().decode())
                if t.get("type") == "page" and "tauri" in t.get("url", "")]


def connect(port, target):
    path = target["webSocketDebuggerUrl"].split(f":{port}", 1)[-1]
    s = socket.create_connection(("127.0.0.1", port), timeout=20)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        c = s.recv(4096)
        if not c:
            raise RuntimeError("handshake eof")
        resp += c
    if b"101" not in resp.split(b"\r\n")[0]:
        raise RuntimeError(f"handshake {resp.split(chr(13).encode())[0]!r}")
    return s


def rpc(s, mid, method, params=None, timeout=6):
    payload = json.dumps({"id": mid, "method": method, "params": params or {}}).encode()
    n = len(payload)
    h = struct.pack("!BB", 0x81, 0x80 | n) if n < 126 else struct.pack("!BBH", 0x81, 0x80 | 126, n)
    s.sendall(h + b"\x00\x00\x00\x00" + payload)
    s.settimeout(timeout)
    buf = b""
    t0 = time.time()
    while time.time() - t0 < timeout:
        hdr = s.recv(2)
        op = hdr[0] & 0x0F; ln = hdr[1] & 0x7F
        if ln == 126: ln = struct.unpack("!H", s.recv(2))[0]
        elif ln == 127: ln = struct.unpack("!Q", s.recv(8))[0]
        data = b""
        while len(data) < ln: data += s.recv(ln - len(data))
        if op == 0x8: raise RuntimeError("peer closed")
        if op != 0x1: continue
        buf += data
        try: msg = json.loads(buf.decode("utf-8", "replace"))
        except Exception: continue
        buf = b""
        if msg.get("id") == mid: return msg
    raise TimeoutError(method)


PORT = free_port()
subprocess.run(["taskkill", "/F", "/IM", "personal-workspace-core.exe"], capture_output=True)
time.sleep(1)
env = dict(os.environ)
env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={PORT}"
env["PW_DATA_DIR"] = tempfile.mkdtemp(prefix="pw-diag4-")
proc = subprocess.Popen([EXE], cwd=os.path.dirname(EXE), env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("port", PORT)
sock = None
mid = 0
t0 = time.time()
try:
    while time.time() - t0 < 40:
        if sock is None:
            try:
                tg = list_targets(PORT)
                if tg:
                    sock = connect(PORT, tg[0])
                    mid += 1
                    rpc(sock, mid, "Runtime.enable")
                    print(f"[{time.time()-t0:5.1f}s] attached, url={tg[0]['url']}")
                else:
                    print(f"[{time.time()-t0:5.1f}s] no tauri target yet")
            except Exception as e:
                print(f"[{time.time()-t0:5.1f}s] attach/list err {type(e).__name__}: {e}")
            time.sleep(1.0)
            continue
        try:
            mid += 1
            r = rpc(sock, mid, "Runtime.evaluate",
                    {"expression": "location.href + '|' + document.readyState + '|' + document.querySelectorAll('.app-nav a').length",
                     "returnByValue": True})
            val = r.get("result", {}).get("result", {}).get("value")
            print(f"[{time.time()-t0:5.1f}s] eval -> {val}")
            if val and "tauri" in str(val) and str(val).endswith("|11"):
                print("READY with nav 11")
                break
        except Exception as e:
            print(f"[{time.time()-t0:5.1f}s] eval err {type(e).__name__}: {e} -> reconnect")
            try:
                sock.close()
            except Exception:
                pass
            sock = None
        time.sleep(1.2)
finally:
    proc.terminate()
