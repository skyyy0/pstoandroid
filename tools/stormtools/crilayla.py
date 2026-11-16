"""CRILAYLA decompressor (CriWare per-entry compression used inside CPK).

Layout of one compressed frame (everything little-endian):

    0x00  char[8]  "CRILAYLA"
    0x08  u32      uncompressed_size   (excluding the 0x100 byte prefix)
    0x0C  u32      compressed_size     (bytes of bit stream that follow)

    then ``compressed_size`` bytes of bit stream, then 0x100 bytes of raw
    prefix data.  Decompressed output = prefix + decoded tail, and the tail is
    *built backwards*: the bit stream is consumed from its last byte, most
    significant bit first, and every decoded byte is written from the end of the
    output towards the prefix.

Two kinds of pattern exist:

* literal: ``1`` bit = 0, then 8 bits of data;
* back-reference: ``1`` bit = 1, 13 bits of ``distance - 3``, then a length that
  starts at 3 and is extended by 2, 3, 5 and then 8 bit chunks for as long as a
  chunk is all ones.

References: the 0x10/0x100 framing and the bit grammar are described by
unknownbrackets (XeNTaX / "Valkyria Chronicles 3 file formats"), repeated in
CriPakTools, CriFsV2Lib and pes-file-tools.  This implementation was written from
that description; it has not been validated against a retail Naruto archive yet
(see docs/FORMATS_RETAIL.md).
"""

from __future__ import annotations

import struct
from typing import Optional

MAGIC = b"CRILAYLA"
HEADER_SIZE = 0x10
PREFIX_SIZE = 0x100
MIN_MATCH = 3
MAX_DISTANCE = (1 << 13) + MIN_MATCH


class CrilaylaError(ValueError):
    pass


def is_crilayla(data: bytes) -> bool:
    return len(data) >= HEADER_SIZE and data[:8] == MAGIC


def header(data: bytes) -> "tuple[int, int]":
    """Return ``(uncompressed_size, compressed_size)`` from a frame header."""
    if not is_crilayla(data):
        raise CrilaylaError("not a CRILAYLA frame (bad or missing magic)")
    return struct.unpack_from("<II", data, 8)


class _BitReader:
    """Bits are pulled MSB-first from the payload read back-to-front."""

    __slots__ = ("payload", "index", "bits", "count")

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.index = 0
        self.bits = 0
        self.count = 0

    def read(self, count: int) -> int:
        while self.count < count:
            if self.index >= len(self.payload):
                raise CrilaylaError("unexpected end of CRILAYLA bit stream")
            self.bits = (self.bits << 8) | self.payload[len(self.payload) - 1 - self.index]
            self.count += 8
            self.index += 1
        self.count -= count
        value = self.bits >> self.count
        self.bits &= (1 << self.count) - 1
        return value


def _read_length(reader: _BitReader) -> int:
    length = MIN_MATCH
    for width in (2, 3, 5):
        chunk = reader.read(width)
        length += chunk
        if chunk + 1 != (1 << width):
            return length
    while True:
        chunk = reader.read(8)
        length += chunk
        if chunk != 0xFF:
            return length


def decompress(data: bytes, expected_size: Optional[int] = None) -> bytes:
    """Decompress one CRILAYLA frame.

    ``expected_size`` is the CPK entry's ``ExtractSize``; when given it is
    checked against the decoded length so a silently corrupt frame cannot reach
    the engine.
    """
    uncompressed_size, compressed_size = header(data)
    stream_end = HEADER_SIZE + compressed_size
    if stream_end + PREFIX_SIZE > len(data):
        raise CrilaylaError(
            f"frame is {len(data)} bytes but header declares "
            f"{compressed_size} compressed + {PREFIX_SIZE} prefix bytes"
        )
    if expected_size is not None and expected_size != uncompressed_size + PREFIX_SIZE:
        raise CrilaylaError(
            f"ExtractSize {expected_size} does not match frame "
            f"({uncompressed_size} + {PREFIX_SIZE} bytes)"
        )

    prefix = data[stream_end:stream_end + PREFIX_SIZE]
    out = bytearray(PREFIX_SIZE + uncompressed_size)
    out[:PREFIX_SIZE] = prefix

    reader = _BitReader(data[HEADER_SIZE:stream_end])
    cursor = len(out) - 1
    while cursor >= PREFIX_SIZE:
        if reader.read(1) == 0:
            out[cursor] = reader.read(8)
            cursor -= 1
            continue
        distance = reader.read(13) + MIN_MATCH
        length = _read_length(reader)
        if cursor + distance >= len(out):
            raise CrilaylaError("back-reference points past the decoded tail")
        # The reference is recomputed from the moving cursor, so a match can
        # overlap the bytes it just wrote (that is how runs are stored).
        for _ in range(length):
            out[cursor] = out[cursor + distance]
            cursor -= 1
            if cursor < PREFIX_SIZE:
                break

    return bytes(out)
