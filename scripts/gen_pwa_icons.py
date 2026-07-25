"""Generate the PWA icons committed under web/static/icons/.

Stdlib-only (struct + zlib) raw-RGBA PNG writer — no Pillow dependency.
Each icon is a rounded square filled with the brand primary color
(--primary: #22d3ee from web/src/app.css) on a transparent canvas.

Usage: python scripts/gen_pwa_icons.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

PRIMARY = (0x22, 0xD3, 0xEE)  # --primary (dark theme) in web/src/app.css
OUT_DIR = Path(__file__).resolve().parent.parent / "web" / "static" / "icons"
SIZES = (192, 512)
CORNER_RADIUS_RATIO = 0.18  # rounded-look corners, as a fraction of icon size


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + tag
        + data
        + struct.pack(">I", zlib.crc32(tag + data))
    )


def _rounded_square_rgba(size: int) -> bytes:
    """Raw RGBA pixels: solid PRIMARY square with rounded transparent corners."""
    radius = size * CORNER_RADIUS_RATIO
    r2 = radius * radius
    opaque = bytes((*PRIMARY, 255))
    clear = b"\x00\x00\x00\x00"
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            # Distance check only matters inside the four corner boxes.
            cx = radius if x < radius else (size - radius if x > size - radius else None)
            cy = radius if y < radius else (size - radius if y > size - radius else None)
            if cx is not None and cy is not None:
                dx, dy = x + 0.5 - cx, y + 0.5 - cy
                row += opaque if dx * dx + dy * dy <= r2 else clear
            else:
                row += opaque
        rows.append(row)
    # Each scanline is prefixed with filter type 0 (None).
    return b"".join(b"\x00" + bytes(row) for row in rows)


def write_png(path: Path, size: int) -> None:
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    idat = zlib.compress(_rounded_square_rgba(size), 9)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", ihdr)
        + _png_chunk(b"IDAT", idat)
        + _png_chunk(b"IEND", b"")
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in SIZES:
        out = OUT_DIR / f"icon-{size}.png"
        write_png(out, size)
        print(f"wrote {out} ({size}x{size})")


if __name__ == "__main__":
    main()
