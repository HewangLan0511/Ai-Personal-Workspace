#!/usr/bin/env python3
"""一次性批量复跑（本批次验收用）。不进验收链，只为把结果收拢到一处。"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = r"C:\Users\baiyu\.workbuddy\binaries\python\versions\3.13.12\python.exe"

SCRIPTS = [
    "verify_tech01.py",
    "verify_tech02_workspace.py",
    "verify_tech04.py",
    "verify_tech05c.py",
    "verify_tech05d.py",
    "verify_tech06a.py",
    "verify_tech06b.py",
    "verify_skin_engine.py",
    "verify_tech07c.py",
    "verify_tech07c2.py",
    "verify_tech07c3.py",
    "verify_tech07c4.py",
    "verify_tech07c5.py",
    "verify_tech07c6.py",
]


def main() -> int:
    only = sys.argv[1:]
    out_lines: list[str] = []
    for name in SCRIPTS:
        if only and not any(o in name for o in only):
            continue
        t0 = time.time()
        try:
            r = subprocess.run([PY, str(ROOT / "tools" / name)], cwd=str(ROOT),
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=1800)
            out = (r.stdout or "") + (r.stderr or "")
            rc = r.returncode
        except subprocess.TimeoutExpired:
            out, rc = "TIMEOUT", -9
        fails = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
        summ = [ln for ln in out.splitlines() if ln.startswith("===") and "汇总" in ln]
        head = f"### {name}  exit={rc}  ({time.time() - t0:.0f}s)"
        out_lines.append(head)
        out_lines.extend("    " + s for s in summ)
        out_lines.extend("    " + f for f in fails)
        if rc != 0 and not fails:
            tail = "\n".join(out.strip().splitlines()[-6:])
            out_lines.append("    (无 FAIL 行，尾部输出) " + tail.replace("\n", " | "))
        print("\n".join(out_lines[-8:]), flush=True)
    log = ROOT / "tools" / "_batch5_verify_all.log"
    log.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    print(f"\n→ {log}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
