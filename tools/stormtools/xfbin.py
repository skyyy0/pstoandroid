"""Reader for CyberConnect2 ``.xfbin`` (NUCC) containers.

An XFBIN is the retail asset container of the Storm games: one file holds
several typed chunks (model, texture, animation, binary/script, audio...) and an
index that names them.  Everything structural is **big-endian**, which is
opposite to the CriWare CPK that wraps it.

Layout implemented here (offsets from the start of the file):

    0x00  char[4]  "NUCC"
    0x04  u32      xfbin version
    0x08  u16      flags.unk00
    0x0A  char[2]  flags.language
    0x0C  u16      flags.unk04
    0x0E  u16      flags.unk06

    0x10  chunk header of the index chunk: u32 size, u32 map_index, u16 version, u16 unk

    nuccIndex right after that header:
          u32 chunk_type_count, u32 chunk_type_size
          u32 file_path_count,  u32 file_path_size
          u32 chunk_name_count, u32 chunk_name_size
          u32 chunk_map_count,  u32 chunk_map_size
          u32 chunk_map_indices_count, u32 extra_map_indices_count
          chunk_type_count NUL-terminated strings   (chunk_type_size bytes total)
          file_path_count  NUL-terminated strings   (file_path_size bytes total)
          chunk_name_count NUL-terminated strings   (chunk_name_size bytes total)
          align to 4
          chunk_map_count * { u32 chunk_type_index, u32 file_path_index, u32 chunk_name_index }
          extra_map_indices_count * { u32 chunk_name_index, u32 chunk_map_index }
          chunk_map_indices_count * u32

    then every following chunk: 12 byte header (u32 size, u32 map_index, u16
    version, u16 unk) followed by ``size`` bytes of payload.  ``map_index`` is
    looked up in the index and yields the chunk's type, path and name.

Reference: the 010 Editor templates of KojoBailey/NUCC-010-Template-Library
(``xfbin.bt``, ``nuccChunk.bt``, ``nuccIndex.bt``) and mosamadeeb/xfbin_lib.
No retail Naruto archive has been parsed with this code yet, so every place
where the structure had to be inferred (the chunk-map indirection, alignment,
size semantics) is reported through ``Xfbin.warnings`` instead of being assumed
silently.  See docs/FORMATS_RETAIL.md.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

MAGIC = b"NUCC"
HEADER_SIZE = 0x10
CHUNK_HEADER_SIZE = 12
INDEX_FIELDS = 10

#: Chunk type -> file extension, so extracted payloads can be handed to the
#: matching community/importer tool without guessing.
CHUNK_EXTENSIONS: Dict[str, str] = {
    "nuccChunkModel": ".nud",
    "nuccChunkTexture": ".nut",
    "nuccChunkAnm": ".anm",
    "nuccChunkBinary": ".bin",
    "nuccChunkNub": ".nub",
    "nuccChunkCamera": ".cam",
    "nuccChunkBillboard": ".billboard",
    "nuccChunkClump": ".clump",
    "nuccChunkLight": ".light",
    "nuccChunkPointLight": ".plight",
    "nuccChunkPage": ".page",
    "nuccChunkNull": ".null",
}


class XfbinError(ValueError):
    pass


@dataclass
class NuccChunk:
    index: int
    map_index: int
    type: str
    name: str
    path: str
    version: int
    offset: int
    data: bytes

    @property
    def size(self) -> int:
        return len(self.data)

    @property
    def extension(self) -> str:
        return CHUNK_EXTENSIONS.get(self.type, ".raw")

    @property
    def file_name(self) -> str:
        label = self.name or f"chunk{self.index:03d}"
        safe = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in label)
        return f"{self.index:03d}_{safe}{self.extension}"

    def describe(self) -> str:
        return f"{self.index:03d} {self.type or '?'} [{self.path or '/'}] {self.name or '?'} {self.size}B"


@dataclass
class Xfbin:
    version: int = 0
    chunks: List[NuccChunk] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    chunk_types: List[str] = field(default_factory=list)
    file_paths: List[str] = field(default_factory=list)
    chunk_names: List[str] = field(default_factory=list)

    # -- inspection ---------------------------------------------------------
    def type_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for chunk in self.chunks:
            counts[chunk.type or "?"] = counts.get(chunk.type or "?", 0) + 1
        return dict(sorted(counts.items()))

    def payload_bytes(self) -> int:
        return sum(chunk.size for chunk in self.chunks)

    def summary(self) -> str:
        kinds = ", ".join(f"{name}x{count}" for name, count in self.type_counts().items())
        return f"xfbin v{self.version}: {len(self.chunks)} chunk(s) [{kinds or 'none'}]"

    # -- extraction ---------------------------------------------------------
    def extract(self, destination: str, prefix: str = "") -> Dict[int, str]:
        """Write every non-empty payload chunk; returns ``{chunk index: path}``."""
        os.makedirs(destination, exist_ok=True)
        written: Dict[int, str] = {}
        for chunk in self.chunks:
            if chunk.type in ("nuccChunkPage", "nuccChunkNull") or chunk.size == 0:
                continue
            target = os.path.join(destination, f"{prefix}{chunk.file_name}")
            with open(target, "wb") as handle:
                handle.write(chunk.data)
            written[chunk.index] = target
        return written


def looks_like_xfbin(data: bytes) -> bool:
    return len(data) >= HEADER_SIZE and data[:4] == MAGIC


def _u32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        raise XfbinError(f"read past end of file at 0x{offset:X}")
    return struct.unpack_from(">I", data, offset)[0]


def _strings(data: bytes, cursor: int, count: int, size: int, label: str) -> Tuple[List[str], int]:
    end = cursor + size
    if cursor < 0 or end > len(data):
        raise XfbinError(f"{label}: string table outside the file (0x{cursor:X}+{size})")
    values: List[str] = []
    position = cursor
    for index in range(count):
        terminator = data.find(b"\x00", position, end)
        if terminator < 0:
            raise XfbinError(f"{label}: string {index} is not NUL terminated")
        values.append(data[position:terminator].decode("utf-8", "replace"))
        position = terminator + 1
    return values, end


def parse(data: bytes) -> Xfbin:
    if len(data) < HEADER_SIZE + CHUNK_HEADER_SIZE + 4 * INDEX_FIELDS:
        raise XfbinError("file is too small to hold an XFBIN header and index")
    if data[:4] != MAGIC:
        raise XfbinError("bad magic (expected NUCC; encrypted or not an xfbin)")

    xfbin = Xfbin(version=_u32(data, 4))
    cursor = HEADER_SIZE
    _size, _map_index, _chunk_version, _unk = struct.unpack_from(">IIHH", data, cursor)
    cursor += CHUNK_HEADER_SIZE

    fields = list(struct.unpack_from(f">{INDEX_FIELDS}I", data, cursor))
    cursor += 4 * INDEX_FIELDS
    (type_count, type_size, path_count, path_size, name_count, name_size,
     map_count, _map_size, map_index_count, extra_count) = fields

    upper = len(data)
    for label, count in (("chunk types", type_count), ("paths", path_count),
                         ("names", name_count), ("chunk maps", map_count),
                         ("chunk map indices", map_index_count)):
        if count > upper:
            raise XfbinError(f"implausible {label} count {count}")

    xfbin.chunk_types, cursor = _strings(data, cursor, type_count, type_size, "chunk types")
    xfbin.file_paths, cursor = _strings(data, cursor, path_count, path_size, "file paths")
    xfbin.chunk_names, cursor = _strings(data, cursor, name_count, name_size, "chunk names")

    cursor = (cursor + 3) & ~3
    map_end = cursor + map_count * 12
    if map_end > len(data):
        raise XfbinError("chunk map table outside the file")
    chunk_maps = [struct.unpack_from(">III", data, cursor + index * 12) for index in range(map_count)]
    cursor = map_end

    extra_end = cursor + extra_count * 8
    if extra_end > len(data):
        raise XfbinError("extra map index table outside the file")
    cursor = extra_end

    indices_end = cursor + map_index_count * 4
    if indices_end > len(data):
        raise XfbinError("chunk map index table outside the file")
    chunk_map_indices = [struct.unpack_from(">I", data, cursor + index * 4)[0]
                         for index in range(map_index_count)]
    cursor = indices_end

    def resolve(map_index: int) -> Tuple[str, str, str]:
        entry = map_index
        if 0 <= map_index < len(chunk_map_indices):
            entry = chunk_map_indices[map_index]
        elif chunk_map_indices:
            xfbin.warnings.append(
                f"chunk map index {map_index} outside the {len(chunk_map_indices)} entry table")
        if not (0 <= entry < len(chunk_maps)):
            xfbin.warnings.append(f"chunk map {entry} does not exist")
            return "", "", ""
        type_index, path_index, name_index = chunk_maps[entry]
        chunk_type = xfbin.chunk_types[type_index] if type_index < len(xfbin.chunk_types) else ""
        path = xfbin.file_paths[path_index] if path_index < len(xfbin.file_paths) else ""
        name = xfbin.chunk_names[name_index] if name_index < len(xfbin.chunk_names) else ""
        if not chunk_type:
            xfbin.warnings.append(f"chunk map {entry} refers to a missing chunk type")
        return chunk_type, path, name

    index = 0
    while cursor + CHUNK_HEADER_SIZE <= len(data):
        size, map_index, version, _unk = struct.unpack_from(">IIHH", data, cursor)
        payload_start = cursor + CHUNK_HEADER_SIZE
        payload_end = payload_start + size
        if payload_end > len(data):
            xfbin.warnings.append(
                f"chunk {index} at 0x{cursor:X} declares {size} bytes but the file ends early")
            payload_end = len(data)
        chunk_type, path, name = resolve(map_index)
        xfbin.chunks.append(NuccChunk(
            index=index,
            map_index=map_index,
            type=chunk_type,
            name=name,
            path=path,
            version=version,
            offset=payload_start,
            data=data[payload_start:payload_end],
        ))
        index += 1
        if size == 0 and payload_end == cursor + CHUNK_HEADER_SIZE:
            # A zero-size chunk is legal (nuccChunkPage / nuccChunkNull) but only
            # when the next header follows immediately; guard against a stall.
            cursor = payload_end
            if cursor + CHUNK_HEADER_SIZE > len(data):
                break
            continue
        cursor = (payload_end + 3) & ~3

    if not xfbin.chunks:
        raise XfbinError("no chunks found after the index")
    return xfbin


def open_xfbin(path: str) -> Xfbin:
    with open(path, "rb") as handle:
        return parse(handle.read())


def describe(xfbin: Xfbin) -> str:
    lines = [xfbin.summary()]
    for chunk in xfbin.chunks:
        lines.append("  " + chunk.describe())
    return "\n".join(lines)
