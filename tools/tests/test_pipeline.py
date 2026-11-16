"""Pipeline tests: CPK/UTF, signature scanner, glTF packing, demo assets."""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from stormtools import crilayla, demo_assets, retail, scan, pack, xfbin  # noqa: E402
from stormtools.binary import Writer, fnv1a32  # noqa: E402
from stormtools.cpk import Cpk, CpkError  # noqa: E402
from stormtools.formats import read_anim, read_mesh, write_mesh  # noqa: E402


def pack_bits(bits):
    """Pack decoder-read-order bits into a CRILAYLA payload (MSB first, reversed)."""
    padded = bits + [0] * ((-len(bits)) % 8)
    groups = []
    for start in range(0, len(padded), 8):
        value = 0
        for bit in padded[start:start + 8]:
            value = (value << 1) | bit
        groups.append(value)
    return bytes(reversed(groups))


def crilayla_literals(payload, prefix=None):
    """Build a literal-only CRILAYLA frame for ``payload`` (test helper)."""
    bits = []
    for byte in reversed(payload):
        bits.append(0)
        bits.extend((byte >> shift) & 1 for shift in range(7, -1, -1))
    stream = pack_bits(bits)
    raw_prefix = (prefix or b"").ljust(0x100, b"\x00")[:0x100]
    return b"CRILAYLA" + struct.pack("<II", len(payload), len(stream)) + stream + raw_prefix


def length_bits(length):
    """Encode a back-reference length with the 2/3/5/8-bit chunk grammar."""
    remaining = length - crilayla.MIN_MATCH
    bits = []
    for width in (2, 3, 5):
        cap = (1 << width) - 1
        if remaining < cap:
            bits.extend((remaining >> shift) & 1 for shift in range(width - 1, -1, -1))
            return bits
        bits.extend([1] * width)
        remaining -= cap
    while remaining >= 0xFF:
        bits.extend([1] * 8)
        remaining -= 0xFF
    bits.extend((remaining >> shift) & 1 for shift in range(7, -1, -1))
    return bits


def crilayla_repeat(unit, repeat):
    """Frame whose payload is ``unit * repeat``: literals then one back-reference."""
    bits = []
    for byte in reversed(unit):
        bits.append(0)
        bits.extend((byte >> shift) & 1 for shift in range(7, -1, -1))
    bits.append(1)
    distance = len(unit) - crilayla.MIN_MATCH
    bits.extend((distance >> shift) & 1 for shift in range(12, -1, -1))
    bits.extend(length_bits(len(unit) * (repeat - 1)))
    stream = pack_bits(bits)
    payload_size = len(unit) * repeat
    return b"CRILAYLA" + struct.pack("<II", payload_size, len(stream)) + stream + b"\x00" * 0x100


def build_xfbin(chunks, version=0x0220):
    """Build a minimal NUCC container: chunks is [(type, name, path, payload)]."""
    types = sorted({chunk[0] for chunk in chunks})
    paths = sorted({chunk[2] for chunk in chunks})
    names = [chunk[1] for chunk in chunks]

    def table(values):
        return b"".join(value.encode() + b"\x00" for value in values)

    type_blob, path_blob, name_blob = table(types), table(paths), table(names)
    maps = b"".join(
        struct.pack(
            ">III",
            types.index(chunk_type),
            paths.index(path) if path in paths else 0,
            names.index(name),
        )
        for chunk_type, name, path, _payload in chunks
    )
    indices = b"".join(struct.pack(">I", index) for index in range(len(chunks)))

    body = bytearray()
    body += struct.pack(">10I", len(types), len(type_blob), len(paths), len(path_blob),
                        len(names), len(name_blob), len(chunks), len(maps),
                        len(chunks), 0)
    body += type_blob + path_blob + name_blob
    body += b"\x00" * ((-len(body)) % 4)
    body += maps + indices

    out = bytearray()
    out += b"NUCC" + struct.pack(">I", version) + b"\x00" * 8
    out += struct.pack(">IIHH", len(body), 0, version, 0) + bytes(body)
    for index, (_type, _name, _path, payload) in enumerate(chunks):
        out += struct.pack(">IIHH", len(payload), index, version, 0)
        out += payload
        out += b"\x00" * ((-len(out)) % 4)
    return bytes(out)


def build_cpk(entries, compressed=False):
    """Build a minimal but structurally valid CRI CPK containing ``entries``."""
    # (UTF type nibble, column name) - 0x0A = string, 0x04 = u32
    columns = [
        (0x0A, "FileName"),
        (0x0A, "DirName"),
        (0x04, "FileOffset"),
        (0x04, "FileSize"),
        (0x04, "ExtractSize"),
    ]
    column_bytes = b"".join(bytes([ctype]) + name.encode() + b"\x00" for ctype, name in columns)

    strings = bytearray(b"\x00")
    string_offsets = {}

    def intern(text):
        if not text:
            return 0
        if text not in string_offsets:
            string_offsets[text] = len(strings)
            strings.extend(text.encode() + b"\x00")
        return string_offsets[text]

    for name, directory, *_rest in entries:
        intern(name)
        intern(directory)

    rows_offset = 32 + len(column_bytes) + len(strings)
    # align rows to 4 bytes
    padding = (-rows_offset) % 4
    strings.extend(b"\x00" * padding)
    rows_offset += padding
    row_stride = 20
    rows_start = rows_offset
    data_start = rows_start + row_stride * len(entries)
    table_size = data_start
    wrapper = 16  # real CPK files put a 16 byte wrapper before the @UTF table

    row_values = []
    payload_offset = wrapper + data_start
    for name, directory, payload, *rest in entries:
        size = len(payload)
        extract_size = rest[0] if rest else (size + 1 if compressed else size)
        row = Writer("<")
        row.u32(string_offsets[name]).u32(string_offsets.get(directory, 0))
        row.u32(payload_offset).u32(size).u32(extract_size)
        row_values.append(row.bytes())
        payload_offset += size

    payload_blob = b"".join(entry[2] for entry in entries)

    out = bytearray()
    out += b"@UTF" + struct.pack("<I", table_size + wrapper) + b"\x00" * 8
    out += b"@UTF" + struct.pack("<I", table_size)
    out += struct.pack("<IIII", rows_offset, 32 + len(column_bytes), data_start, 0)
    out += struct.pack("<HHI", len(columns), row_stride, len(entries))
    out += column_bytes + bytes(strings)
    for row in row_values:
        out += row
    out += payload_blob
    return bytes(out)


def build_glb():
    """Two triangles skinned to a two-bone chain, one rotation clip."""
    positions = [
        0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
        1.0, 1.0, 0.0, 0.0, 1.0, 0.0,
    ]
    joints = [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0]
    weights = [1.0, 0.0, 0.0, 0.0] * 4
    indices = [0, 1, 2, 1, 2, 3]
    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    invbind = identity + [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, -1, 0, 1]
    times = [0.0, 1.0]
    # 90 degrees around Z
    half = 0.7071067811865476
    rotations = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, half, half]

    binary = bytearray()
    layout = {}

    def add(name, fmt, values, size):
        offset = len(binary)
        binary.extend(struct.pack("<" + fmt * len(values), *values))
        while len(binary) % 4:
            binary.append(0)
        layout[name] = (offset, size)
        return offset

    add("positions", "f", positions, len(positions) * 4)
    add("joints", "B", joints, len(joints))
    add("weights", "f", weights, len(weights) * 4)
    add("indices", "H", indices, len(indices) * 2)
    add("invbind", "f", invbind, len(invbind) * 4)
    add("times", "f", times, len(times) * 4)
    add("rotations", "f", rotations, len(rotations) * 4)

    views = [
        {"buffer": 0, "byteOffset": layout[name][0], "byteLength": layout[name][1]}
        for name in ("positions", "joints", "weights", "indices", "invbind", "times", "rotations")
    ]
    accessors = [
        {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"},
        {"bufferView": 1, "componentType": 5121, "count": 4, "type": "VEC4"},
        {"bufferView": 2, "componentType": 5126, "count": 4, "type": "VEC4"},
        {"bufferView": 3, "componentType": 5123, "count": 6, "type": "SCALAR"},
        {"bufferView": 4, "componentType": 5126, "count": 2, "type": "MAT4"},
        {"bufferView": 5, "componentType": 5126, "count": 2, "type": "SCALAR"},
        {"bufferView": 6, "componentType": 5126, "count": 2, "type": "VEC4"},
    ]
    gltf = {
        "asset": {"version": "2.0"},
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": views,
        "accessors": accessors,
        "materials": [{"name": "suit", "pbrMetallicRoughness": {"baseColorFactor": [1.0, 0.5, 0.0, 1.0]}}],
        "nodes": [
            {"name": "body", "mesh": 0, "skin": 0},
            {"name": "root", "children": [2]},
            {"name": "spine", "translation": [0.0, 1.0, 0.0]},
        ],
        "scenes": [{"nodes": [0, 1]}],
        "skins": [{"joints": [1, 2], "inverseBindMatrices": 4}],
        "meshes": [{"name": "body", "primitives": [{
            "attributes": {"POSITION": 0, "JOINTS_0": 1, "WEIGHTS_0": 2},
            "indices": 3, "material": 0,
        }]}],
        "animations": [{
            "name": "wave",
            "samplers": [{"input": 5, "output": 6, "interpolation": "LINEAR"}],
            "channels": [{"sampler": 0, "target": {"node": 2, "path": "rotation"}}],
        }],
    }
    json_bytes = json.dumps(gltf).encode()
    while len(json_bytes) % 4:
        json_bytes += b" "

    out = bytearray()
    out += b"glTF" + struct.pack("<II", 2, 12 + 8 + len(json_bytes) + 8 + len(binary))
    out += struct.pack("<I", len(json_bytes)) + b"JSON" + json_bytes
    out += struct.pack("<I", len(binary)) + b"BIN\x00" + bytes(binary)
    return bytes(out)


class CpkTests(unittest.TestCase):
    def test_extracts_uncompressed_entries(self):
        payload_a = b"NUCC" + b"\x01" * 60
        payload_b = b"@UTF" + b"\x02" * 20
        blob = build_cpk([
            ("naruto.xfbin", "chara", payload_a),
            ("sasuke.xfbin", "chara", payload_b),
        ])
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "data.cpk")
            with open(archive, "wb") as handle:
                handle.write(blob)
            cpk = Cpk.open(archive)
            self.assertEqual(len(cpk), 2)
            names = sorted(entry.path for entry in cpk.entries)
            self.assertEqual(names, ["chara/naruto.xfbin", "chara/sasuke.xfbin"])
            found = cpk.find("sasuke")
            self.assertEqual(len(found), 1)
            self.assertEqual(cpk.read(found[0]), payload_b)

            written = cpk.extract_all(tmp, extensions=[".xfbin"])
            self.assertEqual(len(written), 2)
            with open(os.path.join(tmp, "chara", "naruto.xfbin"), "rb") as handle:
                self.assertEqual(handle.read(), payload_a)

    def test_decodes_crilayla_entries(self):
        raw = b"NUCC" + bytes(range(64))
        frame = crilayla_literals(raw)
        blob = build_cpk([("packed.xfbin", "data", frame, 0x100 + len(raw))])
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "data.cpk")
            with open(archive, "wb") as handle:
                handle.write(blob)
            cpk = Cpk.open(archive)
            entry = cpk.entries[0]
            self.assertTrue(entry.compressed)
            self.assertEqual(cpk.read(entry), b"\x00" * 0x100 + raw)

            written = cpk.extract_all(tmp, extensions=[".xfbin"])
            self.assertEqual(len(written), 1)
            with open(written[0], "rb") as handle:
                self.assertEqual(handle.read(), b"\x00" * 0x100 + raw)

    def test_compressed_entry_without_frame_is_rejected(self):
        blob = build_cpk([("packed.bin", "data", b"\x00" * 32)], compressed=True)
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "data.cpk")
            with open(archive, "wb") as handle:
                handle.write(blob)
            cpk = Cpk.open(archive)
            with self.assertRaises(CpkError) as ctx:
                cpk.read(cpk.entries[0])
            self.assertIn("CRILAYLA", str(ctx.exception))

    def test_missing_table_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "broken.cpk")
            with open(archive, "wb") as handle:
                handle.write(b"\x00" * 64)
            with self.assertRaises(CpkError):
                Cpk.open(archive)


class ScanTests(unittest.TestCase):
    def test_finds_signatures_and_chunk_tags(self):
        blob = b"\x00" * 16 + b"NUCC" + b"\x00" * 8 + b"nuccChunkModel\x00" + b"\x00" * 4
        blob += b"nuccChunkTexture\x00" + b"NTP3" + b"\x00" * 8
        result = scan.scan_bytes(blob, "sample.xfbin")
        signatures = {hit.signature for hit in result.hits}
        self.assertIn(b"NUCC", signatures)
        self.assertIn(b"NTP3", signatures)
        self.assertEqual(result.chunk_types, ["Model", "Texture"])
        self.assertIn("chunks: Model, Texture", result.summary())

    def test_carve_writes_regions(self):
        blob = b"XX" + b"NTP3" + b"A" * 6 + b"NTP3" + b"B" * 6
        with tempfile.TemporaryDirectory() as tmp:
            written = scan.carve(blob, b"NTP3", tmp)
            self.assertEqual(len(written), 2)
            with open(written[1], "rb") as handle:
                self.assertEqual(handle.read(), b"NTP3" + b"B" * 6)


class PackTests(unittest.TestCase):
    def test_glb_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            glb_path = os.path.join(tmp, "body.glb")
            with open(glb_path, "wb") as handle:
                handle.write(build_glb())
            manifest = os.path.join(tmp, "manifest.txt")
            info = pack.pack_glb(glb_path, tmp, base_name="ninja", manifest_path=manifest)
            self.assertEqual(info["vertices"], 4)
            self.assertEqual(info["triangles"], 2)
            self.assertEqual(info["bones"], 2)
            self.assertEqual(info["clips"], ["wave"])

            with open(os.path.join(tmp, "ninja.smesh"), "rb") as handle:
                mesh = read_mesh(handle.read())
            self.assertEqual(len(mesh.bones), 2)
            self.assertEqual(fnv1a32("spine"), mesh.bones[1].name_hash)
            self.assertEqual(mesh.bones[1].parent, 0)
            self.assertEqual(mesh.indices, [0, 1, 2, 1, 2, 3])
            self.assertEqual(mesh.materials[0].base_color[:3], (1.0, 0.5, 0.0))
            self.assertTrue(all(0 <= index < len(mesh.vertices) for index in mesh.indices))
            for vertex in mesh.vertices:
                self.assertEqual(sum(vertex.weights), 255)
                self.assertTrue(all(0 <= joint < 2 for joint in vertex.joints))

            with open(os.path.join(tmp, "ninja_wave.sanm"), "rb") as handle:
                clip = read_anim(handle.read())
            self.assertAlmostEqual(clip.duration, 1.0)
            self.assertEqual(len(clip.tracks), 1)
            self.assertEqual(len(clip.tracks[0].keys), 2)
            self.assertAlmostEqual(clip.tracks[0].keys[1].rotation[3], 0.7071068, places=5)

            with open(manifest, "r", encoding="utf-8") as handle:
                lines = [line.strip() for line in handle if line.strip()]
            self.assertIn("mesh ninja ninja.smesh", lines)
            self.assertIn("anim ninja wave ninja_wave.sanm", lines)


class DemoAssetTests(unittest.TestCase):
    def test_demo_assets_are_well_formed(self):
        with tempfile.TemporaryDirectory() as tmp:
            asset_dir = os.path.join(tmp, "storm")
            manifest = os.path.join(asset_dir, "manifest.txt")
            result = demo_assets.write_demo_assets(asset_dir, manifest)
            self.assertTrue(result["files"])

            with open(os.path.join(asset_dir, "fighter.smesh"), "rb") as handle:
                mesh = read_mesh(handle.read())
            self.assertEqual(len(mesh.bones), len(demo_assets.BONES))
            self.assertGreater(len(mesh.indices), 300)
            self.assertEqual(len(mesh.indices) % 3, 0)
            self.assertTrue(all(0 <= index < len(mesh.vertices) for index in mesh.indices))
            for vertex in mesh.vertices:
                self.assertEqual(sum(vertex.weights), 255)
                self.assertLess(vertex.joints[0], len(mesh.bones))
                self.assertTrue(0.0 <= vertex.uv[0] <= 20.0)
            self.assertTrue(mesh.textures == [])

            with open(os.path.join(asset_dir, "arena.smesh"), "rb") as handle:
                arena = read_mesh(handle.read())
            self.assertEqual(len(arena.textures), 1)
            self.assertEqual(arena.textures[0].width, 64)

            for clip in demo_assets.build_animations():
                with open(os.path.join(asset_dir, f"fighter_{clip.name}.sanm"), "rb") as handle:
                    parsed = read_anim(handle.read())
                self.assertEqual(parsed.name, clip.name)
                self.assertGreater(parsed.duration, 0.0)
                for track in parsed.tracks:
                    for key in track.keys:
                        self.assertGreaterEqual(key.time, 0.0)
                        self.assertAlmostEqual(
                            sum(component * component for component in key.rotation), 1.0, places=3
                        )

            with open(manifest, "r", encoding="utf-8") as handle:
                text = handle.read()
            self.assertIn("character rookie fighter 1.0", text)
            self.assertIn("anim fighter idle storm/fighter_idle.sanm", text)

    def test_write_mesh_is_deterministic(self):
        first = write_mesh(demo_assets.build_character("rookie"))
        second = write_mesh(demo_assets.build_character("rookie"))
        self.assertEqual(first, second)
        self.assertEqual(first[:4], b"SMSH")


class CrilaylaTests(unittest.TestCase):
    def test_literal_frame_round_trip(self):
        payload = bytes(range(1, 40))
        frame = crilayla_literals(payload)
        self.assertTrue(crilayla.is_crilayla(frame))
        out = crilayla.decompress(frame, expected_size=0x100 + len(payload))
        self.assertEqual(out, b"\x00" * 0x100 + payload)

    def test_back_reference_copies_already_decoded_bytes(self):
        frame = crilayla_repeat(b"ABCD", 4)
        out = crilayla.decompress(frame)
        self.assertEqual(out, b"\x00" * 0x100 + b"ABCD" * 4)

    def test_long_length_uses_the_8bit_extension(self):
        unit = bytes(range(32))
        frame = crilayla_repeat(unit, 12)  # 352 byte match: 2/3/5 bit chunks all saturate
        out = crilayla.decompress(frame)
        self.assertEqual(out, b"\x00" * 0x100 + unit * 12)

    def test_truncated_frame_is_rejected(self):
        frame = crilayla_literals(b"x" * 32)
        with self.assertRaises(crilayla.CrilaylaError):
            crilayla.decompress(frame[:-10])

    def test_extract_size_mismatch_is_rejected(self):
        frame = crilayla_literals(b"y" * 8)
        with self.assertRaises(crilayla.CrilaylaError):
            crilayla.decompress(frame, expected_size=1234)

    def test_bad_magic_is_rejected(self):
        with self.assertRaises(crilayla.CrilaylaError):
            crilayla.decompress(b"NOTLAYLA" + b"\x00" * 32)


class XfbinTests(unittest.TestCase):
    def build(self):
        return build_xfbin([
            ("nuccChunkModel", "body", "chara/naruto", b"NDP3" + b"\x01" * 24),
            ("nuccChunkTexture", "face", "chara/naruto", b"NTP3" + b"\x02" * 12),
            ("nuccChunkAnm", "idle00", "chara/naruto", b"ANM " + b"\x03" * 8),
        ])

    def test_parses_chunk_index(self):
        container = xfbin.parse(self.build())
        self.assertEqual(container.version, 0x0220)
        self.assertEqual([chunk.type for chunk in container.chunks],
                         ["nuccChunkModel", "nuccChunkTexture", "nuccChunkAnm"])
        self.assertEqual([chunk.name for chunk in container.chunks], ["body", "face", "idle00"])
        self.assertEqual(container.chunks[0].path, "chara/naruto")
        self.assertTrue(container.chunks[0].data.startswith(b"NDP3"))
        self.assertEqual(container.chunks[0].extension, ".nud")
        self.assertEqual(container.type_counts(),
                         {"nuccChunkAnm": 1, "nuccChunkModel": 1, "nuccChunkTexture": 1})
        self.assertEqual(container.warnings, [])

    def test_extracts_typed_payloads(self):
        container = xfbin.parse(self.build())
        with tempfile.TemporaryDirectory() as tmp:
            written = container.extract(tmp)
            self.assertEqual(len(written), 3)
            names = sorted(os.path.basename(path) for path in written.values())
            self.assertEqual(names, ["000_body.nud", "001_face.nut", "002_idle00.anm"])
            with open(os.path.join(tmp, "002_idle00.anm"), "rb") as handle:
                self.assertTrue(handle.read().startswith(b"ANM "))

    def test_bad_magic_is_rejected(self):
        with self.assertRaises(xfbin.XfbinError):
            xfbin.parse(b"XFBIN" + b"\x00" * 64)

    def test_truncated_index_is_rejected(self):
        blob = self.build()
        with self.assertRaises(xfbin.XfbinError):
            xfbin.parse(blob[:0x30])


class RetailTests(unittest.TestCase):
    def test_unpacks_compressed_xfbin_and_writes_report(self):
        container = build_xfbin([
            ("nuccChunkModel", "body", "chara/naruto", b"NDP3" + b"\x04" * 140),
            ("nuccChunkTexture", "face", "chara/naruto", b"NTP3" + b"\x05" * 24),
        ])
        self.assertGreater(len(container), 0x100)
        # The first 0x100 bytes of a file are stored verbatim as the frame prefix.
        frame = crilayla_literals(container[0x100:], prefix=container[:0x100])
        blob = build_cpk([("naruto.xfbin", "chara", frame, len(container))])
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "data.cpk")
            with open(archive, "wb") as handle:
                handle.write(blob)
            out = os.path.join(tmp, "out")
            summary = retail.unpack(archive, out, log=lambda _line: None)
            self.assertEqual(summary["entries"], 1)
            self.assertEqual(summary["failed"], 0)
            self.assertEqual(summary["chunks"], 2)
            self.assertEqual(summary["chunk_bytes"],
                             {"nuccChunkModel": 144, "nuccChunkTexture": 28})

            chunk_dir = os.path.join(out, "chara", "naruto_chunks")
            self.assertTrue(os.path.isfile(os.path.join(chunk_dir, "000_body.nud")))
            self.assertTrue(os.path.isfile(os.path.join(chunk_dir, "001_face.nut")))
            with open(os.path.join(out, "chara", "naruto.xfbin"), "rb") as handle:
                self.assertEqual(handle.read(), container)

            with open(os.path.join(out, "report.json"), "r", encoding="utf-8") as handle:
                report = json.load(handle)
            self.assertEqual(report["archive"], "data.cpk")
            self.assertEqual(report["files"][0]["chunks"][0]["file"], "000_body.nud")
            self.assertIn("no runtime importer", report["note"])

    def test_unsafe_paths_are_not_written(self):
        with self.assertRaises(retail.RetailError):
            retail._sanitize("../escape.xfbin")


if __name__ == "__main__":
    unittest.main(verbosity=2)
