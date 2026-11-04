"""Procedurally generated, original demo assets.

The engine must be runnable and testable without shipping a single byte of
retail game data.  These two stylised fighters and the dojo arena are generated
from scratch (boxes + authored keyframes, no ripped content), so the APK boots
into a playable vertical slice that exercises skinning, animation, the toon
shader, the hit system and the adaptive-resolution governor.

Retail assets enter through the glTF pipeline in ``pack.py`` and the same
manifest, so swapping the slice for converted characters is a data change.
"""

from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

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

Vec3 = Tuple[float, float, float]

# name, parent, rest position relative to the parent (bind pose)
BONES: Sequence[Tuple[str, Optional[str], Vec3]] = (
    ("root", None, (0.0, 0.0, 0.0)),
    ("hips", "root", (0.0, 0.95, 0.0)),
    ("spine", "hips", (0.0, 0.18, 0.0)),
    ("chest", "spine", (0.0, 0.22, 0.0)),
    ("head", "chest", (0.0, 0.24, 0.0)),
    ("shoulder_l", "chest", (0.20, 0.02, 0.0)),
    ("elbow_l", "shoulder_l", (0.0, -0.28, 0.0)),
    ("wrist_l", "elbow_l", (0.0, -0.26, 0.0)),
    ("shoulder_r", "chest", (-0.20, 0.02, 0.0)),
    ("elbow_r", "shoulder_r", (0.0, -0.28, 0.0)),
    ("wrist_r", "elbow_r", (0.0, -0.26, 0.0)),
    ("hip_l", "hips", (0.12, -0.05, 0.0)),
    ("knee_l", "hip_l", (0.0, -0.43, 0.0)),
    ("ankle_l", "knee_l", (0.0, -0.43, 0.0)),
    ("hip_r", "hips", (-0.12, -0.05, 0.0)),
    ("knee_r", "hip_r", (0.0, -0.43, 0.0)),
    ("ankle_r", "knee_r", (0.0, -0.43, 0.0)),
)


class MeshBuilder:
    def __init__(self) -> None:
        self.vertices: List[Vertex] = []
        self.indices: List[int] = []
        self.materials: List[Material] = []
        self.textures: List[Texture] = []
        self.bones: List[Bone] = []
        self.submeshes: List[SubMesh] = []
        self._bone_lookup: Dict[str, int] = {}

    def add_bone(self, name: str, parent: int, inverse_bind: Sequence[float]) -> int:
        index = len(self.bones)
        self.bones.append(Bone(fnv1a32(name), parent, tuple(inverse_bind)))
        self._bone_lookup[name] = index
        return index

    def bone(self, name: str) -> int:
        return self._bone_lookup[name]

    def add_material(self, material: Material) -> int:
        self.materials.append(material)
        return len(self.materials) - 1

    def box(self, center: Vec3, size: Vec3, material: int, bone: int,
            uv_scale: float = 1.0) -> None:
        cx, cy, cz = center
        hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
        faces = (
            ((0, 0, 1), ((cx - hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz + hz),
                         (cx + hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz + hz))),
            ((0, 0, -1), ((cx + hx, cy - hy, cz - hz), (cx - hx, cy - hy, cz - hz),
                          (cx - hx, cy + hy, cz - hz), (cx + hx, cy + hy, cz - hz))),
            ((1, 0, 0), ((cx + hx, cy - hy, cz + hz), (cx + hx, cy - hy, cz - hz),
                         (cx + hx, cy + hy, cz - hz), (cx + hx, cy + hy, cz + hz))),
            ((-1, 0, 0), ((cx - hx, cy - hy, cz - hz), (cx - hx, cy - hy, cz + hz),
                          (cx - hx, cy + hy, cz + hz), (cx - hx, cy + hy, cz - hz))),
            ((0, 1, 0), ((cx - hx, cy + hy, cz + hz), (cx + hx, cy + hy, cz + hz),
                         (cx + hx, cy + hy, cz - hz), (cx - hx, cy + hy, cz - hz))),
            ((0, -1, 0), ((cx - hx, cy - hy, cz - hz), (cx + hx, cy - hy, cz - hz),
                          (cx + hx, cy - hy, cz + hz), (cx - hx, cy - hy, cz + hz))),
        )
        base = len(self.vertices)
        for normal, corners in faces:
            uvs = ((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0))
            for corner, uv in zip(corners, uvs):
                self.vertices.append(
                    Vertex(corner, normal, (uv[0] * uv_scale, uv[1] * uv_scale),
                           (bone, 0, 0, 0), (255, 0, 0, 0))
                )
            self.indices.extend((base, base + 1, base + 2, base, base + 2, base + 3))
            base += 4
        material_index = material
        self.submeshes.append(SubMesh(len(self.indices) - 36, 36, material_index))

    def finish(self, name: str) -> MeshAsset:
        merged: List[SubMesh] = []
        for submesh in self.submeshes:
            if merged and merged[-1].material == submesh.material and \
                    merged[-1].index_offset + merged[-1].index_count == submesh.index_offset:
                merged[-1].index_count += submesh.index_count
            else:
                merged.append(SubMesh(submesh.index_offset, submesh.index_count, submesh.material))
        return MeshAsset(
            name=name,
            vertices=self.vertices,
            indices=self.indices,
            submeshes=merged,
            materials=self.materials,
            bones=self.bones,
            textures=self.textures,
        )


def _inverse_translate(position: Vec3) -> List[float]:
    return [
        1.0, 0.0, 0.0, 0.0,
        0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0,
        -position[0], -position[1], -position[2], 1.0,
    ]


def _bone_world_positions() -> Dict[str, Vec3]:
    world: Dict[str, Vec3] = {}
    for name, parent, offset in BONES:
        if parent is None:
            world[name] = offset
        else:
            parent_pos = world[parent]
            world[name] = (parent_pos[0] + offset[0], parent_pos[1] + offset[1],
                           parent_pos[2] + offset[2])
    return world


def _skeleton_builder() -> Tuple[MeshBuilder, Dict[str, Vec3]]:
    world = _bone_world_positions()
    builder = MeshBuilder()
    for name, parent, _offset in BONES:
        parent_index = builder.bone(parent) if parent else -1
        builder.add_bone(name, parent_index, _inverse_translate(world[name]))
    return builder, world


def build_character(palette: str) -> MeshAsset:
    builder, world = _skeleton_builder()
    if palette == "rookie":
        suit = (0.92, 0.42, 0.12, 1.0)
        trim = (0.10, 0.16, 0.32, 1.0)
        accent = (0.95, 0.80, 0.35, 1.0)
    else:
        suit = (0.20, 0.22, 0.30, 1.0)
        trim = (0.55, 0.10, 0.16, 1.0)
        accent = (0.70, 0.75, 0.82, 1.0)
    skin = (0.93, 0.76, 0.62, 1.0)

    m_suit = builder.add_material(Material(suit, (0.5, 0.6, 0.85, 1.0), (0.25, 28.0, 0.0, 0.5)))
    m_trim = builder.add_material(Material(trim, (0.4, 0.5, 0.9, 1.0), (0.35, 40.0, 0.0, 0.5)))
    m_skin = builder.add_material(Material(skin, (0.7, 0.5, 0.4, 1.0), (0.15, 12.0, 0.0, 0.5)))
    m_accent = builder.add_material(Material(accent, (0.8, 0.7, 0.3, 1.0), (0.5, 60.0, 0.0, 0.5)))

    hips = world["hips"]
    builder.box((hips[0], hips[1] + 0.02, hips[2]), (0.34, 0.24, 0.26), m_suit, builder.bone("hips"))
    builder.box((hips[0], hips[1] + 0.05, hips[2]), (0.36, 0.08, 0.28), m_trim, builder.bone("hips"))

    spine = world["spine"]
    builder.box((spine[0], spine[1] + 0.10, spine[2]), (0.34, 0.22, 0.24), m_suit, builder.bone("spine"))
    chest = world["chest"]
    builder.box((chest[0], chest[1] + 0.06, chest[2]), (0.40, 0.30, 0.28), m_suit, builder.bone("chest"))
    builder.box((chest[0], chest[1] + 0.10, chest[2] + 0.02), (0.30, 0.16, 0.26), m_trim, builder.bone("chest"))
    # shoulder pads
    for side, bone in ((1.0, "shoulder_l"), (-1.0, "shoulder_r")):
        pos = world[bone]
        builder.box((pos[0] + 0.02 * side, pos[1] + 0.02, pos[2]), (0.18, 0.14, 0.20),
                    m_trim, builder.bone(bone))

    head = world["head"]
    builder.box((head[0], head[1] + 0.02, head[2]), (0.24, 0.24, 0.24), m_skin, builder.bone("head"))
    builder.box((head[0], head[1] + 0.15, head[2] - 0.01), (0.26, 0.10, 0.26), m_accent, builder.bone("head"))
    builder.box((head[0], head[1] + 0.04, head[2] + 0.13), (0.16, 0.05, 0.04), m_trim, builder.bone("head"))

    for bone, length, width in (("shoulder_l", 0.28, 0.14), ("shoulder_r", 0.28, 0.14)):
        pos = world[bone]
        builder.box((pos[0], pos[1] - length / 2, pos[2]), (width, length, width * 1.05),
                    m_skin, builder.bone(bone))
        elbow = world[bone.replace("shoulder", "elbow")]
        builder.box((elbow[0], elbow[1] - 0.13, elbow[2]), (width * 0.92, 0.26, width),
                    m_skin, builder.bone(bone.replace("shoulder", "elbow")))
        wrist = world[bone.replace("shoulder", "wrist")]
        builder.box((wrist[0], wrist[1] - 0.03, wrist[2] + 0.01), (0.12, 0.12, 0.14),
                    m_trim, builder.bone(bone.replace("shoulder", "wrist")))

    for hip, knee, ankle in (("hip_l", "knee_l", "ankle_l"), ("hip_r", "knee_r", "ankle_r")):
        pos = world[hip]
        builder.box((pos[0], pos[1] - 0.21, pos[2]), (0.17, 0.44, 0.18), m_trim, builder.bone(hip))
        knee_pos = world[knee]
        builder.box((knee_pos[0], knee_pos[1] - 0.21, knee_pos[2]), (0.15, 0.44, 0.16),
                    m_trim, builder.bone(knee))
        ankle_pos = world[ankle]
        builder.box((ankle_pos[0], ankle_pos[1] - 0.02, ankle_pos[2] + 0.06),
                    (0.17, 0.12, 0.30), m_accent, builder.bone(ankle))

    return builder.finish(palette)


def build_arena() -> MeshAsset:
    builder, _world = _skeleton_builder()
    # Arena is static: everything is rigidly bound to the root bone so the same
    # skinned pipeline (and the same shader) can draw it.
    root = builder.bone("root")
    builder.bones = [builder.bones[root]]

    checker = _checker_texture(64, 10)
    builder.textures.append(checker)
    floor = builder.add_material(
        Material((1.0, 1.0, 1.0, 1.0), (0.35, 0.35, 0.45, 1.0), (0.05, 8.0, 0.0, 0.5), albedo=0)
    )
    wood = builder.add_material(Material((0.38, 0.24, 0.16, 1.0), (0.5, 0.4, 0.3, 1.0), (0.1, 8.0, 0.0, 0.5)))
    stone = builder.add_material(Material((0.24, 0.24, 0.28, 1.0), (0.4, 0.45, 0.6, 1.0), (0.1, 16.0, 0.0, 0.5)))

    builder.box((0.0, -0.25, 0.0), (26.0, 0.5, 26.0), floor, 0, uv_scale=13.0)
    # low ring wall
    builder.box((0.0, 0.30, -13.0), (26.0, 1.1, 0.6), stone, 0)
    builder.box((0.0, 0.30, 13.0), (26.0, 1.1, 0.6), stone, 0)
    builder.box((-13.0, 0.30, 0.0), (0.6, 1.1, 26.0), stone, 0)
    builder.box((13.0, 0.30, 0.0), (0.6, 1.1, 26.0), stone, 0)
    # pillars + torii-inspired frame
    for x, z in ((-9.0, -9.0), (9.0, -9.0), (-9.0, 9.0), (9.0, 9.0)):
        builder.box((x, 2.6, z), (0.9, 5.8, 0.9), wood, 0)
        builder.box((x, 5.4, z), (1.3, 0.4, 1.3), stone, 0)
    for x in (-9.0, 9.0):
        builder.box((x, 5.9, 9.0), (0.4, 0.4, 6.4), wood, 0)
    builder.box((0.0, 6.1, 9.0), (19.0, 0.5, 1.6), wood, 0)
    builder.box((-6.0, 6.6, 9.0), (0.6, 1.4, 1.6), stone, 0)
    builder.box((6.0, 6.6, 9.0), (0.6, 1.4, 1.6), stone, 0)
    return builder.finish("arena")


def _checker_texture(size: int, squares: int) -> Texture:
    rgba = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            cx = x * squares // size
            cy = y * squares // size
            bright = ((cx + cy) & 1) == 0
            base = 168 if bright else 118
            offset = (y * size + x) * 4
            rgba[offset + 0] = base
            rgba[offset + 1] = base - 6
            rgba[offset + 2] = base - 12
            rgba[offset + 3] = 255
    return Texture(size, size, bytes(rgba))


# --------------------------------------------------------------------------
# animation authoring
# --------------------------------------------------------------------------
def _q_x(degrees: float) -> Tuple[float, float, float, float]:
    half = math.radians(degrees) * 0.5
    return (math.sin(half), 0.0, 0.0, math.cos(half))


def _q_z(degrees: float) -> Tuple[float, float, float, float]:
    half = math.radians(degrees) * 0.5
    return (0.0, 0.0, math.sin(half), math.cos(half))


def _q_mul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
        aw * bw - ax * bx - ay * by - az * bz,
    )


def _rest_offsets() -> Dict[str, Vec3]:
    return {name: offset for name, _parent, offset in BONES}


def _clip(name: str, duration: float, frames: Dict[str, List[Tuple[float, Tuple[float, float, float, float]]]],
          root_offset: Optional[List[Tuple[float, Vec3]]] = None) -> AnimClip:
    offsets = _rest_offsets()
    clip = AnimClip(name=name, duration=duration, loop=True)
    for bone, keys in frames.items():
        track = BoneTrack(fnv1a32(bone))
        for time, rotation in keys:
            position = offsets[bone]
            if bone == "hips" and root_offset:
                # vertical bob / jump arc
                position = (0.0, 0.95 + _sample_offsets(root_offset, time)[1], 0.0)
            track.keys.append(BoneKey(time, rotation, position))
        clip.tracks.append(track)
    return clip


def _sample_offsets(keys: List[Tuple[float, Vec3]], time: float) -> Vec3:
    if not keys:
        return (0.0, 0.0, 0.0)
    if time <= keys[0][0]:
        return keys[0][1]
    if time >= keys[-1][0]:
        return keys[-1][1]
    for index in range(len(keys) - 1):
        t0, v0 = keys[index]
        t1, v1 = keys[index + 1]
        if t0 <= time <= t1:
            alpha = 0.0 if t1 - t0 <= 1e-6 else (time - t0) / (t1 - t0)
            return tuple(v0[i] + (v1[i] - v0[i]) * alpha for i in range(3))
    return keys[-1][1]


def build_animations() -> List[AnimClip]:
    identity = (0.0, 0.0, 0.0, 1.0)
    clips: List[AnimClip] = []

    clips.append(_clip("idle", 2.4, {
        "chest": [(0.0, _q_x(-1.5)), (1.2, _q_x(1.5)), (2.4, _q_x(-1.5))],
        "head": [(0.0, _q_z(2.0)), (1.2, _q_z(-2.0)), (2.4, _q_z(2.0))],
        "shoulder_l": [(0.0, _q_z(-4.0)), (1.2, _q_z(-1.0)), (2.4, _q_z(-4.0))],
        "shoulder_r": [(0.0, _q_z(4.0)), (1.2, _q_z(1.0)), (2.4, _q_z(4.0))],
        "elbow_l": [(0.0, _q_x(-8.0)), (1.2, _q_x(-4.0)), (2.4, _q_x(-8.0))],
        "elbow_r": [(0.0, _q_x(-8.0)), (1.2, _q_x(-4.0)), (2.4, _q_x(-8.0))],
    }, root_offset=[(0.0, (0.0, 0.0, 0.0)), (1.2, (0.0, 0.012, 0.0)), (2.4, (0.0, 0.0, 0.0))]))

    run_cycle = [(0.0, 34.0), (0.25, 0.0), (0.5, -34.0), (0.75, 0.0), (1.0, 34.0)]
    clips.append(_clip("run", 1.0, {
        "hip_l": [(t, _q_x(a)) for t, a in run_cycle],
        "hip_r": [(t, _q_x(-a)) for t, a in run_cycle],
        "knee_l": [(t, _q_x(-max(0.0, -a) - 8.0)) for t, a in run_cycle],
        "knee_r": [(t, _q_x(-max(0.0, a) - 8.0)) for t, a in run_cycle],
        "shoulder_l": [(t, _q_x(-a * 0.8)) for t, a in run_cycle],
        "shoulder_r": [(t, _q_x(a * 0.8)) for t, a in run_cycle],
        "elbow_l": [(0.0, _q_x(-35.0)), (0.5, _q_x(-25.0)), (1.0, _q_x(-35.0))],
        "elbow_r": [(0.0, _q_x(-25.0)), (0.5, _q_x(-35.0)), (1.0, _q_x(-25.0))],
        "chest": [(0.0, _q_x(6.0)), (0.5, _q_x(3.0)), (1.0, _q_x(6.0))],
    }, root_offset=[(0.0, (0.0, 0.0, 0.0)), (0.25, (0.0, 0.05, 0.0)),
                    (0.5, (0.0, 0.0, 0.0)), (0.75, (0.0, 0.05, 0.0)), (1.0, (0.0, 0.0, 0.0))]))

    clips.append(_clip("jump", 0.7, {
        "hip_l": [(0.0, _q_x(20.0)), (0.35, _q_x(45.0)), (0.7, _q_x(10.0))],
        "hip_r": [(0.0, _q_x(-10.0)), (0.35, _q_x(-20.0)), (0.7, _q_x(-5.0))],
        "knee_l": [(0.0, _q_x(-30.0)), (0.35, _q_x(-60.0)), (0.7, _q_x(-15.0))],
        "knee_r": [(0.0, _q_x(-20.0)), (0.35, _q_x(-40.0)), (0.7, _q_x(-10.0))],
        "shoulder_l": [(0.0, _q_z(-25.0)), (0.35, _q_z(-55.0)), (0.7, _q_z(-20.0))],
        "shoulder_r": [(0.0, _q_z(25.0)), (0.35, _q_z(55.0)), (0.7, _q_z(20.0))],
    }, root_offset=[(0.0, (0.0, 0.0, 0.0)), (0.2, (0.0, 0.55, 0.0)),
                    (0.45, (0.0, 0.65, 0.0)), (0.7, (0.0, 0.0, 0.0))]))

    clips.append(_clip("attack", 0.5, {
        "chest": [(0.0, _q_z(0.0)), (0.12, _q_z(-22.0)), (0.25, _q_z(18.0)), (0.5, _q_z(0.0))],
        "shoulder_r": [(0.0, _q_x(0.0)), (0.12, _q_x(35.0)), (0.25, _q_x(-75.0)), (0.5, _q_x(0.0))],
        "elbow_r": [(0.0, _q_x(-20.0)), (0.12, _q_x(-80.0)), (0.25, _q_x(-8.0)), (0.5, _q_x(-20.0))],
        "shoulder_l": [(0.0, _q_z(-5.0)), (0.25, _q_z(-25.0)), (0.5, _q_z(-5.0))],
        "wrist_r": [(0.0, identity), (0.25, identity), (0.5, identity)],
        "hip_l": [(0.0, _q_z(3.0)), (0.25, _q_z(12.0)), (0.5, _q_z(3.0))],
    }))

    clips.append(_clip("kick", 0.62, {
        "chest": [(0.0, _q_x(0.0)), (0.15, _q_x(-12.0)), (0.3, _q_x(14.0)), (0.62, _q_x(0.0))],
        "hip_r": [(0.0, _q_x(0.0)), (0.15, _q_x(-45.0)), (0.3, _q_x(-95.0)), (0.62, _q_x(0.0))],
        "knee_r": [(0.0, _q_x(-10.0)), (0.15, _q_x(-24.0)), (0.3, _q_x(-5.0)), (0.62, _q_x(-10.0))],
        "hip_l": [(0.0, _q_x(0.0)), (0.3, _q_x(14.0)), (0.62, _q_x(0.0))],
        "shoulder_l": [(0.0, _q_z(-6.0)), (0.3, _q_z(-32.0)), (0.62, _q_z(-6.0))],
        "shoulder_r": [(0.0, _q_z(6.0)), (0.3, _q_z(28.0)), (0.62, _q_z(6.0))],
    }))

    clips.append(_clip("guard", 0.45, {
        "chest": [(0.0, _q_x(0.0)), (0.1, _q_x(10.0)), (0.45, _q_x(10.0))],
        "shoulder_l": [(0.0, _q_x(0.0)), (0.1, _q_x(-70.0)), (0.45, _q_x(-70.0))],
        "shoulder_r": [(0.0, _q_x(0.0)), (0.1, _q_x(-70.0)), (0.45, _q_x(-70.0))],
        "elbow_l": [(0.0, _q_x(-20.0)), (0.1, _q_x(-95.0)), (0.45, _q_x(-95.0))],
        "elbow_r": [(0.0, _q_x(-20.0)), (0.1, _q_x(-95.0)), (0.45, _q_x(-95.0))],
    }))

    clips.append(_clip("hit", 0.34, {
        "chest": [(0.0, _q_x(0.0)), (0.08, _q_x(22.0)), (0.34, _q_x(0.0))],
        "head": [(0.0, _q_x(0.0)), (0.08, _q_x(18.0)), (0.34, _q_x(0.0))],
        "shoulder_l": [(0.0, _q_z(0.0)), (0.08, _q_z(-28.0)), (0.34, _q_z(0.0))],
        "shoulder_r": [(0.0, _q_z(0.0)), (0.08, _q_z(28.0)), (0.34, _q_z(0.0))],
    }))
    return clips


def write_demo_assets(out_dir: str, manifest_path: str) -> Dict[str, object]:
    os.makedirs(out_dir, exist_ok=True)
    written: List[str] = []
    lines: List[str] = []

    def emit(relative_name: str, payload: bytes) -> str:
        path = os.path.join(out_dir, relative_name)
        with open(path, "wb") as handle:
            handle.write(payload)
        written.append(path)
        # Manifest paths are relative to the APK assets root.
        return f"storm/{relative_name}"

    for character in ("fighter", "rival"):
        asset = build_character(character)
        lines.append(f"mesh {character} {emit(character + '.smesh', write_mesh(asset))}")
    arena = build_arena()
    lines.append(f"mesh arena {emit('arena.smesh', write_mesh(arena))}")

    for clip in build_animations():
        lines.append(f"anim fighter {clip.name} {emit('fighter_' + clip.name + '.sanm', write_anim(clip))}")
    # rival reuses the fighter clips (identical skeleton hashes)
    lines.append("character rookie fighter 1.0")
    lines.append("character rival rival 1.0")
    lines.append("arena dojo arena")

    os.makedirs(os.path.dirname(manifest_path), exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        handle.write("# storm manifest v1\n")
        for line in sorted(set(lines)):
            handle.write(line + "\n")
    return {"files": written, "manifest": manifest_path}


if __name__ == "__main__":  # pragma: no cover
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "android/app/src/main"
    print(write_demo_assets(os.path.join(target, "assets", "storm"),
                            os.path.join(target, "assets", "storm", "manifest.txt")))
