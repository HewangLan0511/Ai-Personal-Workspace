"""临时：打印冻结基线关注的样式文件 sha256[:16]。"""
import hashlib
from pathlib import Path

ROOT = Path(r"C:\Users\baiyu\Desktop\Personal Workspace")
FILES = [
    "ui/src/styles/base.css",
    "ui/src/styles/tokens.css",
    "ui/src/styles/motion-tokens.css",
    "ui/src/components/ui/primitives.css",
    "ui/src/components/ModeBar.vue",
    "ui/src/workspace/boundary.ts",
    "ui/src/workspace/snapshot.ts",
    "core/database/schema.sql",
]

for rel in FILES:
    p = ROOT / rel
    if p.exists():
        print(rel, hashlib.sha256(p.read_bytes()).hexdigest()[:16])
    else:
        print(rel, "(missing)")
