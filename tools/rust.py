#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rust 命令执行辅助（本机 PATH 里没有 cargo，且 shell 的 grep/head 不可靠）。

用法：
  python tools/rust.py check
  python tools/rust.py test
  python tools/rust.py build --release
  python tools/rust.py <任意 cargo 子命令...> [-- <透传>]

背景：这台机器的 bash shim 损坏（`dirname: command not found`），
且 `/sys/` 里的 cargo 不在 Python 的 PATH。故统一由此脚本定位 cargo 并执行，
避免每次手拼绝对路径。
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, "core")

CARGO_CANDIDATES = [
    os.path.expanduser(r"~/.cargo/bin/cargo.exe"),
    os.path.expanduser(
        r"~/.rustup/toolchains/stable-x86_64-pc-windows-msvc/bin/cargo.exe"
    ),
]


def find_cargo() -> str:
    for c in CARGO_CANDIDATES:
        if os.path.isfile(c):
            return c
    raise SystemExit("找不到 cargo，请确认 Rust 工具链已安装")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        args = ["check"]

    env = dict(os.environ)
    env["PATH"] = (
        os.path.expanduser(r"~/.cargo/bin")
        + os.pathsep
        + os.path.expanduser(r"~/.rustup/toolchains/stable-x86_64-pc-windows-msvc/bin")
        + os.pathsep
        + env.get("PATH", "")
    )

    cmd = [find_cargo(), *args]
    print(f"[rust.py] cwd={CORE}")
    print(f"[rust.py] cmd={' '.join(cmd)}")
    print("-" * 68)
    proc = subprocess.run(cmd, cwd=CORE, env=env)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
