"""V0.1-RELEASE install/launch smoke orchestrator (NSIS or MSI)."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUNDLE = ROOT / "core" / "target" / "release" / "bundle"
LOGS = ROOT / "tools"
APPDATA = os.environ["APPDATA"]
DATA_DIR = Path(APPDATA) / "PersonalWorkspace"


def find_installed_exe() -> Path | None:
    candidates = [
        Path(os.environ["LOCALAPPDATA"]) / "Programs" / "Personal Workspace" / "personal-workspace-core.exe",
        Path(os.environ["LOCALAPPDATA"]) / "Personal Workspace" / "personal-workspace-core.exe",
        Path(os.environ["ProgramFiles"]) / "Personal Workspace" / "personal-workspace-core.exe",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def cdp_pages(port: int):
    for _ in range(40):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2) as r:
                pages = [t for t in json.loads(r.read().decode()) if t.get("type") == "page"]
            if pages:
                return pages
        except OSError:
            pass
        time.sleep(0.5)
    return []


def main() -> int:
    mode = sys.argv[1]  # nsis | msi
    if mode == "nsis":
        installer = BUNDLE / "nsis" / "Personal Workspace_0.1.0_x64-setup.exe"
        print("[install] NSIS silent install...", flush=True)
        subprocess.run([str(installer), "/S"], timeout=300, check=True)
        time.sleep(3)
    else:
        installer = BUNDLE / "msi" / "Personal Workspace_0.1.0_x64_en-US.msi"
        print("[install] MSI quiet install...", flush=True)
        subprocess.run(["msiexec", "/i", str(installer), "/qn", "/norestart"],
                       timeout=600, check=True)
        time.sleep(3)

    exe = find_installed_exe()
    print(f"[install] installed exe = {exe}", flush=True)
    if not exe:
        return 2

    # data dir will be created on first launch
    dbg = 9223 if mode == "nsis" else 9224
    env = dict(os.environ)
    env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = f"--remote-debugging-port={dbg}"
    proc = subprocess.Popen([str(exe)], env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[launch] pid={proc.pid} cdp={dbg}", flush=True)
    time.sleep(8)
    pages = cdp_pages(dbg)
    print(f"[cdp] pages={len(pages)}", flush=True)
    out = {"mode": mode, "exe": str(exe), "pages": len(pages),
           "dataDirExists": DATA_DIR.exists(),
           "dataDirContent": sorted(p.name for p in DATA_DIR.glob("*"))[:20] if DATA_DIR.exists() else []}
    (LOGS / f"_release_{mode}_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    # 保持进程运行，由外层决定何时杀；写 pid 供外层用
    (LOGS / f"_release_{mode}_pid.txt").write_text(str(proc.pid), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
