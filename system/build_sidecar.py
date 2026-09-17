#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 sidecar 打成单文件，并按 Tauri 2 的 externalBin 约定命名。

背景（04 §5 / REVIEW-003 L-015）：
  阶段1 要求"打包时用 PyInstaller 打成单文件，作为 Tauri sidecar 资源"。
  本脚本负责这一步，并保证产物名与 `core/tauri.conf.json` 的 `bundle.externalBin`
  约定一致 —— Tauri 2 要求 sidecar 文件名带**目标三元组**后缀。

用法：
  python system/build_sidecar.py              # 构建（缺 PyInstaller 会给出安装提示）
  python system/build_sidecar.py --if-needed  # 产物比源码新则跳过（供 tauri beforeBuildCommand 用）
  python system/build_sidecar.py --check      # 只检查产物是否已就绪，不构建

解释器选择（REVIEW-005）：
  PyInstaller 是**构建期**依赖，未打进 runtime。若当前解释器没装 PyInstaller，
  可用环境变量 `PW_PYTHON` 指向一个已装 PyInstaller 的解释器（与 core 的
  `PW_PYTHON` 约定同名，见 core/src/sidecar/mod.rs）。

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
import os
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
BUILD_SCRIPT = Path(__file__).resolve()


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


def build_python() -> str:
    """跑 PyInstaller 的解释器。默认当前解释器，可用 `PW_PYTHON` 覆盖。

    PyInstaller 是构建期依赖，不应作为 runtime 依赖装进全局环境；
    开发机常把它放在 venv 里，因此需要一个显式的指定入口。
    """
    return os.environ.get("PW_PYTHON") or sys.executable


def pyinstaller_available(python: str) -> bool:
    try:
        proc = subprocess.run(
            [python, "-c", "import PyInstaller"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode == 0
    except Exception:
        return False


def is_fresh() -> bool:
    """产物是否比源码新（供 `--if-needed` 用）。

    比较对象：sidecar 入口 + 本构建脚本 + **业务目录（ai/ 与 system/win/）**。
    后者是阶段5 补的：PyInstaller 产物里同时嵌入了 `.py` 模块**与** `.md` 数据，
    只比入口文件会得出"没改过"的假结论 —— 改了提示词模板却拿旧产物交付。
    """
    out = artifact_path()
    if not out.exists():
        return False
    sources = [p for p in (ENTRY, BUILD_SCRIPT) if p.exists()]
    for extra in (REPO_ROOT / "ai", REPO_ROOT / "system" / "win"):
        if extra.is_dir():
            sources.extend(
                p for p in extra.rglob("*")
                if p.is_file() and "__pycache__" not in p.parts
            )
    if not sources:
        return True
    newest = max(p.stat().st_mtime for p in sources)
    return out.stat().st_mtime >= newest


def build() -> int:
    if not ENTRY.exists():
        print(f"[sidecar] 入口不存在：{ENTRY}", file=sys.stderr)
        return 2

    python = build_python()
    if not pyinstaller_available(python):
        print(
            f"[sidecar] 解释器 {python} 缺少 PyInstaller。请择一：\n"
            "    1) python -m pip install pyinstaller\n"
            "    2) 设 PW_PYTHON 指向已装 PyInstaller 的解释器\n"
            "（runtime 侧仍是 stdlib-only，PyInstaller 只用于打包。）",
            file=sys.stderr,
        )
        return 2

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ★ 数据文件必须显式声明：PyInstaller 只自动收集"被 import 的 .py"，
    #   **不会**收集 `.md`。漏掉 `ai/prompt/` 的症状只在**打包态**出现：
    #   安装版里该目录为空 → `/ai/chat` 报「模板不存在：consult_default」
    #   → 发行版 AI 对话整体不可用，而开发态（跑源码）一切正常。
    #   典型的"只在发行版炸、验收脚本还测不到"的坑，故在此显式带上。
    #   分隔符：Windows 用 `;`、POSIX 用 `:`。
    prompt_dir = REPO_ROOT / "ai" / "prompt"
    if not prompt_dir.is_dir():
        print(f"[sidecar] 提示词目录不存在：{prompt_dir}", file=sys.stderr)
        return 2
    data_sep = ";" if sys.platform == "win32" else ":"

    with tempfile.TemporaryDirectory(prefix="pw-sidecar-build-") as tmp:
        cmd = [
            python,
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
            # 提示词模板（08 §4：模板集中管理，运行时按 PROMPT_DIR 读取）
            "--add-data",
            f"{prompt_dir}{data_sep}ai/prompt",
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
    parser.add_argument(
        "--if-needed",
        action="store_true",
        help="产物已存在且不比源码旧时跳过构建（tauri beforeBuildCommand 用）",
    )
    args = parser.parse_args()
    if args.check:
        return 0 if check() else 1
    if args.if_needed and is_fresh():
        check()
        print("[sidecar] 产物已是最新，跳过构建。")
        return 0
    return build()


if __name__ == "__main__":
    raise SystemExit(main())
