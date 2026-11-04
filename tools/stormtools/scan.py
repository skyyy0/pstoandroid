"""Signature scanner for retail CC2/CriWare blobs.

The retail containers (.cpk -> .xfbin -> nuccChunk*) have no public binary spec,
and the community parsers (xfbin_lib, UNSME, Blender addons) are the reference
implementations.  Rather than guessing field layouts and silently producing
garbage, this module provides a *carver*: it locates well-known magic numbers
and the literal ``nuccChunk*`` tags so assets can be routed to the right
community tool, and raw payloads can be lifted out of a blob for inspection.

Output is honest about what it found: signatures, offsets and the chunk type
names present in the file.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Dict, List

SIGNATURES: Dict[bytes, str] = {
    b"NUCC": "xfbin container (CyberConnect2 NUCC)",
    b"@UTF": "CRI UTF table (CPK / SFD)",
    b"NTP3": "NUT texture (Bandai Namco, DDS-like)",
    b"NDP3": "NUD model (Bandai Namco mesh)",
    b"DDS ": "DDS texture",
    b"CRILAYLA": "CRILAYLA compressed block",
    b"RIFF": "RIFF container (audio)",
    b"OggS": "Ogg stream (audio)",
    b"XFBIN": "xfbin (legacy tag)",
}

CHUNK_RE = re.compile(rb"nuccChunk([A-Za-z0-9_]+)")


@dataclass
class Hit:
    offset: int
    signature: bytes
    description: str


@dataclass
class ScanResult:
    path: str
    size: int
    hits: List[Hit]
    chunk_types: List[str]

    def summary(self) -> str:
        kinds = ", ".join(f"{h.signature.decode('latin-1')}@{h.offset}" for h in self.hits[:8])
        chunks = ", ".join(sorted(set(self.chunk_types))) or "none"
        more = "" if len(self.hits) <= 8 else f" (+{len(self.hits) - 8} more)"
        return f"{os.path.basename(self.path)} [{self.size} bytes] signatures: {kinds}{more} | chunks: {chunks}"


def scan_bytes(data: bytes, path: str = "<memory>") -> ScanResult:
    hits: List[Hit] = []
    for signature, description in SIGNATURES.items():
        start = 0
        while True:
            index = data.find(signature, start)
            if index < 0:
                break
            hits.append(Hit(index, signature, description))
            start = index + 1
            if len(hits) > 512:
                break
    hits.sort(key=lambda hit: hit.offset)
    chunk_types = sorted({m.group(1).decode("ascii", "replace") for m in CHUNK_RE.finditer(data)})
    return ScanResult(path=path, size=len(data), hits=hits, chunk_types=chunk_types)


def scan_file(path: str) -> ScanResult:
    with open(path, "rb") as handle:
        return scan_bytes(handle.read(), path)


def carve(data: bytes, signature: bytes, destination: str, max_hits: int = 16) -> List[str]:
    """Write every region that starts with ``signature`` up to the next hit."""
    starts = []
    cursor = 0
    while True:
        index = data.find(signature, cursor)
        if index < 0 or len(starts) >= max_hits:
            break
        starts.append(index)
        cursor = index + len(signature)
    written: List[str] = []
    os.makedirs(destination, exist_ok=True)
    for order, start in enumerate(starts):
        end = starts[order + 1] if order + 1 < len(starts) else len(data)
        name = f"{signature.decode('latin-1').strip().replace(' ', '_').lower()}_{start:08x}.bin"
        target = os.path.join(destination, name)
        with open(target, "wb") as handle:
            handle.write(data[start:end])
        written.append(target)
    return written
