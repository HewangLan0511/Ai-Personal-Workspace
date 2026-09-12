#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 sidecar 打成单文件，并按 Tauri 2 的 externalBin 约定命名。

背景（04 §5 / REVIEW-003 L-015）：
  阶段1 要求"打包时用 PyInstaller 打成单文件，作为 Tauri sidecar 资源"。
  本脚本负责这一步，并保证产物名与 `core/tauri.conf.json` 的 `bundle.externalBin`
  约定一致 —— Tauri 2 要求 sidecar 文件名带**目标三元组**后缀。

用法：
  python system/build_sidecar.py            # 构建（缺 PyInstaller 会给出安装提示）
  python system/build_sidecar.py --check    # 只检查产物是否已就绪，不构建

产物：
  core/binaries/service-<target-triple>[.exe]
  例：core/binaries/service-x86_64-pc-windows-msvc.exe

⚠️ 关键坑：**不能加 `--noconsole`**。
  core 通过读取 sidecar 的 **stdout 首行** 拿随机端口（`--announce` 协议）。
  Windows 下 windowed（无控制台）程序没有可用的 stdout，加了 `--noconsole`
  端口就永远传不回来 —— sidecar 会"启动成功但 core 拿不到端口"。
"""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENTRY = REPO_ROOT / "system" / "service.py"
OUT_DIR = REPO_ROOT / "core" / "binaries"
BIN_STEM = "service"


def target_triple() -> str:
    """推断 Rust 目标三元组（与 `rustc -vV` 的 host 对齐）。"""
    machine = platform.machine().lower()
    arch = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "arm64": "aarch64",
        "aarch64": "aarch64",
        "x86": "i686",
    }.get(machine, machine)
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def artifact_path() -> Path:
    suffix = ".exe" if sys.platform == "win32" else ""
    return OUT_DIR / f"{BIN_STEM}-{target_triple()}{suffix}"


def check() -> bool:
    out = artifact_path()
    if out.exists():
        size_mb = out.stat().st_size / (1024 * 1024)
        print(f"[sidecar] 已就绪：{out}  ({size_mb:.1f} MB)")
        return True
    print(f"[sidecar] 未找到产物：{out}")
    print("[sidecar] 运行 `python system/build_sidecar.py` 构建。")
    return False


def build() -> int:
    if not ENTRY.exists():
        print(f"[sidecar] 入口不存在：{ENTRY}", file=sys.stderr)
        return 2

    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print(
            "[sidecar] 缺少 PyInstaller。请先安装构建依赖：\n"
            "    python -m pip install pyinstaller\n"
            "（runtime 侧仍是 stdlib-only，PyInstaller 只用于打包。）",
            file=sys.stderr,
        )
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pw-sidecar-build-") as tmp:
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--clean",
            "--name",
            BIN_STEM,
            # 注意：不加 --noconsole（见文件头说明）
            "--distpath",
            tmp,
            "--workpath",
            str(Path(tmp) / "build"),
            "--specpath",
            tmp,
            str(ENTRY),
        ]
        print("[sidecar] " + " ".join(cmd))
        proc = subprocess.run(cmd, check=False)
        if proc.returncode != 0:
            print(f"[sidecar] PyInstaller 失败，退出码 {proc.returncode}", file=sys.stderr)
            return proc.returncode

        suffix = ".exe" if sys.platform == "win32" else ""
        built = Path(tmp) / f"{BIN_STEM}{suffix}"
        if not built.exists():
            print(f"[sidecar] 未找到构建产物：{built}", file=sys.stderr)
            return 3

        target = artifact_path()
        shutil.copy2(built, target)
        print(f"[sidecar] 已产出：{target}  ({target.stat().st_size / 1048576:.1f} MB)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="构建 Personal Workspace sidecar")
    parser.add_argument("--check", action="store_true", help="只检查产物是否存在")
    args = parser.parse_args()
    if args.check:
        return 0 if check() else 1
    return build()


if __name__ == "__main__":
    raise SystemExit(main())
