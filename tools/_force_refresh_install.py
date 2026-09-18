"""UI-FUSION-FORCE：把最新构建刷新到正式安装位置（NSIS 静默升级）。

背景：用户看到的"旧 UI"来自 `D:\\Personal Workspace` 里的旧二进制（V0.1-RELEASE 那版），
不是源码里的第二套 UI。本脚本负责把新构建装上去，并核对安装产物确实是新构建（大小/时间）。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(r"C:\Users\baiyu\Desktop\Personal Workspace")
BUNDLE = ROOT / "core" / "target" / "release" / "bundle" / "nsis"
BUILT_EXE = ROOT / "core" / "target" / "release" / "personal-workspace-core.exe"
INSTALLER = BUNDLE / "Personal Workspace_0.1.0_x64-setup.exe"
APP_EXE = "personal-workspace-core.exe"

CANDIDATES = [
    Path("D:/Personal Workspace"),
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Personal Workspace",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Personal Workspace",
    Path(os.environ.get("ProgramFiles", "")) / "Personal Workspace",
]


def find_installed():
    for d in CANDIDATES:
        exe = d / APP_EXE
        if exe.exists():
            return exe
    return None


def info(p: Path):
    st = p.stat()
    return {"path": str(p), "size": st.st_size,
            "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}


def main() -> int:
    out = {"installer": info(INSTALLER), "built": info(BUILT_EXE)}
    # 杀掉正在运行的旧实例（否则安装器无法覆盖）
    subprocess.run(["taskkill", "/F", "/IM", APP_EXE], capture_output=True)
    time.sleep(2)
    before = find_installed()
    out["before"] = info(before) if before else None

    r = subprocess.run([str(INSTALLER), "/S"], timeout=600)
    out["installer_exit"] = r.returncode
    time.sleep(6)

    after = find_installed()
    out["after"] = info(after) if after else None
    if after:
        out["refreshed"] = (after.stat().st_size == BUILT_EXE.stat().st_size)
    (ROOT / "tools" / "_force_install_result.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if after else 2


if __name__ == "__main__":
    sys.exit(main())
