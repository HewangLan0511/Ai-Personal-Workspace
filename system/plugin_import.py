#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""插件导入包（zip）安全解包（阶段9，12 §A1 / 契约 3.4 /plugin/import）。

归属说明：zip 解包是"文件 IO + 归档格式解析"，属通用系统能力（02 §2.4 归 Python；
Rust 侧解 zip 需引入新 crate，本机 crates.io 不可达）。安全边界仍然在 Rust core：
本模块**只解包到临时目录并回读 manifest 摘要**，不注册、不授权 —— 注册与权限
判定一律由 core `plugins::install` 完成（trust boundary 在 core）。

安全要点（防 zip-slip）：
  - 解包前逐项校验归档内路径，拒绝绝对路径与 `..` 穿越；
  - 解包目标固定在 `<data_dir>/tmp/plugin-import/` 下，随机子目录；
  - 仅标准库实现（zipfile），与 sidecar 零依赖约束一致。
"""

from __future__ import annotations

import json
import os
import time
import uuid
import zipfile


class ImportError(Exception):
    """可预期的导入失败（客户端错误，sidecar 回 400）。"""


def import_zip(zip_path: str, data_dir: str) -> dict:
    """解包插件 zip 到临时目录，返回 { dir, pluginId, name, version, fileCount }。"""
    if not zip_path:
        raise ImportError("需要 zipPath")
    if not os.path.isfile(zip_path):
        raise ImportError(f"zip 不存在：{zip_path}")
    if os.path.getsize(zip_path) > 50 * 1024 * 1024:
        raise ImportError("zip 超过 50MB 上限（数据轻量化）")

    target_root = os.path.join(data_dir, "tmp", "plugin-import")
    os.makedirs(target_root, exist_ok=True)
    target = os.path.join(target_root, f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}")
    os.makedirs(target, exist_ok=True)

    # 先做路径安全检查，再统一解包（zipfile 原生不防穿越，必须自查）。
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        if len(names) > 2000:
            raise ImportError("zip 内文件数超过 2000（疑似恶意包）")
        for name in names:
            if name.startswith("/") or "\\" in name and ".." in name:
                raise ImportError(f"归档内非法路径：{name}")
            normalized = name.replace("\\", "/")
            parts = [p for p in normalized.split("/") if p not in ("", ".")]
            if any(p == ".." for p in parts):
                raise ImportError(f"归档内路径穿越（..）：{name}")
        zf.extractall(target)

    manifest_path = os.path.join(target, "manifest.json")
    if not os.path.isfile(manifest_path):
        # 允许单层目录包裹（zip 里套一层 <pluginId>/）：向下找一层 manifest.json
        for entry in os.listdir(target):
            candidate = os.path.join(target, entry, "manifest.json")
            if os.path.isfile(candidate):
                manifest_path = candidate
                break
        else:
            _rm(target)
            raise ImportError("zip 中未找到 manifest.json")

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as exc:
        _rm(target)
        raise ImportError(f"manifest.json 解析失败：{exc}") from exc

    # 摘要字段缺失让 core 的 Manifest::validate 报权威错误，这里只做最外层可读性检查。
    plugin_id = str(manifest.get("pluginId") or "")
    if not plugin_id:
        _rm(target)
        raise ImportError("manifest.json 缺少 pluginId")

    return {
        "dir": os.path.dirname(manifest_path),
        "tempRoot": target,
        "pluginId": plugin_id,
        "name": str(manifest.get("name") or ""),
        "version": str(manifest.get("version") or ""),
        "fileCount": len(names),
    }


def cleanup(temp_root: str) -> None:
    """core 安装完成（复制进 plugins 目录）后清理临时解包目录。失败静默。"""
    if temp_root and os.path.isdir(temp_root):
        _rm(temp_root)


def _rm(path: str) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
