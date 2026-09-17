"""V0.1-FINAL 全量回归 runner：9 套串行，独立日志。"""
import re
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
SUITES = [
    ("tech02", "verify_tech02_workspace.py"),
    ("c1", "verify_tech07c.py"),
    ("c2", "verify_tech07c2.py"),
    ("c3", "verify_tech07c3.py"),
    ("c4", "verify_tech07c4.py"),
    ("c5", "verify_tech07c5.py"),
    ("c6", "verify_tech07c6.py"),
    ("c7", "verify_tech07c7.py"),
    ("contracts", "verify_contracts.py"),
]


def main() -> int:
    summary = []
    for name, script in SUITES:
        t0 = time.time()
        p = subprocess.run(
            [sys.executable, str(TOOLS / script)], cwd=ROOT,
            capture_output=True, text=True, timeout=5400)
        dt = time.time() - t0
        out = p.stdout or ""
        m = re.findall(r"(\d+)/(\d+)\s*通过", out)
        last = m[-1] if m else ("?", "?")
        line = f"{name}: exit={p.returncode} {last[0]}/{last[1]} {dt:.0f}s"
        print(line, flush=True)
        summary.append(line)
        (TOOLS / f"_v01_reg_{name}.log").write_text(out[-20000:], encoding="utf-8")
    print("SUMMARY")
    print("\n".join(summary))
    bad = [s for s in summary if "exit=0" not in s or "/?" in s]
    ok = [s for s in summary if s.split(":")[1].split("exit=")[0].strip()
          and "exit=0" in s]
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
