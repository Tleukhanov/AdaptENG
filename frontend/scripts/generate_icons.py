#!/usr/bin/env python3
"""Generate the PWA icons (blue rounded square + white "A") without external tools.

The artwork mirrors `components/Logo.tsx`: a 34x34 plate with the same linear
gradient and the same "A" strokes, so the installed app icon matches the in-app
logo. Only the Python standard library is used (zlib + struct), which keeps the
script runnable on CI images that have no ImageMagick / librsvg / Pillow.

Usage:
    python3 frontend/scripts/generate_icons.py

Output (relative to frontend/):
    public/icons/icon-192.png
    public/icons/icon-512.png
    public/icons/apple-touch-icon.png
"""

from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent
OUT_DIR = FRONTEND / "public" / "icons"

#: Gradient stops from the in-app logo (top-left -> bottom-right).
GRADIENT_START = (0x1D, 0x4E, 0xD8)  # #1d4ed8
GRADIENT_END = (0x38, 0xBD, 0xF8)  # #38bdf8
PLATE_RADIUS = 0.22  # corner radius, relative to the icon side
STROKE_HALF = 2.6 / 34 / 2  # logo stroke width 2.6 on a 34px plate
SUPERSAMPLING = 4

#: "A" geometry in a 0..1 unit square, taken from the logo paths.
SEGMENTS = (
    ((10.2 / 34, 24.2 / 34), (17.0 / 34, 9.8 / 34)),
    ((17.0 / 34, 9.8 / 34), (23.8 / 34, 24.2 / 34)),
    ((13.2 / 34, 20.1 / 34), (20.8 / 34, 20.1 / 34)),
)


def _segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _gradient(x: float, y: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, (x + y) / 2))
    return tuple(round(a + (b - a) * t) for a, b in zip(GRADIENT_START, GRADIENT_END))


def _inside_plate(x: float, y: float) -> bool:
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        return False
    r = PLATE_RADIUS
    cx = min(max(x, r), 1.0 - r)
    cy = min(max(y, r), 1.0 - r)
    return math.hypot(x - cx, y - cy) <= r


def _inside_glyph(x: float, y: float) -> bool:
    return any(
        _segment_distance(x, y, ax, ay, bx, by) <= STROKE_HALF for (ax, ay), (bx, by) in SEGMENTS
    )


def render(size: int) -> list[bytes]:
    """Render one icon and return raw RGBA rows."""
    samples = SUPERSAMPLING * SUPERSAMPLING
    inv = 1.0 / (size * SUPERSAMPLING)
    rows: list[bytes] = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            r = g = b = a_cover = 0
            for sy in range(SUPERSAMPLING):
                for sx in range(SUPERSAMPLING):
                    x = (px * SUPERSAMPLING + sx + 0.5) * inv
                    y = (py * SUPERSAMPLING + sy + 0.5) * inv
                    if not _inside_plate(x, y):
                        continue
                    a_cover += 1
                    if _inside_glyph(x, y):
                        r, g, b = r + 255, g + 255, b + 255
                    else:
                        cr, cg, cb = _gradient(x, y)
                        r, g, b = r + cr, g + cg, b + cb
            if a_cover == 0:
                row += b"\x00\x00\x00\x00"
            else:
                row += bytes(
                    (
                        round(r / a_cover),
                        round(g / a_cover),
                        round(b / a_cover),
                        round(255 * a_cover / samples),
                    )
                )
        rows.append(bytes(row))
    return rows


def write_png(path: Path, size: int, rows: list[bytes]) -> None:
    raw = b"".join(b"\x00" + row for row in rows)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    print(f"wrote {path.relative_to(FRONTEND)} ({size}x{size}, {len(png)} bytes)")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size, name in ((192, "icon-192.png"), (512, "icon-512.png"), (180, "apple-touch-icon.png")):
        write_png(OUT_DIR / name, size, render(size))


if __name__ == "__main__":
    main()
