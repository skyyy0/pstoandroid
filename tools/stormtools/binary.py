"""Little/big endian binary helpers shared by the stormtools parsers.

The retail CC2/CriWare data is mostly big endian; the runtime packages that the
engine consumes (``.smesh`` / ``.sanm``) are little endian so that Android ARM64
can map them almost directly.  Both directions are supported here.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List, Optional


class BinaryError(Exception):
    """Raised when a buffer is too small or a magic does not match."""


@dataclass
class Reader:
    data: bytes
    pos: int = 0
    endian: str = "<"

    # -- primitives ---------------------------------------------------------
    def seek(self, pos: int) -> None:
        if pos < 0 or pos > len(self.data):
            raise BinaryError(f"seek out of range: {pos} (size {len(self.data)})")
        self.pos = pos

    def skip(self, count: int) -> None:
        self.seek(self.pos + count)

    def _unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        if self.pos + size > len(self.data):
            raise BinaryError(f"read past end at {self.pos} (+{size}, size {len(self.data)})")
        value = struct.unpack_from(fmt, self.data, self.pos)
        self.pos += size
        return value[0] if len(value) == 1 else value

    def u8(self) -> int:
        return self._unpack("B")

    def s8(self) -> int:
        return self._unpack("b")

    def u16(self) -> int:
        return self._unpack(self.endian + "H")

    def s16(self) -> int:
        return self._unpack(self.endian + "h")

    def u32(self) -> int:
        return self._unpack(self.endian + "I")

    def s32(self) -> int:
        return self._unpack(self.endian + "i")

    def i32(self) -> int:
        """Alias kept because the package readers use signed 32-bit offsets."""
        return self._unpack(self.endian + "i")

    def u64(self) -> int:
        return self._unpack(self.endian + "Q")

    def s64(self) -> int:
        return self._unpack(self.endian + "q")

    def f32(self) -> float:
        return self._unpack(self.endian + "f")

    def f32s(self, count: int) -> List[float]:
        return list(self._unpack(self.endian + f"{count}f"))

    def bytes(self, count: int) -> bytes:
        if self.pos + count > len(self.data):
            raise BinaryError(f"read past end at {self.pos} (+{count})")
        out = self.data[self.pos:self.pos + count]
        self.pos += count
        return out

    def fixed_str(self, size: int) -> str:
        raw = self.bytes(size)
        return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")

    def cstr(self, limit: int = 4096) -> str:
        end = self.data.find(b"\x00", self.pos)
        if end < 0:
            raise BinaryError(f"unterminated string at {self.pos}")
        if end - self.pos > limit:
            raise BinaryError(f"string at {self.pos} exceeds {limit} bytes")
        raw = self.data[self.pos:end]
        self.pos = end + 1
        return raw.decode("utf-8", "replace")

    def magic(self, expected: bytes) -> None:
        got = self.bytes(len(expected))
        if got != expected:
            raise BinaryError(f"bad magic {got!r}, expected {expected!r}")

    @property
    def remaining(self) -> int:
        return len(self.data) - self.pos


@dataclass
class Writer:
    endian: str = "<"
    _buf: Optional[bytearray] = None

    def __post_init__(self) -> None:
        if self._buf is None:
            self._buf = bytearray()

    def _pack(self, fmt: str, *values) -> "Writer":
        self._buf += struct.pack(self.endian + fmt, *values)
        return self

    def u8(self, v: int) -> "Writer":
        return self._pack("B", v)

    def u16(self, v: int) -> "Writer":
        return self._pack("H", v)

    def u32(self, v: int) -> "Writer":
        return self._pack("I", v)

    def i32(self, v: int) -> "Writer":
        return self._pack("i", v)

    def f32(self, v: float) -> "Writer":
        return self._pack("f", v)

    def f32s(self, values) -> "Writer":
        return self._pack(f"{len(values)}f", *values)

    def raw(self, data: bytes) -> "Writer":
        self._buf += data
        return self

    def cstr(self, text: str, size: int = 0) -> "Writer":
        raw = text.encode("utf-8")
        if size:
            raw = raw[:size].ljust(size, b"\x00")
        else:
            raw += b"\x00"
        self._buf += raw
        return self

    def align(self, alignment: int, fill: int = 0) -> "Writer":
        pad = (-len(self._buf)) % alignment
        self._buf += bytes([fill]) * pad
        return self

    @property
    def size(self) -> int:
        return len(self._buf)

    def bytes(self) -> bytes:
        return bytes(self._buf)


def fnv1a32(text: str) -> int:
    """Stable bone/material name hash used by the runtime packages."""
    h = 0x811C9DC5
    for byte in text.lower().encode("utf-8"):
        h ^= byte
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment
