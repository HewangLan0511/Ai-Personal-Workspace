"""V0.1 smoke: dev server + stage1 route verification, then cleanup."""
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui"
LOGS = ROOT / "tools"
EXE = ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"


def main() -> int:
    dev = subprocess.Popen(
        ["npm.cmd", "run", "dev"], cwd=str(UI),
        stdout=open(LOGS / "_v01_devserver.log", "w", encoding="utf-8"),
        stderr=subprocess.STDOUT, shell=True)
    up = False
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:5173", timeout=2) as r:
                if r.status == 200:
                    up = True
                    break
        except OSError:
            time.sleep(1)
    print(f"devserver up={up}", flush=True)
    rc = 1
    if up:
        p = subprocess.run(
            [sys.executable, str(LOGS / "verify_stage1.py"),
             "--exe", str(EXE), "--routes-url", "http://localhost:5173",
             "--widget-probe"],
            cwd=str(ROOT), capture_output=True, text=True, timeout=1200)
        (LOGS / "_v01_smoke_routes.log").write_text(
            (p.stdout or "") + "\n---STDERR---\n" + (p.stderr or "")[-2000:],
            encoding="utf-8")
        rc = p.returncode
        print(p.stdout[-1500:], flush=True)
    try:
        dev.terminate()
        dev.wait(timeout=10)
    except Exception:
        dev.kill()
    # 收尾：清掉 vite 残留 node 子树（按命令行匹配，避免误伤其他 node）
    subprocess.run(
        ["wmic", "process", "where",
         "name='node.exe' and commandline like '%vite%'", "call", "terminate"],
        capture_output=True, timeout=30)
    print(f"stage1 exit={rc}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
