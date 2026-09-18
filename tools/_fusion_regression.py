"""UI-FUSION-REAL 回归编排：TECH-02 + C1~C7 串行（单跑口径，嵌套连跑不作为判定依据）。"""
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(r"C:\Users\baiyu\Desktop\Personal Workspace\tools")
PY = r"C:\Users\baiyu\.workbuddy\binaries\python\versions\3.13.12\python.exe"

SCRIPTS = [
    "verify_tech02_workspace.py",
    "verify_tech07c.py",
    "verify_tech07c2.py",
    "verify_tech07c3.py",
    "verify_tech07c4.py",
    "verify_tech07c5.py",
    "verify_tech07c6.py",
    "verify_tech07c7.py",
]

if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    results = []
    for name in SCRIPTS:
        if only and only not in name:
            continue
        t0 = time.time()
        r = subprocess.run([PY, str(TOOLS / name)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           cwd=str(TOOLS), timeout=1200)
        out = (r.stdout or "") + (r.stderr or "")
        last = "\n".join(out.strip().splitlines()[-4:])
        print(f"### {name}: exit={r.returncode} ({time.time()-t0:.0f}s)")
        if last:
            print(last)
        results.append((name, r.returncode))
    print("\n==== SUMMARY ====")
    for name, rc in results:
        print(("PASS " if rc == 0 else "FAIL ") + name)
    sys.exit(0 if all(rc == 0 for _, rc in results) else 1)
