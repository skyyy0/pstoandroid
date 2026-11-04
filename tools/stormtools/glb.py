"""glTF 2.0 (.glb / .gltf) reader used by the asset packer.

Only the subset Blender produces for game characters is implemented: indexed
triangle meshes, triangle strips/fans are rejected, skins with
``inverseBindMatrices``, PNG albedo textures and TRS animation channels.
"""

from __future__ import annotations

import base64
import json
import os
import struct
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .binary import BinaryError

COMPONENT = {
    5120: ("b", 1),
    5121: ("B", 1),
    5122: ("h", 2),
    5123: ("H", 2),
    5125: ("I", 4),
    5126: ("f", 4),
}
TYPE_SIZE = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}


class GltfError(BinaryError):
    pass


@dataclass
class Accessor:
    values: List[List[float]]
    component_type: int
    normalized: bool

    def __len__(self) -> int:
        return len(self.values)


@dataclass
class Gltf:
    json: dict
    buffers: List[bytes]
    base_dir: str

    # -- loading ------------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "Gltf":
        with open(path, "rb") as handle:
            data = handle.read()
        base_dir = os.path.dirname(os.path.abspath(path))
        if data[:4] == b"glTF":
            version, length = struct.unpack_from("<II", data, 4)
            if version != 2:
                raise GltfError(f"unsupported glTF version {version}")
            if length > len(data):
                raise GltfError("glb header length exceeds file size")
            pos = 12
            gltf_json = None
            binary = b""
            while pos + 8 <= length:
                chunk_length, chunk_type = struct.unpack_from("<I4s", data, pos)
                pos += 8
                payload = data[pos:pos + chunk_length]
                pos += chunk_length
                if chunk_type == b"JSON":
                    gltf_json = json.loads(payload.decode("utf-8").rstrip("\x00 "))
                elif chunk_type == b"BIN\x00":
                    binary = payload
            if gltf_json is None:
                raise GltfError("glb has no JSON chunk")
            buffers = [binary] if binary else []
            # External buffers referenced from a glb are rare but legal.
            for index, buffer in enumerate(gltf_json.get("buffers", [])):
                uri = buffer.get("uri")
                if uri and not uri.startswith("data:") and index >= len(buffers):
                    buffers.append(cls._read_external(uri, base_dir))
            return cls(json=gltf_json, buffers=buffers, base_dir=base_dir)

        gltf_json = json.loads(data.decode("utf-8"))
        buffers = []
        for buffer in gltf_json.get("buffers", []):
            uri = buffer.get("uri")
            if uri is None:
                raise GltfError("gltf buffer without uri; export as .glb instead")
            if uri.startswith("data:"):
                buffers.append(base64.b64decode(uri.split(",", 1)[1]))
            else:
                buffers.append(cls._read_external(uri, base_dir))
        return cls(json=gltf_json, buffers=buffers, base_dir=base_dir)

    @staticmethod
    def _read_external(uri: str, base_dir: str) -> bytes:
        with open(os.path.join(base_dir, uri), "rb") as handle:
            return handle.read()

    # -- accessors ----------------------------------------------------------
    def accessor(self, index: int) -> Accessor:
        declared = self.json["accessors"][index]
        component_type = declared["componentType"]
        if component_type not in COMPONENT:
            raise GltfError(f"unsupported component type {component_type}")
        fmt, component_size = COMPONENT[component_type]
        count = declared["count"]
        components = TYPE_SIZE[declared["type"]]
        normalized = bool(declared.get("normalized", False))
        if "bufferView" not in declared:
            zeros = [[0.0] * components for _ in range(count)]
            return Accessor(zeros, component_type, normalized)
        view = self.json["bufferViews"][declared["bufferView"]]
        buffer = self.buffers[view.get("buffer", 0)]
        start = view.get("byteOffset", 0) + declared.get("byteOffset", 0)
        stride = view.get("byteStride") or components * component_size
        values: List[List[float]] = []
        for i in range(count):
            offset = start + i * stride
            if offset + components * component_size > len(buffer):
                raise GltfError(f"accessor {index} reads past buffer end")
            raw = struct.unpack_from("<" + fmt * components, buffer, offset)
            if normalized and component_type in (5121, 5123):
                scale = 255.0 if component_type == 5121 else 65535.0
                raw = tuple(value / scale for value in raw)
            values.append(list(raw))
        return Accessor(values, component_type, normalized)

    # -- scene helpers ------------------------------------------------------
    def node_matrix(self, index: int) -> List[float]:
        node = self.json["nodes"][index]
        if "matrix" in node:
            return list(node["matrix"])
        translation = node.get("translation", [0.0, 0.0, 0.0])
        rotation = node.get("rotation", [0.0, 0.0, 0.0, 1.0])
        scale = node.get("scale", [1.0, 1.0, 1.0])
        return compose_trs(translation, rotation, scale)

    def mesh_nodes(self) -> List[int]:
        return [i for i, node in enumerate(self.json.get("nodes", [])) if "mesh" in node]


def compose_trs(translation, rotation, scale) -> List[float]:
    """Column-major TRS matrix, matching glTF's matrix layout."""
    x, y, z, w = rotation
    xx, yy, zz = x * x, y * y, z * z
    xy, xz, yz = x * y, x * z, y * z
    wx, wy, wz = w * x, w * y, w * z
    sx, sy, sz = scale
    return [
        (1 - 2 * (yy + zz)) * sx, (2 * (xy + wz)) * sx, (2 * (xz - wy)) * sx, 0.0,
        (2 * (xy - wz)) * sy, (1 - 2 * (xx + zz)) * sy, (2 * (yz + wx)) * sy, 0.0,
        (2 * (xz + wy)) * sz, (2 * (yz - wx)) * sz, (1 - 2 * (xx + yy)) * sz, 0.0,
        translation[0], translation[1], translation[2], 1.0,
    ]


def quat_slerp(a: List[float], b: List[float], t: float) -> List[float]:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    dot = ax * bx + ay * by + az * bz + aw * bw
    if dot < 0.0:
        bx, by, bz, bw, dot = -bx, -by, -bz, -bw, -dot
    if dot > 0.9995:
        out = [ax + t * (bx - ax), ay + t * (by - ay), az + t * (bz - az), aw + t * (bw - aw)]
    else:
        theta = __import__("math").acos(max(-1.0, min(1.0, dot)))
        sin_theta = __import__("math").sin(theta)
        wa = __import__("math").sin((1.0 - t) * theta) / sin_theta
        wb = __import__("math").sin(t * theta) / sin_theta
        out = [ax * wa + bx * wb, ay * wa + by * wb, az * wa + bz * wb, aw * wa + bw * wb]
    length = sum(value * value for value in out) ** 0.5
    if length <= 1e-8:
        return [0.0, 0.0, 0.0, 1.0]
    return [value / length for value in out]


def lerp(a: List[float], b: List[float], t: float) -> List[float]:
    return [a[i] + (b[i] - a[i]) * t for i in range(len(a))]


def sample_channel(times: List[float], values: List[List[float]], t: float,
                   interpolation: str, is_rotation: bool) -> List[float]:
    if not times:
        return values[0] if values else [0.0, 0.0, 0.0, 1.0]
    if t <= times[0]:
        return list(values[0])
    if t >= times[-1]:
        return list(values[-1])
    lo, hi = 0, len(times) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if times[mid] <= t:
            lo = mid
        else:
            hi = mid
    span = times[hi] - times[lo]
    alpha = 0.0 if span <= 1e-8 else (t - times[lo]) / span
    if interpolation == "STEP":
        return list(values[lo])
    if is_rotation:
        return quat_slerp(values[lo], values[hi], alpha)
    return lerp(values[lo], values[hi], alpha)


def read_gltf_info(path: str) -> Dict[str, object]:
    gltf = Gltf.load(path)
    meshes = gltf.json.get("meshes", [])
    tri_count = 0
    for mesh in meshes:
        for primitive in mesh.get("primitives", []):
            if "indices" in primitive:
                tri_count += gltf.json["accessors"][primitive["indices"]]["count"] // 3
    return {
        "meshes": len(meshes),
        "triangles": tri_count,
        "skins": len(gltf.json.get("skins", [])),
        "animations": [anim.get("name", f"anim{index}") for index, anim in enumerate(gltf.json.get("animations", []))],
        "images": len(gltf.json.get("images", [])),
        "materials": len(gltf.json.get("materials", [])),
    }


__all__ = [
    "Accessor",
    "Gltf",
    "GltfError",
    "compose_trs",
    "lerp",
    "quat_slerp",
    "read_gltf_info",
    "sample_channel",
    "Tuple",
    "Optional",
]
