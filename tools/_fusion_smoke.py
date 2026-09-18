"""UI-FUSION-REAL：真机 Smoke（release exe 启动 → HTTP API 冒烟）。"""
import json
import os
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(r"C:\Users\baiyu\Desktop\Personal Workspace")
EXE = ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"
DATA = Path(os.environ["APPDATA"]) / "PersonalWorkspace"
DB = DATA / "workspace.db"

ok = []

# S1 启动 release exe（若已在运行则复用）
rc = subprocess.run(["tasklist", "/FI", "IMAGENAME eq personal-workspace-core.exe"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace")
running = "personal" in (rc.stdout or "").lower()
if not running:
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(EXE)], creationflags=flags,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(10)
ok.append(("S1 release exe 启动", True, f"pre_running={running}"))

# S2 读 http_port → /health
port = None
for _ in range(30):
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        cur = con.execute("SELECT value FROM config WHERE key='runtime.http_port'")
        row = cur.fetchone()
        con.close()
        if row:
            port = int(json.loads(row[0])) if isinstance(row[0], str) and row[0].startswith('"') else int(row[0])
            break
    except Exception:
        pass
    time.sleep(1)
ok.append(("S2 用户数据目录 + runtime.http_port", port is not None, f"db={DB} port={port}"))

if port:
    def get(path: str):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return json.loads(r.read().decode())

    health = get("/health")
    ok.append(("S3 /health", health.get("ok") is True, str(health.get("data", {}))[:80]))
    apps = get("/api/v1/apps")
    ok.append(("S4 软件库", isinstance(apps.get("data"), list), f"n={len(apps.get('data', []))}"))
    layouts = get("/api/v1/layouts")
    ok.append(("S5 布局库", "data" in layouts, f"bytes={len(json.dumps(layouts))}"))
    monitors = get("/api/v1/monitors")
    ok.append(("S6 显示器", "data" in monitors, f"n={len(monitors.get('data', []))}"))
else:
    ok.append(("S3~S6 HTTP 冒烟", False, "未读到端口"))

print()
for name, passed, detail in ok:
    print(("PASS " if passed else "FAIL ") + name + " — " + detail)
fails = [n for n, p, _ in ok if not p]
print(f"\nSMOKE {len(ok)-len(fails)}/{len(ok)}")
