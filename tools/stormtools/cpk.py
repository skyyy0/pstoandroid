"""CriWare CPK (CRI FileMajik) reader.

Naruto Storm ships its whole data tree inside ``data.cpk``.  A CPK is a UTF
table (CRI's generic table format) describing rows with columns such as
``FileName``, ``DirName``, ``FileOffset``, ``FileSize`` and ``ExtractSize``.

This module implements the UTF table reader and uncompressed extraction.  Rows
whose ``ExtractSize`` differs from ``FileSize`` are CRILAYLA-compressed in the
retail files; those are reported explicitly instead of being decoded, because a
half-verified LZ decoder silently corrupting assets would be worse than asking
for the community extractor documented in docs/ASSET_PIPELINE.md.

References: the UTF layout used by CRIWARE (see CriPakTools / CriFsV2Lib).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .binary import BinaryError, Reader

# UTF storage type = low nibble of the column flags byte.
_UTF_U8, _UTF_S8, _UTF_U16, _UTF_S16 = 0x0, 0x1, 0x2, 0x3
_UTF_U32, _UTF_S32, _UTF_U64, _UTF_S64 = 0x4, 0x5, 0x6, 0x7
_UTF_F32, _UTF_STRING, _UTF_DATA = 0x8, 0xA, 0xB


class CpkError(BinaryError):
    pass


@dataclass
class UtfColumn:
    name: str
    type: int
    constant: Optional[int] = None


@dataclass
class CpkEntry:
    name: str
    directory: str
    offset: int
    size: int
    extract_size: int
    row: int

    @property
    def path(self) -> str:
        if self.directory:
            return f"{self.directory}/{self.name}"
        return self.name

    @property
    def compressed(self) -> bool:
        return self.extract_size not in (0, self.size)


@dataclass
class Cpk:
    path: str
    _data: bytes
    entries: List[CpkEntry] = field(default_factory=list)

    # -- construction -------------------------------------------------------
    @classmethod
    def open(cls, path: str) -> "Cpk":
        with open(path, "rb") as handle:
            data = handle.read()
        cpk = cls(path=path, _data=data)
        cpk._parse()
        return cpk

    def _find_table(self) -> int:
        start = self._data.find(b"@UTF")
        if start < 0:
            raise CpkError(
                "no @UTF table found; the archive header may be encrypted "
                "(needs the 'encrypted CPK' path or an external extractor)"
            )
        return start

    def _table_candidates(self) -> List[int]:
        """CPK files carry a 16 byte wrapper before the real table, so try both."""
        candidates: List[int] = []
        start = 0
        while len(candidates) < 8:
            index = self._data.find(b"@UTF", start)
            if index < 0:
                break
            candidates.append(index)
            start = index + 4
        if not candidates:
            self._find_table()  # raises the actionable error
        return candidates

    def _parse(self) -> None:
        failures: List[str] = []
        for start in self._table_candidates():
            try:
                self._parse_table(start)
                return
            except CpkError as exc:
                failures.append(f"@{start:#x}: {exc}")
        raise CpkError("no parsable @UTF table (" + "; ".join(failures) + ")")

    def _parse_table(self, start: int) -> None:
        reader = Reader(self._data, start, endian="<")
        reader.magic(b"@UTF")
        table_size = reader.u32()
        rows_offset = reader.u32()
        string_offset = reader.u32()
        data_offset = reader.u32()
        reader.u32()  # table name offset
        num_columns = reader.u16()
        row_stride = reader.u16()
        num_rows = reader.u32()

        table_end = start + table_size
        if table_size == 0 or table_end > len(self._data) or row_stride == 0:
            raise CpkError("corrupt UTF table header")
        if rows_offset < 32 or rows_offset >= table_size:
            raise CpkError("rows offset outside the table")

        columns: List[UtfColumn] = []
        for _ in range(num_columns):
            flags = reader.u8()
            ctype = flags & 0x0F
            constant = None
            # High nibble 0x50 / 0x30 marks an inline constant value.
            if (flags & 0xF0) == 0x50:
                constant = reader.u32()
            elif (flags & 0xF0) == 0x30:
                constant = reader.u8()
            name = reader.cstr() if (flags & 0x10) == 0 else ""
            columns.append(UtfColumn(name=name, type=ctype, constant=constant))

        rows_start = start + rows_offset
        string_base = start + string_offset
        self.entries = []
        for row in range(num_rows):
            row_pos = rows_start + row * row_stride
            if row_pos + row_stride > len(self._data):
                raise CpkError("row data extends past end of archive")
            row_reader = Reader(self._data, row_pos, endian="<")
            values: Dict[str, object] = {}
            for column in columns:
                values[column.name] = self._read_value(
                    row_reader, column, string_base, start + data_offset
                )
            entry = self._entry_from_row(row, values)
            if entry is not None and entry.size > 0:
                self.entries.append(entry)

    def _read_value(self, reader: Reader, column: UtfColumn, string_base: int, data_base: int):
        if column.constant is not None:
            return column.constant
        ctype = column.type
        if ctype == _UTF_U8:
            return reader.u8()
        if ctype == _UTF_S8:
            return reader.s8()
        if ctype == _UTF_U16:
            return reader.u16()
        if ctype == _UTF_S16:
            return reader.s16()
        if ctype == _UTF_U32:
            return reader.u32()
        if ctype == _UTF_S32:
            return reader.s32()
        if ctype == _UTF_U64:
            return reader.u64()
        if ctype == _UTF_S64:
            return reader.s64()
        if ctype == _UTF_F32:
            return reader.f32()
        if ctype == _UTF_STRING:
            offset = reader.u32()
            if offset == 0:
                return ""
            return self._read_cstring(string_base + offset)
        if ctype == _UTF_DATA:
            offset = reader.u32()
            size = reader.u32()
            start = data_base + offset
            if start + size > len(self._data):
                raise CpkError("inline data column past end of archive")
            return self._data[start:start + size]
        raise CpkError(f"unsupported UTF column type 0x{ctype:X}")

    def _read_cstring(self, offset: int) -> str:
        if offset >= len(self._data):
            return ""
        end = self._data.find(b"\x00", offset)
        if end < 0:
            return ""
        return self._data[offset:end].decode("utf-8", "replace")

    @staticmethod
    def _entry_from_row(row: int, values: Dict[str, object]) -> Optional[CpkEntry]:
        name = values.get("FileName", "")
        directory = values.get("DirName", "")
        offset = values.get("FileOffset", 0)
        size = values.get("FileSize", 0)
        extract_size = values.get("ExtractSize", size)
        if not isinstance(name, str):
            name = ""
        if not isinstance(directory, str):
            directory = ""
        if not isinstance(offset, int) or not isinstance(size, int):
            return None
        if isinstance(extract_size, int) is False:
            extract_size = size
        return CpkEntry(
            name=name,
            directory=directory,
            offset=offset,
            size=size,
            extract_size=extract_size,
            row=row,
        )

    # -- access -------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.entries)

    def find(self, needle: str) -> List[CpkEntry]:
        needle = needle.lower()
        return [e for e in self.entries if needle in e.path.lower()]

    def read(self, entry: CpkEntry) -> bytes:
        if entry.compressed:
            raise CpkError(
                f"{entry.path}: entry is CRILAYLA-compressed "
                f"({entry.size} -> {entry.extract_size} bytes); "
                "use the external extractor described in docs/ASSET_PIPELINE.md"
            )
        if entry.offset + entry.size > len(self._data):
            raise CpkError(f"{entry.path}: data past end of archive")
        return self._data[entry.offset:entry.offset + entry.size]

    def extract_all(
        self,
        destination: str,
        only: Optional[str] = None,
        extensions: Optional[List[str]] = None,
        limit: int = 0,
    ) -> List[str]:
        written: List[str] = []
        lowered = [ext.lower() for ext in extensions] if extensions else None
        for entry in self.entries:
            if only and only.lower() not in entry.path.lower():
                continue
            if lowered and not any(entry.name.lower().endswith(ext) for ext in lowered):
                continue
            try:
                payload = self.read(entry)
            except CpkError as exc:
                print(f"[skip] {exc}")
                continue
            target = os.path.join(destination, entry.path.replace("\\", "/"))
            os.makedirs(os.path.dirname(target) or destination, exist_ok=True)
            with open(target, "wb") as handle:
                handle.write(payload)
            written.append(target)
            if limit and len(written) >= limit:
                break
        return written


def open_cpk(path: str) -> Cpk:
    return Cpk.open(path)
