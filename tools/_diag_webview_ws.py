"""诊断 2：WebView2 ws 握手变体（Origin / Host 组合）。"""
import base64, json, os, socket, subprocess, tempfile, time, urllib.request

EXE = r"C:\Users\baiyu\Desktop\Personal Workspace\core\target\release\personal-workspace-core.exe"
PORT = 9352


def variants(host_header, origin):
    lines = [f"GET {PATH} HTTP/1.1", f"Host: {host_header}", "Upgrade: websocket",
             "Connection: Upgrade", f"Sec-WebSocket-Key: {KEY}", "Sec-WebSocket-Version: 13"]
    if origin is not None:
        lines.append(f"Origin: {origin}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


def try_handshake(name, req_bytes):
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=8)
        s.sendall(req_bytes)
        resp = b""
        while b"\r\n\r\n" not in resp:
            c = s.recv(4096)
            if not c:
                break
            resp += c
        print(f"{name:46s} -> {resp.split(chr(13).encode())[0][:60]!r}")
        return s
    except Exception as e:
        print(f"{name:46s} -> ERR {type(e).__name__} {e}")
        return None


subprocess.run(["taskkill", "/F", "/IM", "personal-workspace-core.exe"], capture_output=True)
time.sleep(1.5)
env = dict(os.environ)
env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={PORT}"
env["PW_DATA_DIR"] = tempfile.mkdtemp(prefix="pw-diag2-")
p = subprocess.Popen([EXE], cwd=os.path.dirname(EXE), env=env,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    t0 = time.time()
    tgt = None
    while time.time() - t0 < 60 and tgt is None:
        try:
            ts = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=10).read())
            hit = [t for t in ts if "tauri" in t.get("url", "")]
            if hit:
                tgt = hit[0]
        except Exception:
            time.sleep(1.5)
    print("target:", tgt["url"])
    PATH = tgt["webSocketDebuggerUrl"].split(f":{PORT}", 1)[-1]
    KEY = base64.b64encode(os.urandom(16)).decode()
    for name, host, origin in [("no-Origin / Host=127.0.0.1:port", f"127.0.0.1:{PORT}", None),
                               ("no-Origin / Host=localhost:port", f"localhost:{PORT}", None),
                               ("Origin=devtools://devtools", f"127.0.0.1:{PORT}", "devtools://devtools"),
                               ("Origin=http://127.0.0.1:port", f"127.0.0.1:{PORT}", f"http://127.0.0.1:{PORT}"),
                               ("Origin=http://localhost:port", f"localhost:{PORT}", f"http://localhost:{PORT}")]:
        try_handshake(name, variants(host, origin))
        time.sleep(0.3)
finally:
    p.terminate()
