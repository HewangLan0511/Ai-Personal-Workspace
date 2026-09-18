"""UI-FUSION-REAL 前端构建编排：typecheck + vite build（VITE_CORE_BASE='' 同源）。"""
import os
import subprocess
import sys
import time
from pathlib import Path

UI = Path(r"C:\Users\baiyu\Desktop\Personal Workspace\ui")
NODE = r"C:\Users\baiyu\.workbuddy\binaries\node\versions\22.22.2-3\node.exe"
VUE_TSC = str(UI / "node_modules" / "vue-tsc" / "bin" / "vue-tsc.js")
VITE = str(UI / "node_modules" / "vite" / "bin" / "vite.js")

env = dict(os.environ)
env["VITE_CORE_BASE"] = ""  # 同源验证构建（C2/C3 验收要求）


def run(cmd: list[str], tag: str, timeout: int = 600) -> int:
    t0 = time.time()
    r = subprocess.run(cmd, cwd=str(UI), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    out = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(out.strip().splitlines()[-25:])
    print(f"=== {tag} exit={r.returncode} ({time.time()-t0:.1f}s) ===")
    if out.strip():
        print(tail)
    return r.returncode


if __name__ == "__main__":
    rc1 = run([NODE, VUE_TSC, "--noEmit"], "vue-tsc")
    if rc1 != 0:
        sys.exit(rc1)
    rc2 = run([NODE, VITE, "build"], "vite build")
    sys.exit(rc2)
