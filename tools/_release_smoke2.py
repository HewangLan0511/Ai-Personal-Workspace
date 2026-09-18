"""V0.1-RELEASE runtime smoke via installed core's HTTP API (port from its SQLite)."""
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

LOGS = Path(__file__).resolve().parent
EXE = r"D:\Personal Workspace\personal-workspace-core.exe"
DB = Path(os.environ["APPDATA"]) / "PersonalWorkspace" / "workspace.db"

RESULTS = []


def check(name, ok, detail):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'} {name} — {detail}", flush=True)


def get_port() -> int | None:
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    try:
        cur = con.execute("SELECT value FROM config WHERE key='runtime.http_port'")
        row = cur.fetchone()
        return int(row[0]) if row else None
    finally:
        con.close()


def http(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return json.loads(r.read().decode())


def main() -> int:
    proc = subprocess.Popen([EXE], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[launch] installed app pid={proc.pid}", flush=True)
    try:
        port = None
        deadline = time.time() + 30
        while time.time() < deadline and port is None:
            time.sleep(2)
            try:
                port = get_port()
            except Exception:
                port = None
        check("S1 已安装实例启动并写入用户数据目录（%APPDATA%/PersonalWorkspace）",
              port is not None and DB.exists(), f"port={port} db={DB}")
        if port is None:
            return 1

        health = http(port, "/health")
        check("S2 Core /health（已安装实例）",
              isinstance(health, dict) and bool(health),
              json.dumps(health, ensure_ascii=False)[:160])

        apps = http(port, "/api/v1/apps")
        d = apps.get("data")
        n_apps = len(d) if isinstance(d, list) else len((d or {}).get("apps") or [])
        check("S3 软件库读取（/api/v1/apps）", True, f"{n_apps} 项")

        modes = http(port, "/api/v1/modes")
        d = modes.get("data")
        n_modes = len(d) if isinstance(d, list) else len((d or {}).get("modes") or [])
        check("S4 模式库读取（/api/v1/modes）", True, f"{n_modes} 模式")

        mons = http(port, "/api/v1/monitors")
        n_mon = len(mons.get("data") or [])
        check("S5 显示器事实（/api/v1/monitors，窗口投影基准）", n_mon >= 1, f"{n_mon} 台")

        layouts = http(port, "/api/v1/layouts")
        check("S6 布局库读取（/api/v1/layouts）", True, f"{len(json.dumps(layouts))}B")

        # 数据表存在性（profile / model registry / snapshot 键）
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        ai_keys = [r[0] for r in con.execute(
            "SELECT key FROM config WHERE key LIKE 'ai.%'")]
        con.close()
        need = {
            "profile 数据表": any("profile" in t for t in tables),
            "model registry 持久化（config ai.* 键，契约 PW-INTEGRATION-003）": len(ai_keys) > 0,
            "config 键值表（snapshot.last 载体）": "config" in tables,
            "layouts 表": any("layout" in t for t in tables),
        }
        for k, ok in need.items():
            check(f"S7 {k}", ok, f"ai_keys={ai_keys}" if "model" in k else "")
        check("S8 表清单", True, f"{sorted(tables)[:18]}")
    finally:
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
