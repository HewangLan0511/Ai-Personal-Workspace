#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 `core/icons/` 下的应用图标集（纯标准库，无需 Pillow / tauri icon）。

为什么需要它（REVIEW-003 L-011 / 04 验收项 7「能出安装包」）：
  `core/tauri.conf.json` 打开 `bundle.active` 后必须提供图标，否则 `tauri build` 失败。
  原先只有一张 32×32 的占位图，Windows 安装器（NSIS/MSI）图标质量不足。
  本脚本产出：`icon.png`（256×256，Linux/高 DPI）+ `icon.ico`（16/32/48/64/128 BMP + 256 PNG）。

用法：
  python tools/make_icons.py            # 重新生成
  python tools/make_icons.py --check    # 只校验现有图标

设计：深色圆角底 + 2×2 蓝色卡片（对应 Dashboard 的 Widget 网格）。
"""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

ICON_DIR = Path(__file__).resolve().parent.parent / "core" / "icons"
PNG_SIZES = (16, 32, 48, 64, 128, 256)
BMP_SIZES = (16, 32, 48, 64, 128)   # 小尺寸用 BMP（兼容性最好）
ICO_PNG_SIZES = (256,)              # 256 用 PNG 载荷（Vista+）

BG = (31, 41, 55)        # #1f2937
CARD_A = (59, 130, 246)  # #3b82f6
CARD_B = (96, 165, 250)  # #60a5fa
SS = 4                   # 超采样倍数（抗锯齿）


def _rounded_alpha(x: float, y: float, size: float, radius: float) -> bool:
    """点 (x, y) 是否在 size×size、圆角 radius 的圆角矩形内。"""
    cx = min(max(x, radius), size - radius)
    cy = min(max(y, radius), size - radius)
    dx, dy = x - cx, y - cy
    return dx * dx + dy * dy <= radius * radius


def render_rgba(size: int) -> bytes:
    """渲染 size×size RGBA 像素（超采样抗锯齿），返回自顶向下的 RGBA 字节流。"""
    hi = size * SS
    # 高分辨率布尔图：0=透明 1=底 2=亮卡 3=暗卡
    grid = bytearray(hi * hi)
    bg_r = hi * 0.22
    margin = hi * 0.24
    gap = hi * 0.07
    cell = (hi - 2 * margin - gap) / 2.0
    cr = cell * 0.28

    def in_cell(x: float, y: float, ox: float, oy: float) -> bool:
        return _rounded_alpha(x - ox, y - oy, cell, cr)

    for yy in range(hi):
        y = yy + 0.5
        row = yy * hi
        for xx in range(hi):
            x = xx + 0.5
            if not _rounded_alpha(x, y, hi, bg_r):
                continue
            v = 1
            ox0, oy0 = margin, margin
            ox1, oy1 = margin + cell + gap, margin
            ox2, oy2 = margin, margin + cell + gap
            ox3, oy3 = margin + cell + gap, margin + cell + gap
            # 左上大卡（视觉重心）：占 1 格但用亮色
            if in_cell(x, y, ox0, oy0):
                v = 2
            elif in_cell(x, y, ox1, oy1) or in_cell(x, y, ox2, oy2) or in_cell(x, y, ox3, oy3):
                v = 3
            grid[row + xx] = v

    # 降采样到 size×size
    out = bytearray()
    total = SS * SS
    for y in range(size):
        for x in range(size):
            r = g = b = a = 0
            for dy in range(SS):
                base = (y * SS + dy) * hi + x * SS
                for dx in range(SS):
                    v = grid[base + dx]
                    if v == 0:
                        continue
                    if v == 1:
                        cr_, cg_, cb_ = BG
                    elif v == 2:
                        cr_, cg_, cb_ = CARD_A
                    else:
                        cr_, cg_, cb_ = CARD_B
                    r += cr_
                    g += cg_
                    b += cb_
                    a += 255
            out += bytes((r // total, g // total, b // total, a // total))
    return bytes(out)


def png_bytes(size: int, rgba: bytes) -> bytes:
    raw = bytearray()
    stride = size * 4
    for y in range(size):
        raw.append(0)  # filter: None
        raw += rgba[y * stride:(y + 1) * stride]

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def bmp_entry(size: int, rgba: bytes) -> bytes:
    """ICO 内的 BMP 载荷：BITMAPINFOHEADER（高度=2×）+ BGRA 自底向上 + AND 掩码。"""
    header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
    xor = bytearray()
    for y in range(size - 1, -1, -1):
        for x in range(size):
            i = (y * size + x) * 4
            r, g, b, a = rgba[i:i + 4]
            xor += bytes((b, g, r, a))
    mask_row = ((size + 31) // 32) * 4  # 每行按 4 字节对齐
    and_mask = bytes(mask_row * size)
    return header + bytes(xor) + and_mask


def build_ico(pngs: dict[int, bytes], bmps: dict[int, bytes]) -> bytes:
    entries = []
    blobs = bytearray()
    offset = 6 + 16 * (len(bmps) + len(pngs))
    for size in sorted(set(bmps) | set(pngs)):
        blob = bmps.get(size) or pngs[size]
        w = 0 if size >= 256 else size
        h = 0 if size >= 256 else size
        entries.append(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset))
        blobs += blob
        offset += len(blob)
    return struct.pack("<HHH", 0, 1, len(entries)) + b"".join(entries) + bytes(blobs)


def generate() -> int:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    pngs: dict[int, bytes] = {}
    for s in sorted(set(PNG_SIZES)):
        pngs[s] = png_bytes(s, render_rgba(s))
    # 主 PNG 用最大尺寸
    main = max(PNG_SIZES)
    (ICON_DIR / "icon.png").write_bytes(pngs[main])
    bmps = {s: bmp_entry(s, render_rgba(s)) for s in sorted(BMP_SIZES)}
    (ICON_DIR / "icon.ico").write_bytes(build_ico({s: pngs[s] for s in ICO_PNG_SIZES}, bmps))
    print(f"[icons] icon.png  {main}x{main}  {(ICON_DIR / 'icon.png').stat().st_size} bytes")
    print(f"[icons] icon.ico  entries={sorted(set(BMP_SIZES) | set(ICO_PNG_SIZES))}  "
          f"{(ICON_DIR / 'icon.ico').stat().st_size} bytes")
    return 0


def check() -> int:
    ok = True
    p = ICON_DIR / "icon.png"
    i = ICON_DIR / "icon.ico"
    if not p.exists():
        print(f"[icons] 缺失 {p}")
        ok = False
    else:
        b = p.read_bytes()
        w, h = struct.unpack(">II", b[16:24])
        print(f"[icons] {p.name} {w}x{h} {len(b)} bytes")
        ok &= b[:8] == b"\x89PNG\r\n\x1a\n" and w >= 256
    if not i.exists():
        print(f"[icons] 缺失 {i}")
        ok = False
    else:
        b = i.read_bytes()
        cnt = struct.unpack("<H", b[4:6])[0]
        sizes = []
        for n in range(cnt):
            off = 6 + n * 16
            bw, bh = b[off], b[off + 1]
            sizes.append(256 if bw == 0 else bw)
        print(f"[icons] {i.name} {len(b)} bytes, entries={sizes}")
        ok &= cnt >= 4 and 256 in sizes
    print("[icons] " + ("校验通过" if ok else "校验不通过"))
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 core/icons 图标集")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    return check() if a.check else generate()


if __name__ == "__main__":
    raise SystemExit(main())
