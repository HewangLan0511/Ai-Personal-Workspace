#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""已安装软件扫描 + 图标提取（阶段2 / 05-阶段指令-软件管理）。

为什么在 Python 而不是 Rust：
  - 05 §禁止事项：「不要在 UI 线程做注册表扫描（会卡界面）——放 Python sidecar 或 Rust 异步任务」；
  - ADR-001 只把**进程启动 / 窗口控制**收归 Rust，注册表与文件属性读取不在其范围；
  - 02 §2.4 边界表把「系统 API」归 Python，符合架构分工。

零第三方依赖：仅标准库（winreg / ctypes / zlib / struct / hashlib）。
图标 PNG 自行编码（zlib 属标准库），不引入 Pillow —— 与 sidecar「stdlib-only」约束一致。
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import struct
import zlib
from ctypes import wintypes
from typing import Any

# ---------------------------------------------------------------------------
# 常量

# SHGetFileInfo 标志
SHGFI_ICON = 0x000000100
SHGFI_LARGEICON = 0x000000000
SHGFI_SMALLICON = 0x000000001

# 图标缓存尺寸（05 §技术要点：建议 64×64 和 128×128 两档）
ICON_SIZES = (128, 64)

_UNINSTALL_PATHS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
)


# ---------------------------------------------------------------------------
# 已安装软件扫描（05 §技术要点：注册表 32/64 位视图 + 去重）

def _read_values(key) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        count = __import__("winreg").QueryInfoKey(key)[1]
    except OSError:
        return out
    winreg = __import__("winreg")
    for i in range(count):
        try:
            name, value, _ = winreg.EnumValue(key, i)
            out[name] = value
        except OSError:
            continue
    return out


def _exe_from_display_icon(raw: Any) -> str | None:
    """从 DisplayIcon 里解析出可执行文件路径。

    DisplayIcon 的形态很杂：`"C:\\a\\b.exe,0"`、`C:\\a\\b.exe`、`C:\\a\\icon.ico`。
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    s = raw.strip()
    if s.startswith('"'):
        end = s.find('"', 1)
        s = s[1:end] if end > 0 else s.strip('"')
    else:
        # 未加引号时，末尾的 ",0" 是图标索引
        s = s.rsplit(",", 1)[0] if s.count(",") == 1 and s.rsplit(",", 1)[1].strip().isdigit() else s
    s = s.strip().strip('"').strip()
    if s.lower().endswith((".exe", ".lnk")):
        return s
    return None


def scan_installed() -> list[dict[str, Any]]:
    """枚举注册表 Uninstall 项，返回去重后的已安装软件列表。

    去重规则（05 §技术要点）：`DisplayName + InstallLocation` 相同视为同一软件。
    扫描结果**只展示给用户勾选**，本函数不写库（单一写入者：写库只能走 core）。
    """
    try:
        import winreg
    except ImportError:  # pragma: no cover - 非 Windows
        return []

    results: dict[tuple[str, str], dict[str, Any]] = {}
    views = (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    )

    for hive, view in views:
        for sub in _UNINSTALL_PATHS:
            try:
                with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ | view) as key:
                    count = winreg.QueryInfoKey(key)[0]
                    for i in range(count):
                        try:
                            with winreg.OpenKey(key, winreg.EnumKey(key, i)) as sk:
                                vals = _read_values(sk)
                        except OSError:
                            continue

                        name = vals.get("DisplayName")
                        if not name or not str(name).strip():
                            continue
                        # 系统组件/更新补丁不是"软件"，过滤掉（否则列表全是噪音）
                        if vals.get("SystemComponent") in (1, "1"):
                            continue
                        if vals.get("ParentKeyName"):
                            continue

                        loc = str(vals.get("InstallLocation") or "")
                        dedup = (str(name).strip(), loc.strip().lower())
                        if dedup in results:
                            continue

                        exe = _exe_from_display_icon(vals.get("DisplayIcon"))
                        results[dedup] = {
                            "name": str(name).strip(),
                            "path": exe or "",
                            "installLocation": loc,
                            "publisher": vals.get("Publisher") or "",
                            "version": vals.get("DisplayVersion") or "",
                            # 无 exe 路径的条目用户仍可看到，但无法直接启动
                            "launchable": bool(exe),
                        }
            except OSError:
                # 该视图/路径不存在（32 位系统没有 WOW6432Node 等）—— 正常情况
                continue

    items = list(results.values())
    # 可启动的排前面，其次按名称
    items.sort(key=lambda x: (not x["launchable"], x["name"].lower()))
    return items


# ---------------------------------------------------------------------------
# 文件属性 / 图标提取

class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [
        ("hIcon", wintypes.HANDLE),
        ("iIcon", ctypes.c_int),
        ("dwAttributes", wintypes.DWORD),
        ("szDisplayName", wintypes.WCHAR * 260),
        ("szTypeName", wintypes.WCHAR * 80),
    ]


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _user32():
    u = ctypes.WinDLL("user32", use_last_error=True)
    u.PrivateExtractIconsW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
        wintypes.UINT, wintypes.UINT,
    ]
    u.PrivateExtractIconsW.restype = wintypes.UINT
    u.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(_ICONINFO)]
    u.GetIconInfo.restype = wintypes.BOOL
    u.DestroyIcon.argtypes = [wintypes.HICON]
    u.DestroyIcon.restype = wintypes.BOOL
    return u


def _shell32():
    """`SHGetFileInfoW` 在 **shell32.dll**，不是 user32 —— 放错 DLL 会 AttributeError。"""
    s = ctypes.WinDLL("shell32", use_last_error=True)
    s.SHGetFileInfoW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_SHFILEINFOW),
        wintypes.UINT, wintypes.UINT,
    ]
    s.SHGetFileInfoW.restype = ctypes.c_void_p
    return s


def _grab_hicon(path: str, size: int):
    """取 HICON（调用方负责 DestroyIcon）。返回 None 表示失败。"""
    user32 = _user32()
    hicon = wintypes.HICON()
    iconid = wintypes.UINT()
    n = user32.PrivateExtractIconsW(
        path, 0, size, size, ctypes.byref(hicon), ctypes.byref(iconid), 1, 0
    )
    if n and hicon:
        return user32, hicon

    # 回退：系统图标（尺寸由系统决定，通常 32×32；后续放大使用）
    shell32 = _shell32()
    info = _SHFILEINFOW()
    got = shell32.SHGetFileInfoW(path, 0, ctypes.byref(info), ctypes.sizeof(info),
                                 SHGFI_ICON | SHGFI_LARGEICON)
    if got and info.hIcon:
        return user32, info.hIcon
    return None


def _hicon_to_rgba(user32, hicon) -> tuple[int, int, bytes] | None:
    """HICON → (w, h, RGBA bytes)。失败返回 None。"""
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    gdi32.GetObjectW.argtypes = [wintypes.HGDIOBJ, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.POINTER(_BITMAPINFOHEADER), wintypes.UINT,
    ]
    # ⚠️ 这些**必须**显式声明 argtypes：未声明时 ctypes 按 C int（32 位）传参，
    # 64 位句柄会被截断并抛 OverflowError —— 本函数第一版正是栽在此处。
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL

    info = _ICONINFO()
    if not user32.GetIconInfo(hicon, ctypes.byref(info)):
        return None
    # 单色图标（hbmColor 为空）本实现不支持 —— 由调用方降级到默认图标
    if not info.hbmColor:
        if info.hbmMask:
            gdi32.DeleteObject(info.hbmMask)
        return None

    bm = _BITMAP()
    if not gdi32.GetObjectW(info.hbmColor, ctypes.sizeof(bm), ctypes.byref(bm)):
        gdi32.DeleteObject(info.hbmColor)
        if info.hbmMask:
            gdi32.DeleteObject(info.hbmMask)
        return None

    w, h = int(bm.bmWidth), int(bm.bmHeight)
    hdr = _BITMAPINFOHEADER()
    hdr.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
    hdr.biWidth = w
    hdr.biHeight = -h  # 负值 = top-down，省得自己翻转
    hdr.biPlanes = 1
    hdr.biBitCount = 32
    hdr.biCompression = 0  # BI_RGB

    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = gdi32.CreateCompatibleDC(None)
    lines = gdi32.GetDIBits(hdc, info.hbmColor, 0, h, buf, ctypes.byref(hdr), 0)
    gdi32.DeleteDC(hdc)
    gdi32.DeleteObject(info.hbmColor)
    if info.hbmMask:
        gdi32.DeleteObject(info.hbmMask)
    if not lines:
        return None

    src = bytearray(buf.raw)
    # Windows 图标是**预乘 alpha** 的 BGRA：先反预乘，否则半透明边缘会发黑
    out = bytearray(len(src))
    for i in range(0, len(src), 4):
        b, g, r, a = src[i], src[i + 1], src[i + 2], src[i + 3]
        if a and a != 255:
            b = min(255, b * 255 // a)
            g = min(255, g * 255 // a)
            r = min(255, r * 255 // a)
        out[i], out[i + 1], out[i + 2], out[i + 3] = r, g, b, a
    return w, h, bytes(out)


def _resize_rgba(rgba: bytes, w: int, h: int, tw: int, th: int) -> bytes:
    """最近邻缩放（图标是离散图形，最近邻比双线性更锐利且实现简单）。"""
    if w == tw and h == th:
        return rgba
    out = bytearray(tw * th * 4)
    for y in range(th):
        sy = min(h - 1, y * h // th)
        for x in range(tw):
            sx = min(w - 1, x * w // tw)
            si = (sy * w + sx) * 4
            di = (y * tw + x) * 4
            out[di:di + 4] = rgba[si:si + 4]
    return bytes(out)


def _png_bytes(w: int, h: int, rgba: bytes) -> bytes:
    """编码 PNG（RGBA8，无滤波）。zlib 属标准库，不引第三方。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    stride = w * 4
    raw = bytearray()
    for y in range(h):
        raw.append(0)  # filter type 0 (None)
        raw += rgba[y * stride:(y + 1) * stride]

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8bit / RGBA
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def _file_description(path: str) -> str | None:
    """读 exe 的 FileDescription（版本资源），失败返回 None。"""
    try:
        ver = ctypes.WinDLL("version", use_last_error=True)
        ver.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
        ver.GetFileVersionInfoSizeW.restype = wintypes.DWORD
        ver.GetFileVersionInfoW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p
        ]
        ver.GetFileVersionInfoW.restype = wintypes.BOOL
        ver.VerQueryValueW.argtypes = [
            ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(wintypes.UINT),
        ]
        ver.VerQueryValueW.restype = wintypes.BOOL

        size = ver.GetFileVersionInfoSizeW(path, None)
        if not size:
            return None
        buf = ctypes.create_string_buffer(size)
        if not ver.GetFileVersionInfoW(path, 0, size, buf):
            return None

        ptr = ctypes.c_void_p()
        ln = wintypes.UINT()
        if not ver.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(ln)):
            return None
        if not ptr.value:
            return None
        words = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16))
        lang, codepage = words[0], words[1]

        sub = f"\\StringFileInfo\\{lang:04x}{codepage:04x}\\FileDescription"
        if not ver.VerQueryValueW(buf, sub, ctypes.byref(ptr), ctypes.byref(ln)):
            return None
        if not ptr.value or not ln.value:
            return None
        text = ctypes.wstring_at(ptr.value, ln.value).strip("\x00").strip()
        return text or None
    except OSError:
        return None


def probe(path: str, out_dir: str) -> dict[str, Any]:
    """探测一个可执行文件：返回自动补全用的 `name` 与缓存后的 `iconPath`。

    永不抛异常 —— 任何子步骤失败都降级（name 回退文件名、icon 回退 None），
    因为"自动补全"是增强项，不该阻塞用户添加软件（02 §2.7 局部失败不拖垮整体）。
    """
    result: dict[str, Any] = {"name": os.path.splitext(os.path.basename(path))[0],
                              "iconPath": None}
    if not os.path.isfile(path):
        return result

    if path.lower().endswith((".exe", ".dll")):
        desc = _file_description(path)
        if desc:
            result["name"] = desc

    try:
        os.makedirs(out_dir, exist_ok=True)
        digest = hashlib.sha1(path.lower().encode("utf-8")).hexdigest()[:16]
        grabbed = _grab_hicon(path, max(ICON_SIZES))
        if grabbed:
            user32, hicon = grabbed
            try:
                got = _hicon_to_rgba(user32, hicon)
            finally:
                user32.DestroyIcon(hicon)
            if got:
                w, h, rgba = got
                target = os.path.join(out_dir, digest + ".png")
                # 输出最大档；需要小档时由前端缩放显示（避免缓存两份文件）
                side = max(ICON_SIZES)
                scaled = _resize_rgba(rgba, w, h, side, side)
                with open(target, "wb") as fh:
                    fh.write(_png_bytes(side, side, scaled))
                result["iconPath"] = target
    except Exception:  # noqa: BLE001 —— 图标是增强项，失败即降级
        result["iconPath"] = None

    return result
