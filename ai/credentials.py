#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""凭据管理（08 §2 / 红线 V1）
=================================

**铁律**：API Key 只存**系统凭据库**（Windows Credential Manager），
数据库里只存**引用名**（如 `pw/deepseek/default`），界面只显示 `sk-****abcd`。

## 实现取向

sidecar 是 stdlib-only（不能依赖 keyring 库）。Windows 上通过
`advapi32.dll` 的 CredRead/CredWrite/CredDelete 直接访问凭据库
—— 这正是 `keyring` 库内部做的事，只是我们去掉了那层依赖。

非 Windows 平台（开发机可能是 mac/linux）降级为**进程内存**存储，
并**明确标记 not persistent**（`backend()` 会返回 `memory`），
避免"以为存了其实没存"这类静默失败。

## 红线自查
- 明文 key 绝不写 SQLite、绝不写日志、绝不出现在返回值里（只回掩码）
- 读取只在发起请求的瞬间发生，用完即弃（不缓存到全局变量）

### ⚠️ Windows 凭据库的容量限制（实测踩到）
`CredWriteW` 的 `CredentialBlob` 上限是 **512 字节**。这是个真实约束：
超长 key（或未来存 JWT / OAuth token）会静默写入失败。
本实现显式检查长度并抛错，不吞掉。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass


CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168
MAX_BLOB_BYTES = 512  # Windows CredentialBlob 硬限制


@dataclass
class Credential:
    username: str
    password: str


class _CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_byte)),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.POINTER(_CREDENTIAL_ATTRIBUTEW)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class CredentialStore:
    """凭据库抽象。Windows 走系统凭据库，其他平台走内存（并如实报告）。"""

    def __init__(self) -> None:
        self._is_windows = sys.platform == "win32"
        self._mem: dict[str, Credential] = {}
        if self._is_windows:
            self._advapi = ctypes.WinDLL("advapi32", use_last_error=True)
            self._bind()

    # ---- 能力报告（UI / 验收据此判断是否真持久化） --------------------

    def backend(self) -> str:
        return "windows-credential-manager" if self._is_windows else "memory"

    def persistent(self) -> bool:
        return self._is_windows

    # ---- 读写 ---------------------------------------------------------

    def set(self, ref: str, secret: str, *, username: str = "apikey") -> None:
        """写入凭据。`ref` 是引用名（如 `pw/deepseek/default`）。"""
        if not ref:
            raise ValueError("凭据引用名不能为空")
        if not secret:
            raise ValueError("密钥不能为空")
        if len(secret.encode("utf-8")) > MAX_BLOB_BYTES:
            raise ValueError(
                f"密钥超过 Windows 凭据库上限（{MAX_BLOB_BYTES} 字节），"
                f"实际 {len(secret.encode('utf-8'))} 字节"
            )

        if not self._is_windows:
            self._mem[ref] = Credential(username=username, password=secret)
            return

        blob = secret.encode("utf-16-le")
        cred = _CREDENTIALW()
        cred.Flags = 0
        cred.Type = CRED_TYPE_GENERIC
        cred.TargetName = ref
        cred.Comment = "Personal Workspace API credential"
        cred.CredentialBlobSize = len(blob)
        cred.CredentialBlob = ctypes.cast(
            ctypes.create_string_buffer(blob, len(blob)),
            ctypes.POINTER(ctypes.c_byte),
        )
        cred.Persist = CRED_PERSIST_LOCAL_MACHINE
        cred.AttributeCount = 0
        cred.Attributes = None
        cred.TargetAlias = None
        cred.UserName = username

        ok = self._advapi.CredWriteW(ctypes.byref(cred), 0)
        if not ok:
            raise OSError(ctypes.get_last_error(), f"写入凭据库失败：{ref}")

    def get(self, ref: str) -> Credential | None:
        """读取凭据。不存在返回 None（不抛错 —— 未配置是正常状态）。"""
        if not self._is_windows:
            return self._mem.get(ref)

        ptr = ctypes.POINTER(_CREDENTIALW)()
        ok = self._advapi.CredReadW(ref, CRED_TYPE_GENERIC, 0, ctypes.byref(ptr))
        if not ok:
            code = ctypes.get_last_error()
            if code == ERROR_NOT_FOUND:
                return None
            raise OSError(code, f"读取凭据库失败：{ref}")

        try:
            cred = ptr.contents
            size = cred.CredentialBlobSize
            raw = ctypes.string_at(cred.CredentialBlob, size) if size else b""
            password = raw.decode("utf-16-le", errors="replace")
            username = cred.UserName or "apikey"
            return Credential(username=username, password=password)
        finally:
            self._advapi.CredFree(ptr)

    def delete(self, ref: str) -> bool:
        """删除凭据。返回是否真的删掉了（不存在返回 False）。"""
        if not self._is_windows:
            return self._mem.pop(ref, None) is not None

        ok = self._advapi.CredDeleteW(ref, CRED_TYPE_GENERIC, 0)
        if not ok:
            code = ctypes.get_last_error()
            if code == ERROR_NOT_FOUND:
                return False
            raise OSError(code, f"删除凭据失败：{ref}")
        return True

    def exists(self, ref: str) -> bool:
        return self.get(ref) is not None

    # ---- 红线辅助：掩码 -----------------------------------------------

    @staticmethod
    def mask(secret: str | None) -> str:
        """把密钥变成 `sk-****abcd` 形式供 UI 显示。**任何返回值都不得含完整 key。**"""
        if not secret:
            return ""
        if len(secret) <= 8:
            return "*" * len(secret)
        return f"{secret[:3]}****{secret[-4:]}"

    def _bind(self) -> None:
        a = self._advapi
        a.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        ]
        a.CredReadW.restype = wintypes.BOOL
        a.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        a.CredWriteW.restype = wintypes.BOOL
        a.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        a.CredDeleteW.restype = wintypes.BOOL
        a.CredFree.argtypes = [ctypes.c_void_p]
        a.CredFree.restype = None


# 单例（凭据库是系统资源，全局一个即可）
_store: CredentialStore | None = None


def store() -> CredentialStore:
    global _store
    if _store is None:
        _store = CredentialStore()
    return _store


def ref_for(provider_id: str, slot: str = "default") -> str:
    """生成凭据引用名（契约：数据库只存这个字符串，不存 key）。"""
    return f"pw/{provider_id}/{slot}"


__all__ = ["CredentialStore", "Credential", "store", "ref_for", "MAX_BLOB_BYTES"]
