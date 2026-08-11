"""Generate the h4xtor-share application icon (PNG and Windows ICO).

The design is a teal rounded square with a bold white "H" mark on a
transparent background. Icon files are generated with only the standard
library so the build has no extra image dependencies.

Run from the repository root:

    python packaging/make_icon.py
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

ACCENT = (0, 209, 178, 255)
MARK = (234, 242, 251, 255)

ICO_SIZES = (16, 32, 48, 256)


def rounded_square_mask(size: int, radius: int, margin: int) -> list[list[bool]]:
    mask: list[list[bool]] = []
    x0, y0 = margin, margin
    x1, y1 = size - margin, size - margin
    for y in range(size):
        row = []
        for x in range(size):
            inside = x0 <= x <= x1 and y0 <= y <= y1
            if inside:
                for cx, cy in (
                    (x0 + radius, y0 + radius),
                    (x1 - radius, y0 + radius),
                    (x0 + radius, y1 - radius),
                    (x1 - radius, y1 - radius),
                ):
                    if (cx == x0 + radius and x < cx and y < cy) or (
                        cx == x1 - radius and x > cx and y < cy
                    ) or (
                        cx == x0 + radius and x < cx and y > cy
                    ) or (
                        cx == x1 - radius and x > cx and y > cy
                    ):
                        inside = (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius
                        break
            row.append(inside)
        mask.append(row)
    return mask


def mark_pixel(size: int, x: int, y: int) -> bool:
    scale = size / 256.0
    left, right = int(84 * scale), int(124 * scale)
    mid_left, mid_right = int(132 * scale), int(172 * scale)
    top, bottom = int(76 * scale), int(180 * scale)
    bar_top, bar_bottom = int(118 * scale), int(142 * scale)
    return (
        (left <= x <= right and top <= y <= bottom)
        or (mid_left <= x <= mid_right and top <= y <= bottom)
        or (left <= x <= mid_right and bar_top <= y <= bar_bottom)
    )


def render_rgba(size: int) -> bytes:
    mask = rounded_square_mask(size, max(1, size // 5), max(1, size // 11))
    raw = bytearray()
    for y in range(size):
        raw.append(0)
        for x in range(size):
            if mark_pixel(size, x, y):
                raw.extend(MARK)
            elif mask[y][x]:
                raw.extend(ACCENT)
            else:
                raw.extend((0, 0, 0, 0))
    return bytes(raw)


def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + chunk_type
        + data
        + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
    )


def encode_png(size: int) -> bytes:
    raw = render_rgba(size)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    payload = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib.compress(raw, 9))
        + png_chunk(b"IEND", b"")
    )
    return payload


def write_ico(path: Path) -> None:
    images = [encode_png(size) for size in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = bytearray()
    offset = 6 + 16 * len(images)
    for size, data in zip(ICO_SIZES, images, strict=True):
        entries.extend(
            struct.pack(
                "<BBBBHHII",
                size if size < 256 else 0,
                size if size < 256 else 0,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        offset += len(data)
    payload = header + bytes(entries) + b"".join(images)
    path.write_bytes(payload)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_ico(OUT_DIR / "h4xtor-share.ico")
    (OUT_DIR / "h4xtor-share.png").write_bytes(encode_png(256))
    print(f"Wrote {OUT_DIR / 'h4xtor-share.ico'} and {OUT_DIR / 'h4xtor-share.png'}")


if __name__ == "__main__":
    main()
