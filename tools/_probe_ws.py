"""Probe WebView2 CDP websocket handshake behavior."""
import base64
import json
import os
import socket
import subprocess
import time
import urllib.request

EXE = r"D:\Personal Workspace\personal-workspace-core.exe"
DBG = 9226

env = dict(os.environ)
env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={DBG}"
proc = subprocess.Popen([EXE], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(10)
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{DBG}/json/version", timeout=3) as r:
        print("VERSION:", r.read().decode()[:300])
    with urllib.request.urlopen(f"http://127.0.0.1:{DBG}/json/list", timeout=3) as r:
        pages = json.loads(r.read().decode())
    for p in pages:
        print("PAGE:", p.get("type"), "|", (p.get("url") or "")[:60], "|", p.get("webSocketDebuggerUrl"))

    target = next((p for p in pages if p.get("webSocketDebuggerUrl")), None)
    if target:
        wsurl = target["webSocketDebuggerUrl"]
        rest = wsurl[5:]
        hostport, path = rest.split("/", 1)
        path = "/" + path
        for host_header in (hostport, f"localhost:{hostport.split(':')[1]}"):
            s = socket.create_connection((hostport.split(":")[0], int(hostport.split(":")[1])), timeout=5)
            key = base64.b64encode(os.urandom(16)).decode()
            req = (f"GET {path} HTTP/1.1\r\nHost: {host_header}\r\nUpgrade: websocket\r\n"
                   f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
            try:
                s.sendall(req.encode())
                s.settimeout(5)
                resp = b""
                try:
                    while b"\r\n\r\n" not in resp:
                        chunk = s.recv(4096)
                        if not chunk:
                            break
                        resp += chunk
                except socket.timeout:
                    resp += b"<timeout>"
                print(f"Host={host_header} -> {resp[:200]!r}")
            finally:
                s.close()
finally:
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
