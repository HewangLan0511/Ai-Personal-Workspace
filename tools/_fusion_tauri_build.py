"""UI-FUSION-REAL：Tauri release 构建（嵌入新 dist；不打包 installer，只出 exe 即可真机 smoke）。"""
import subprocess
import time
from pathlib import Path

UI = Path(r"C:\Users\baiyu\Desktop\Personal Workspace\ui")
TAURI_MJS = UI / "scripts" / "tauri.mjs"
NODE = r"C:\Users\baiyu\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"

t0 = time.time()
r = subprocess.run([NODE, str(TAURI_MJS), "build"],
                   cwd=str(UI), capture_output=True, text=True,
                   encoding="utf-8", errors="replace", timeout=1800)
out = (r.stdout or "") + (r.stderr or "")
print("exit", r.returncode, f"({time.time()-t0:.0f}s)")
print("\n".join(out.strip().splitlines()[-15:]))
