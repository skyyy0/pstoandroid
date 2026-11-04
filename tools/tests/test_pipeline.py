"""Pipeline tests: CPK/UTF, signature scanner, glTF packing, demo assets."""

from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from stormtools import demo_assets, scan, pack  # noqa: E402
from stormtools.binary import Writer, fnv1a32  # noqa: E402
from stormtools.cpk import Cpk, CpkError  # noqa: E402
from stormtools.formats import read_anim, read_mesh, write_mesh  # noqa: E402


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

    for name, directory, _payload in entries:
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
    for name, directory, payload in entries:
        size = len(payload)
        extract_size = size + 1 if compressed else size
        row = Writer("<")
        row.u32(string_offsets[name]).u32(string_offsets.get(directory, 0))
        row.u32(payload_offset).u32(size).u32(extract_size)
        row_values.append(row.bytes())
        payload_offset += size

    payload_blob = b"".join(payload for _n, _d, payload in entries)

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

    def test_rejects_compressed_entries_with_actionable_error(self):
        blob = build_cpk([("packed.bin", "data", b"\x00" * 32)], compressed=True)
        with tempfile.TemporaryDirectory() as tmp:
            archive = os.path.join(tmp, "data.cpk")
            with open(archive, "wb") as handle:
                handle.write(blob)
            cpk = Cpk.open(archive)
            entry = cpk.entries[0]
            self.assertTrue(entry.compressed)
            with self.assertRaises(CpkError) as ctx:
                cpk.read(entry)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
