"""Turn a retail Storm archive into extractable asset files.

This is the first stage of the *real* pipeline: it opens ``data.cpk``, decodes
the CRILAYLA frames the engine's own tooling used to skip, and splits every
``.xfbin`` container into its typed chunks (``.nud`` model, ``.nut`` texture,
``.anm`` animation, ``.bin`` scripts/data, ``.nub`` audio, ...) so the payloads
can be inspected and routed to an importer.

What it deliberately does *not* do is pretend.  Splitting a container is not
importing it: ``.nud`` and ``.nut`` payloads still need their own parsers before
the runtime can draw them, and the report marks every chunk whose payload has no
implemented reader.  See docs/FORMATS_RETAIL.md for the per-format status.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import xfbin
from .cpk import CpkError, open_cpk
from .xfbin import XfbinError


@dataclass
class EntryReport:
    path: str
    size: int
    extract_size: int
    compressed: bool
    chunks: List[Dict[str, object]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None


class RetailError(RuntimeError):
    pass


def _sanitize(relative: str) -> str:
    """Reject absolute paths and ``..`` so extraction stays inside ``destination``."""
    parts = [part for part in relative.replace("\\", "/").split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise RetailError(f"refusing to extract outside the destination: {relative}")
    return os.path.join(*parts) if parts else "unnamed"


def unpack(
    archive: str,
    destination: str,
    only: Optional[str] = None,
    extensions: Optional[List[str]] = None,
    limit: int = 0,
    keep_raw: bool = True,
    split: bool = True,
    log: Callable[[str], None] = print,
) -> Dict[str, object]:
    cpk = open_cpk(archive)
    lowered = [ext.lower() for ext in extensions] if extensions else None

    entries: List[EntryReport] = []
    written_raw: List[str] = []
    written_chunks: List[str] = []
    type_totals: Dict[str, int] = {}
    skipped = 0

    for entry in cpk.entries:
        if only and only.lower() not in entry.path.lower():
            continue
        if lowered and not any(entry.name.lower().endswith(ext) for ext in lowered):
            continue
        if limit and len(entries) >= limit:
            break

        report = EntryReport(path=entry.path, size=entry.size,
                             extract_size=entry.extract_size, compressed=entry.compressed)
        try:
            payload = cpk.read(entry)
        except CpkError as exc:
            report.error = str(exc)
            entries.append(report)
            skipped += 1
            log(f"[skip] {exc}")
            continue

        target = os.path.join(destination, _sanitize(entry.path))
        if keep_raw:
            os.makedirs(os.path.dirname(target) or destination, exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(payload)
            written_raw.append(target)

        if split and xfbin.looks_like_xfbin(payload):
            try:
                container = xfbin.parse(payload)
            except XfbinError as exc:
                report.error = f"xfbin: {exc}"
                log(f"[warn] {entry.path}: {exc}")
                entries.append(report)
                continue
            report.warnings.extend(container.warnings)
            stem = os.path.splitext(os.path.basename(target))[0]
            chunk_dir = os.path.join(os.path.dirname(target) or destination, f"{stem}_chunks")
            written = container.extract(chunk_dir)
            written_chunks.extend(written.values())
            for chunk in container.chunks:
                target_file = written.get(chunk.index)
                report.chunks.append({
                    "index": chunk.index,
                    "type": chunk.type,
                    "name": chunk.name,
                    "path": chunk.path,
                    "size": chunk.size,
                    "file": os.path.basename(target_file) if target_file else None,
                })
                key = chunk.type or "?"
                type_totals[key] = type_totals.get(key, 0) + chunk.size
        elif xfbin.looks_like_xfbin(payload):
            report.warnings.append("xfbin payload was not split (split disabled)")

        entries.append(report)

    summary: Dict[str, object] = {
        "archive": os.path.basename(archive),
        "entries": len(entries),
        "failed": skipped,
        "raw_files": len(written_raw),
        "chunks": len(written_chunks),
        "chunk_bytes": dict(sorted(type_totals.items())),
        "files": [report.__dict__ for report in entries],
        "note": (
            "Container split only. .nud/.nut/.anm payloads have no runtime importer yet; "
            "see docs/FORMATS_RETAIL.md for the format-by-format status."
        ),
    }
    os.makedirs(destination, exist_ok=True)
    with open(os.path.join(destination, "report.json"), "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    return summary


def summarize(summary: Dict[str, object]) -> str:
    parts = [f"{summary['entries']} entries", f"{summary['raw_files']} files",
             f"{summary['chunks']} chunks"]
    if summary["failed"]:
        parts.append(f"{summary['failed']} failed")
    kinds = summary["chunk_bytes"]
    detail = ", ".join(f"{name} {size}B" for name, size in kinds.items()) if kinds else "no chunks"
    return f"{', '.join(parts)} | {detail}"
