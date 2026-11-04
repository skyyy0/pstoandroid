"""glTF 2.0 -> .smesh/.sanm packer.

This is the last automated step of the asset pipeline:

    data.cpk -> *.xfbin  (CriPakTools / this repo's cpk module)
        -> Blender + XFBIN importer -> glTF 2.0 (.glb)
        -> this packer -> .smesh / .sanm -> APK assets/storm/

Keeping the exchange format at glTF means the heavy reverse-engineering lives in
the community XFBIN tools, while the runtime stays stable and testable.
"""

from __future__ import annotations

import base64
import os
from typing import Dict, List, Optional, Tuple

from .binary import fnv1a32
from .formats import (
    AnimClip,
    Bone,
    BoneKey,
    BoneTrack,
    Material,
    MeshAsset,
    SubMesh,
    Texture,
    Vertex,
    write_anim,
    write_mesh,
)
from .glb import Gltf, GltfError, compose_trs, sample_channel
from .png import PngError, decode_png

MAX_INFLUENCES = 4
# The GLES renderer uploads bone matrices as one std140 uniform block
# (uBones[128], mirrored by storm::kMaxBones). Larger rigs are rejected here
# instead of failing on device.
MAX_BONES = 128


class PackError(Exception):
    pass


def _apply_matrix(matrix: List[float], position: List[float]) -> List[float]:
    x, y, z = position
    return [
        matrix[0] * x + matrix[4] * y + matrix[8] * z + matrix[12],
        matrix[1] * x + matrix[5] * y + matrix[9] * z + matrix[13],
        matrix[2] * x + matrix[6] * y + matrix[10] * z + matrix[14],
    ]


def _rows_from_column_major(matrix: List[float]) -> List[List[float]]:
    return [
        [matrix[0], matrix[4], matrix[8]],
        [matrix[1], matrix[5], matrix[9]],
        [matrix[2], matrix[6], matrix[10]],
    ]


def _inverse_rows(m: List[List[float]]) -> List[List[float]]:
    (a, b, c), (d, e, f), (g, h, i) = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-12:
        return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    inv = 1.0 / det
    return [
        [(e * i - f * h) * inv, (c * h - b * i) * inv, (b * f - c * e) * inv],
        [(f * g - d * i) * inv, (a * i - c * g) * inv, (c * d - a * f) * inv],
        [(d * h - e * g) * inv, (b * g - a * h) * inv, (a * e - b * d) * inv],
    ]


def _normal_matrix(matrix: List[float]) -> List[float]:
    """Inverse-transpose of the upper 3x3, stored column-major."""
    inverse = _inverse_rows(_rows_from_column_major(matrix))
    out = [0.0] * 9
    for row in range(3):
        for column in range(3):
            # (M^-1)^T element (row, column) == inverse[column][row]
            out[column * 3 + row] = inverse[column][row]
    return out


def _transform_normal(m: List[float], normal: List[float]) -> List[float]:
    x, y, z = normal
    out = [
        m[0] * x + m[3] * y + m[6] * z,
        m[1] * x + m[4] * y + m[7] * z,
        m[2] * x + m[5] * y + m[8] * z,
    ]
    length = (out[0] ** 2 + out[1] ** 2 + out[2] ** 2) ** 0.5
    if length <= 1e-8:
        return [0.0, 1.0, 0.0]
    return [value / length for value in out]


def _weights_to_bytes(weights: List[float]) -> Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int]]:
    pairs = [(max(0.0, float(w)), i) for i, w in enumerate(weights[:MAX_INFLUENCES])]
    pairs.sort(reverse=True)
    total = sum(w for w, _ in pairs)
    if total <= 1e-6:
        return (0, 0, 0, 0), (255, 0, 0, 0)
    # If the exporter already wrote 0..255 integers keep the scale.
    scale = 255.0 if total > 1.5 else 1.0
    normalized = [(w / total) * 255.0 for w, _ in pairs]
    indices = [i for _, i in pairs]
    while len(indices) < MAX_INFLUENCES:
        indices.append(0)
    quantized = [int(round(value)) for value in normalized]
    diff = 255 - sum(quantized)
    quantized[0] += diff
    quantized = [max(0, min(255, value)) for value in quantized]
    return tuple(indices), tuple(quantized)


def _image_rgba(gltf: Gltf, image_index: int) -> Texture:
    image = gltf.json["images"][image_index]
    if "bufferView" in image:
        view = gltf.json["bufferViews"][image["bufferView"]]
        buffer = gltf.buffers[view.get("buffer", 0)]
        start = view.get("byteOffset", 0)
        payload = buffer[start:start + view["byteLength"]]
    elif "uri" in image:
        uri = image["uri"]
        if uri.startswith("data:"):
            payload = base64.b64decode(uri.split(",", 1)[1])
        else:
            with open(os.path.join(gltf.base_dir, uri), "rb") as handle:
                payload = handle.read()
    else:
        raise PackError(f"image {image_index} has neither bufferView nor uri")
    mime = image.get("mimeType", "")
    if "jpeg" in mime or payload[:2] == b"\xff\xd8":
        raise PackError("JPEG textures are not supported; re-export as PNG")
    try:
        width, height, rgba = decode_png(payload)
    except PngError as exc:
        raise PackError(f"image {image_index}: {exc}") from exc
    return Texture(width, height, rgba)


def _build_materials(gltf: Gltf, primitive_materials: List[Optional[int]]) -> Tuple[List[Material], List[Texture], Dict[int, int]]:
    materials: List[Material] = []
    textures: List[Texture] = []
    texture_slots: Dict[int, int] = {}
    material_map: Dict[int, int] = {}
    gltf_materials = gltf.json.get("materials", [])
    for gltf_index in primitive_materials:
        key = gltf_index if gltf_index is not None else -1
        if key in material_map:
            continue
        material_map[key] = len(materials)
        if key < 0 or key >= len(gltf_materials):
            materials.append(Material())
            continue
        source = gltf_materials[key]
        pbr = source.get("pbrMetallicRoughness", {})
        base = list(pbr.get("baseColorFactor", [1.0, 1.0, 1.0, 1.0]))
        albedo = -1
        texture_info = pbr.get("baseColorTexture")
        if texture_info is not None:
            texture_index = texture_info["index"]
            image_index = gltf.json["textures"][texture_index]["source"]
            if image_index in texture_slots:
                albedo = texture_slots[image_index]
            else:
                albedo = len(textures)
                textures.append(_image_rgba(gltf, image_index))
                texture_slots[image_index] = albedo
        emissions = source.get("emissiveFactor", [0.0, 0.0, 0.0])
        emissive = max(emissions) if emissions else 0.0
        materials.append(
            Material(
                base_color=tuple(base),
                rim_color=(0.35, 0.45, 0.7, 1.0),
                params=(float(source.get("_specular", 0.2)), 24.0, float(emissive),
                        float(source.get("alphaCutoff", 0.5))),
                albedo=albedo,
            )
        )
    return materials, textures, material_map


def _skeleton(gltf: Gltf, skin_index: int):
    skin = gltf.json["skins"][skin_index]
    joints = skin["joints"]
    joint_to_bone = {node: index for index, node in enumerate(joints)}
    nodes = gltf.json["nodes"]

    parents: Dict[int, int] = {}
    for parent_index, node in enumerate(nodes):
        for child in node.get("children", []):
            parents[child] = parent_index

    bones: List[Bone] = []
    inverse_accessor = None
    if "inverseBindMatrices" in skin:
        inverse_accessor = gltf.accessor(skin["inverseBindMatrices"])
    for bone_index, node_index in enumerate(joints):
        name = nodes[node_index].get("name") or f"bone{bone_index}"
        parent_node = parents.get(node_index)
        parent_bone = joint_to_bone.get(parent_node, -1) if parent_node is not None else -1
        if inverse_accessor is not None and bone_index < len(inverse_accessor.values):
            inverse = inverse_accessor.values[bone_index]
        else:
            inverse = _invert_rigid(gltf.node_matrix(node_index))
        bones.append(Bone(name_hash=fnv1a32(name), parent=parent_bone, inverse_bind=tuple(inverse)))
    bone_names = [nodes[node].get("name") or f"bone{i}" for i, node in enumerate(joints)]
    return bones, joint_to_bone, bone_names


def _invert_rigid(matrix: List[float]) -> List[float]:
    """Inverse of a column-major affine matrix (rotation/translation only)."""
    inverse = _inverse_rows(_rows_from_column_major(matrix))
    tx, ty, tz = matrix[12], matrix[13], matrix[14]
    out = [0.0] * 16
    for row in range(3):
        for column in range(3):
            out[column * 4 + row] = inverse[row][column]
        out[12 + row] = -sum(inverse[row][axis] * (tx, ty, tz)[axis] for axis in range(3))
    out[15] = 1.0
    return out


def build_mesh(gltf: Gltf, name: str) -> MeshAsset:
    mesh_nodes = gltf.mesh_nodes()
    if not mesh_nodes:
        raise PackError("glTF has no mesh node")
    node_index = mesh_nodes[0]
    node = gltf.json["nodes"][node_index]
    mesh = gltf.json["meshes"][node["mesh"]]
    skin_index = node.get("skin")
    bone_names: List[str] = []

    if skin_index is not None:
        bones, joint_to_bone, bone_names = _skeleton(gltf, skin_index)
        world = None
    else:
        bones, joint_to_bone, bone_names = [], {}, []
        world = gltf.node_matrix(node_index)

    primitives = mesh.get("primitives", [])
    materials, textures, material_map = _build_materials(
        gltf, [primitive.get("material") for primitive in primitives]
    )

    asset = MeshAsset(name=name, bones=bones, materials=materials, textures=textures)
    normal_matrix = _normal_matrix(world) if world else None

    for primitive_index, primitive in enumerate(primitives):
        if primitive.get("mode", 4) != 4:
            raise PackError(
                f"primitive {primitive_index} uses mode {primitive.get('mode')}; "
                "only indexed triangles are supported (triangulate in Blender)"
            )
        attributes = primitive["attributes"]
        if "POSITION" not in attributes:
            raise PackError("primitive without POSITION")
        positions = gltf.accessor(attributes["POSITION"]).values
        normals = gltf.accessor(attributes["NORMAL"]).values if "NORMAL" in attributes else None
        uvs = gltf.accessor(attributes["TEXCOORD_0"]).values if "TEXCOORD_0" in attributes else None
        joints = gltf.accessor(attributes["JOINTS_0"]).values if "JOINTS_0" in attributes else None
        weights = gltf.accessor(attributes["WEIGHTS_0"]).values if "WEIGHTS_0" in attributes else None

        base_vertex = len(asset.vertices)
        for i, position in enumerate(positions):
            position = list(position)
            normal = list(normals[i]) if normals else [0.0, 1.0, 0.0]
            uv = (float(uvs[i][0]), float(uvs[i][1])) if uvs else (0.0, 0.0)
            if world:
                position = _apply_matrix(world, position)
                normal = _transform_normal(normal_matrix or [], normal)
            if joints and weights:
                remapped = [joint_to_bone.get(int(j), -1) for j in joints[i]]
                combined = [
                    (float(weights[i][slot]), remapped[slot])
                    for slot in range(min(len(remapped), len(weights[i])))
                    if remapped[slot] >= 0
                ]
                combined.sort(reverse=True)
                total = sum(weight for weight, _ in combined)
                pairs: List[Tuple[int, int]] = []
                if total > 1e-6:
                    pairs = [(bone, int(round(weight / total * 255)))
                             for weight, bone in combined[:MAX_INFLUENCES]]
                    slack = 255 - sum(weight for _, weight in pairs)
                    pairs[0] = (pairs[0][0], pairs[0][1] + slack)
                else:
                    pairs = [(combined[0][1] if combined else 0, 255)]
                bone_indices = [0, 0, 0, 0]
                bone_weights = [0, 0, 0, 0]
                for slot, (bone, weight) in enumerate(pairs):
                    bone_indices[slot] = bone
                    bone_weights[slot] = max(0, min(255, weight))
                asset.vertices.append(
                    Vertex(tuple(position), tuple(normal), uv,
                           tuple(bone_indices), tuple(bone_weights))
                )
            else:
                asset.vertices.append(Vertex(tuple(position), tuple(normal), uv))

        material_index = material_map[primitive.get("material") if primitive.get("material") is not None else -1]
        index_offset = len(asset.indices)
        if "indices" in primitive:
            indices = [int(value[0]) for value in gltf.accessor(primitive["indices"]).values]
        else:
            indices = list(range(len(positions)))
        if len(indices) % 3 != 0:
            raise PackError("index count is not a multiple of 3")
        asset.indices.extend(index + base_vertex for index in indices)
        asset.submeshes.append(
            SubMesh(index_offset=index_offset, index_count=len(indices), material=material_index)
        )
    return asset


def build_animations(gltf: Gltf) -> List[AnimClip]:
    nodes = gltf.json.get("nodes", [])
    clips: List[AnimClip] = []
    for animation_index, animation in enumerate(gltf.json.get("animations", [])):
        name = animation.get("name") or f"clip{animation_index}"
        per_node: Dict[int, Dict[str, Dict[str, object]]] = {}
        duration = 0.0
        for channel in animation.get("channels", []):
            target = channel.get("target", {})
            path = target.get("path")
            if path not in ("rotation", "translation"):
                continue
            sampler = animation["samplers"][channel["sampler"]]
            times = [float(v[0]) for v in gltf.accessor(sampler["input"]).values]
            values = gltf.accessor(sampler["output"]).values
            if not times:
                continue
            duration = max(duration, times[-1])
            per_node.setdefault(target["node"], {})[path] = {
                "times": times,
                "values": values,
                "interpolation": sampler.get("interpolation", "LINEAR"),
            }

        clip = AnimClip(name=name, duration=duration, loop=True)
        for node_index, tracks in per_node.items():
            node = nodes[node_index]
            bone_name = node.get("name") or f"node{node_index}"
            rotation = tracks.get("rotation")
            translation = tracks.get("translation")
            times = set()
            for track in (rotation, translation):
                if track:
                    times.update(track["times"])
            ordered = sorted(times)
            rest_rotation = list(node.get("rotation", [0.0, 0.0, 0.0, 1.0]))
            rest_translation = list(node.get("translation", [0.0, 0.0, 0.0]))
            keys: List[BoneKey] = []
            previous = None
            for t in ordered:
                if rotation:
                    value = sample_channel(rotation["times"], rotation["values"], t,
                                           rotation["interpolation"], True)
                else:
                    value = rest_rotation
                if previous is not None and sum(a * b for a, b in zip(value, previous)) < 0.0:
                    value = [-component for component in value]
                previous = value
                if translation:
                    position = sample_channel(translation["times"], translation["values"], t,
                                             translation["interpolation"], False)
                else:
                    position = rest_translation
                keys.append(BoneKey(time=t, rotation=tuple(value), position=tuple(position)))
            clip.tracks.append(BoneTrack(name_hash=fnv1a32(bone_name), keys=keys))
        if clip.tracks:
            clips.append(clip)
    return clips


def pack_glb(glb_path: str, out_dir: str, base_name: Optional[str] = None,
             manifest_path: Optional[str] = None, scale: float = 1.0,
             prefix: str = "") -> Dict[str, object]:
    """Convert one .glb into packages under ``out_dir``.

    Manifest paths are written relative to the Android ``assets/`` root, with
    ``prefix`` prepended (``--prefix storm`` -> ``storm/ninja.smesh``).
    """
    gltf = Gltf.load(glb_path)
    name = base_name or os.path.splitext(os.path.basename(glb_path))[0]
    mesh = build_mesh(gltf, name)
    if len(mesh.bones) > MAX_BONES:
        raise PackError(
            f"{name}: rig has {len(mesh.bones)} bones, the mobile renderer supports "
            f"at most {MAX_BONES}. Merge non-deforming bones or split the character "
            "into separately drawn parts before exporting."
        )
    if abs(scale - 1.0) > 1e-6:
        mesh.vertices = [
            Vertex(
                (v.position[0] * scale, v.position[1] * scale, v.position[2] * scale),
                v.normal, v.uv, v.joints, v.weights,
            )
            for v in mesh.vertices
        ]
        mesh.bones = [
            Bone(b.name_hash, b.parent, tuple(_scale_inverse_bind(b.inverse_bind, scale)))
            for b in mesh.bones
        ]

    os.makedirs(out_dir, exist_ok=True)
    files: List[str] = []
    mesh_path = os.path.join(out_dir, f"{name}.smesh")
    with open(mesh_path, "wb") as handle:
        handle.write(write_mesh(mesh))
    files.append(mesh_path)

    def asset_path(filename: str) -> str:
        return f"{prefix.strip('/')}/{filename}" if prefix.strip("/") else filename

    lines = [f"mesh {name} {asset_path(f'{name}.smesh')}"]
    clips = build_animations(gltf)
    for clip in clips:
        clip_path = os.path.join(out_dir, f"{name}_{clip.name}.sanm")
        with open(clip_path, "wb") as handle:
            handle.write(write_anim(clip))
        files.append(clip_path)
        lines.append(
            f"anim {name} {clip.name} {asset_path(f'{name}_{clip.name}.sanm')}"
        )

    if manifest_path:
        previous = ""
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as handle:
                previous = handle.read()
        existing = {line.strip() for line in previous.splitlines() if line.strip()}
        with open(manifest_path, "w", encoding="utf-8") as handle:
            header = "# storm manifest v1\n"
            handle.write(header)
            for line in sorted(existing | {line.strip() for line in lines}):
                if line.startswith("#"):
                    continue
                handle.write(line + "\n")

    return {
        "mesh": mesh_path,
        "clips": [clip.name for clip in clips],
        "files": files,
        "vertices": len(mesh.vertices),
        "triangles": len(mesh.indices) // 3,
        "bones": len(mesh.bones),
    }


def _scale_inverse_bind(inverse_bind, scale: float) -> List[float]:
    # Vertices are scaled by s at pack time, so the inverse bind translation
    # (column 3 of the column-major matrix) must be divided by s.
    out = list(inverse_bind)
    for index in (12, 13, 14):
        out[index] /= scale
    return out


__all__ = ["PackError", "GltfError", "build_animations", "build_mesh", "pack_glb"]
