#!/usr/bin/env python3
"""Логотип amxpy — пиксельная «a» из змеи — из одной сетки 16×16.

    python3 scripts/make-logo.py

Пишет:
    docs/assets/logo.svg          значок на тёмной плитке: фавикон и шапка сайта
    docs/assets/logo-banner.svg   значок + «amxpy» пиксельным шрифтом: README
    editors/vscode/icon.png       128×128 для расширения VS Code (Marketplace принимает только PNG)
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PALETTE = {
    "L": "#c6f432",  # тело
    "M": "#84cc16",  # тень на чаше
    "D": "#3f6212",  # контур
    "K": "#0c0c0e",  # зрачок
    "W": "#ffffff",  # глаз
    "R": "#f43f5e",  # язык
}
TILE = "#0c0c0e"
PAD = 2  # отступ сетки от края плитки, в пикселях сетки

LOGO = [
    "................",
    "................",
    "....DDDDDDDD....",
    "...DLLLLLLLLD...",
    "..DLWKLLLLLLLD..",
    "RRDLLLDDDDDDLLD.",
    "..DDDD.....DLLD.",
    "...........DLLD.",
    ".....DDDDDDDLLD.",
    "...DDLLLLLLLLLD.",
    "..DLLMMMMMMMLLD.",
    "..DLLD.....DLLD.",
    "..DLLD....DLLLD.",
    "..DLLMMMMMLLLLDD",
    "...DDLLLLLLDDLLD",
    ".....DDDDDD..DD.",
]

# Пиксельный шрифт: строки 0–1 пусты, x-высота — 2–6, нижние выносные — 7–8
FONT = {
    "a": [".....", ".....", ".LLL.", "....L", ".LLLL", "L...L", ".LLLL", ".....", "....."],
    "m": [".....", ".....", "LL.L.", "L.L.L", "L.L.L", "L.L.L", "L.L.L", ".....", "....."],
    "x": [".....", ".....", "L...L", ".L.L.", "..L..", ".L.L.", "L...L", ".....", "....."],
    "p": [".....", ".....", "LLLL.", "L...L", "L...L", "L...L", "LLLL.", "L....", "L...."],
    "y": [".....", ".....", "L...L", "L...L", "L...L", "L...L", ".LLLL", "....L", ".LLL."],
}


def pixels(rows: list[str], dx: int = 0, dy: int = 0) -> str:
    """SVG-квадраты 1×1; соседние пиксели одного цвета в строке склеиваются в один rect."""
    out = []
    for y, row in enumerate(rows):
        x = 0
        while x < len(row):
            ch = row[x]
            run = 1
            while x + run < len(row) and row[x + run] == ch:
                run += 1
            if ch in PALETTE:
                out.append(f'<rect x="{x + dx}" y="{y + dy}" width="{run}" height="1" fill="{PALETTE[ch]}"/>')
            x += run
    return "".join(out)


def logo_svg() -> str:
    size = len(LOGO) + PAD * 2
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" shape-rendering="crispEdges">'
        f'<rect width="{size}" height="{size}" rx="3.6" fill="{TILE}"/>{pixels(LOGO, PAD, PAD)}</svg>\n'
    )


def word(text: str) -> list[str]:
    rows = [""] * 9
    for i, ch in enumerate(text):
        for r in range(9):
            rows[r] += FONT[ch][r] + ("." if i < len(text) - 1 else "")
    return rows


def banner_svg() -> str:
    """Плашка: значок 16×16 и «amxpy» высотой 9 пикселей, выровненные по центру."""
    text = word("amxpy")
    gap, margin = 4, 4
    width = margin + len(LOGO[0]) + gap + len(text[0]) + margin
    height = margin + len(LOGO) + margin
    ty = margin + (len(LOGO) - 9) // 2 + 1
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width * 12}" '
        f'height="{height * 12}" shape-rendering="crispEdges">'
        f'<rect width="{width}" height="{height}" rx="3" fill="{TILE}"/>'
        f"{pixels(LOGO, margin, margin)}{pixels(text, margin + len(LOGO[0]) + gap, ty)}</svg>\n"
    )


def png(size: int = 128) -> bytes:
    """PNG без зависимостей: плитка со скруглёнными углами, пиксели сетки — целые квадраты."""
    grid = len(LOGO) + PAD * 2
    scale = size // grid
    offset = (size - grid * scale) // 2
    radius = 3.6 * scale

    def rgba(hex_color: str) -> bytes:
        return bytes(int(hex_color[i : i + 2], 16) for i in (1, 3, 5)) + b"\xff"

    tile, empty = rgba(TILE), b"\0\0\0\0"
    lo, hi = offset, offset + grid * scale
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # фильтр строки: None
        for x in range(size):
            if not (lo <= x < hi and lo <= y < hi):
                raw += empty
                continue
            cx = min(max(x + 0.5, lo + radius), hi - radius)  # ближайшая точка «внутреннего» прямоугольника
            cy = min(max(y + 0.5, lo + radius), hi - radius)
            if (x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2 > radius**2:
                raw += empty
                continue
            gx, gy = (x - lo) // scale - PAD, (y - lo) // scale - PAD
            ch = LOGO[gy][gx] if 0 <= gy < len(LOGO) and 0 <= gx < len(LOGO[0]) else "."
            raw += rgba(PALETTE[ch]) if ch in PALETTE else tile

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8 бит, RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")


def main() -> None:
    assert len(LOGO) == 16 and all(len(row) == 16 for row in LOGO), "сетка логотипа — 16×16"
    (ROOT / "docs" / "assets" / "logo.svg").write_text(logo_svg(), encoding="utf-8")
    (ROOT / "docs" / "assets" / "logo-banner.svg").write_text(banner_svg(), encoding="utf-8")
    (ROOT / "editors" / "vscode" / "icon.png").write_bytes(png())
    print("logo.svg, logo-banner.svg, icon.png")


if __name__ == "__main__":
    main()
