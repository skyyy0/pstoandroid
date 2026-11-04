"""Minimal PNG decoder (8-bit, non-interlaced) used by the asset packer.

glTF stores albedo textures as PNG or JPEG.  The engine wants raw RGBA8 for a
direct GL upload, so PNG files are decoded here without pulling in Pillow.  JPEG
is rejected with an actionable message: export textures as PNG in Blender.
"""

from __future__ import annotations

import struct
import zlib
from typing import Tuple


class PngError(Exception):
    pass


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def decode_png(data: bytes) -> Tuple[int, int, bytes]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PngError("not a PNG file (JPEG textures must be converted to PNG first)")
    pos = 8
    width = height = bit_depth = color_type = interlace = 0
    idat = bytearray()
    palette = b""
    trns = b""
    while pos + 8 <= len(data):
        length, chunk_type = struct.unpack_from(">I4s", data, pos)
        pos += 8
        payload = data[pos:pos + length]
        pos += length + 4  # skip CRC
        if chunk_type == b"IHDR":
            width, height, bit_depth, color_type, _comp, _filt, interlace = struct.unpack(
                ">IIBBBBB", payload
            )
        elif chunk_type == b"PLTE":
            palette = payload
        elif chunk_type == b"tRNS":
            trns = payload
        elif chunk_type == b"IDAT":
            idat += payload
        elif chunk_type == b"IEND":
            break
    if width <= 0 or height <= 0:
        raise PngError("PNG has no valid IHDR")
    if bit_depth != 8:
        raise PngError(f"unsupported PNG bit depth {bit_depth} (need 8)")
    if interlace:
        raise PngError("interlaced PNG is not supported; re-export without interlacing")
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        raise PngError(f"unsupported PNG color type {color_type}")

    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(width * height * 4)
    previous = bytearray(stride)
    cursor = 0
    for row in range(height):
        if cursor >= len(raw):
            raise PngError("truncated PNG image data")
        filter_type = raw[cursor]
        cursor += 1
        line = bytearray(raw[cursor:cursor + stride])
        if len(line) != stride:
            raise PngError("truncated PNG scanline")
        cursor += stride
        for i in range(stride):
            left = line[i - channels] if i >= channels else 0
            up = previous[i]
            up_left = previous[i - channels] if i >= channels else 0
            if filter_type == 0:
                pass
            elif filter_type == 1:
                line[i] = (line[i] + left) & 0xFF
            elif filter_type == 2:
                line[i] = (line[i] + up) & 0xFF
            elif filter_type == 3:
                line[i] = (line[i] + ((left + up) >> 1)) & 0xFF
            elif filter_type == 4:
                line[i] = (line[i] + _paeth(left, up, up_left)) & 0xFF
            else:
                raise PngError(f"unknown PNG filter {filter_type}")
        previous = line
        base = row * width * 4
        for x in range(width):
            if color_type == 0:
                value = line[x]
                out[base + x * 4 + 0] = value
                out[base + x * 4 + 1] = value
                out[base + x * 4 + 2] = value
                out[base + x * 4 + 3] = 255
            elif color_type == 4:
                value, alpha = line[x * 2], line[x * 2 + 1]
                out[base + x * 4 + 0] = value
                out[base + x * 4 + 1] = value
                out[base + x * 4 + 2] = value
                out[base + x * 4 + 3] = alpha
            elif color_type == 2:
                idx = x * 3
                out[base + x * 4 + 0] = line[idx]
                out[base + x * 4 + 1] = line[idx + 1]
                out[base + x * 4 + 2] = line[idx + 2]
                out[base + x * 4 + 3] = 255
            elif color_type == 6:
                idx = x * 4
                out[base + x * 4:base + x * 4 + 4] = line[idx:idx + 4]
            else:  # palette
                index = line[x]
                if palette:
                    out[base + x * 4 + 0] = palette[index * 3]
                    out[base + x * 4 + 1] = palette[index * 3 + 1]
                    out[base + x * 4 + 2] = palette[index * 3 + 2]
                alpha = trns[index] if index < len(trns) else 255
                out[base + x * 4 + 3] = alpha
    return width, height, bytes(out)


def encode_png(width: int, height: int, rgba: bytes) -> bytes:
    """Small PNG writer, used by tests and texture previews."""
    if len(rgba) != width * height * 4:
        raise PngError("rgba size mismatch")

    def chunk(tag: bytes, payload: bytes) -> bytes:
        body = tag + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = bytearray()
    for row in range(height):
        raw.append(0)
        start = row * width * 4
        raw += rgba[start:start + width * 4]
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + chunk(b"IEND", b"")
    )
