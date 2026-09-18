"""诊断：WebView2（真实 Tauri App）的 CDP 行为。"""
import base64, json, os, socket, struct, subprocess, sys, tempfile, time, urllib.request

EXE = r"C:\Users\baiyu\Desktop\Personal Workspace\core\target\release\personal-workspace-core.exe"
PORT = 9351


def list_targets():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=10) as r:
        return json.loads(r.read().decode())


def ws_connect(path):
    s = socket.create_connection(("127.0.0.1", PORT), timeout=20)
    key = base64.b64encode(os.urandom(16)).decode()
    s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{PORT}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
               f"Sec-WebSocket-Version: 13\r\nOrigin: http://127.0.0.1:{PORT}\r\n\r\n").encode())
    resp = b""
    while b"\r\n\r\n" not in resp:
        c = s.recv(4096)
        if not c:
            raise RuntimeError("handshake eof")
        resp += c
    return s, resp.split(b"\r\n")[0]


def frame(payload: bytes) -> bytes:
    n = len(payload)
    if n < 126:
        h = struct.pack("!BB", 0x81, 0x80 | n)
    elif n < 65536:
        h = struct.pack("!BBH", 0x81, 0x80 | 126, n)
    else:
        h = struct.pack("!BBQ", 0x81, 0x80 | 127, n)
    return h + b"\x00\x00\x00\x00" + payload


def send(s, mid, method, params=None):
    s.sendall(frame(json.dumps({"id": mid, "method": method, "params": params or {}}).encode()))


def pump(s, want_id, timeout=8):
    s.settimeout(timeout)
    buf = b""
    deadline = time.time() + timeout
    while time.time() < deadline:
        hdr = s.recv(2)
        if not hdr:
            raise RuntimeError("eof")
        op = hdr[0] & 0x0F
        ln = hdr[1] & 0x7F
        if ln == 126:
            ln = struct.unpack("!H", s.recv(2))[0]
        elif ln == 127:
            ln = struct.unpack("!Q", s.recv(8))[0]
        data = b""
        while len(data) < ln:
            data += s.recv(ln - len(data))
        if op == 0x9:
            s.sendall(struct.pack("!BBH", 0x8A, 0x80 | 7, len(data)) + b"\x00" * 4 + data)
            continue
        if op == 0x8:
            raise RuntimeError("peer closed")
        buf += data
        try:
            msg = json.loads(buf.decode("utf-8", "replace"))
        except Exception:
            continue
        buf = b""
        if msg.get("id") == want_id:
            return msg
    raise TimeoutError("no reply")


def main():
    subprocess.run(["taskkill", "/F", "/IM", "personal-workspace-core.exe"], capture_output=True)
    time.sleep(1.5)
    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={PORT}"
    env["PW_DATA_DIR"] = tempfile.mkdtemp(prefix="pw-diag-")
    p = subprocess.Popen([EXE], cwd=os.path.dirname(EXE), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        target = None
        t0 = time.time()
        while time.time() - t0 < 60 and target is None:
            try:
                ts = list_targets()
                hit = [t for t in ts if t.get("type") == "page" and "tauri" in t.get("url", "")]
                if hit:
                    target = hit[0]
                    print("target found at", round(time.time() - t0, 1), "s ->", target["url"], target["id"][:16])
                    print("all targets:", [(t.get("url"), t.get("id", "")[:12]) for t in ts])
            except Exception as e:
                print("list retry", type(e).__name__)
                time.sleep(1.5)
        if not target:
            print("NO TARGET"); return
        path = target["webSocketDebuggerUrl"].split(f":{PORT}", 1)[-1]
        print("ws path:", path)
        s, status = ws_connect(path)
        print("handshake:", status)
        send(s, 1, "Runtime.enable")
        print("Runtime.enable ->", str(pump(s, 1))[:150])
        send(s, 2, "Runtime.evaluate", {"expression": "1+1", "returnByValue": True})
        print("small eval ->", str(pump(s, 2))[:200])
        big = ("(() => ({href: location.href, rs: document.readyState,"
               " nav: [...document.querySelectorAll('.app-nav a')].map(a => a.getAttribute('href')),"
               " text: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0,200)}))()")
        send(s, 3, "Runtime.evaluate", {"expression": big, "returnByValue": True})
        print("big eval ->", str(pump(s, 3))[:900])
    except Exception as e:
        print("FAIL", type(e).__name__, e)
    finally:
        p.terminate()


if __name__ == "__main__":
    main()
