"""Runtime asset packages consumed by the native engine (``.smesh`` / ``.sanm``).

These formats are deliberately flat, little-endian and pointer-free so Android
can stream them with a single read and upload the vertex/index blocks straight
into GLES buffers.  Both the Python packer and the C++ loader implement this
spec; ``docs/ASSET_PIPELINE.md`` documents it for future tooling.

SMSH (mesh)
    char   magic[4]      "SMSH"
    u32    version       1
    u32    vertex_count, index_count, submesh_count, material_count,
           bone_count, texture_count
    texture[texture_count]
        u32 width, u32 height, u8 rgba[width * height * 4]
    material[material_count]
        f32 base_color[4], f32 rim_color[4], f32 params[4],
        i32 albedo_texture (-1 = none)
    bone[bone_count]
        u32 name_hash, i32 parent (-1 = root), f32 inverse_bind[16] (col-major)
    submesh[submesh_count]
        u32 index_offset, u32 index_count, i32 material
    vertex[vertex_count]
        f32 position[3], f32 normal[3], f32 uv[2],
        u8 joints[4], u8 weights[4]            (32 + 8 = 40 bytes)
    u32 index[index_count]

SANM (animation clip, one clip per file)
    char   magic[4]      "SANM"
    u32    version       1
    char   name[32]
    f32    duration_seconds
    u32    loop
    u32    bone_count
    bone[bone_count]
        u32 name_hash, u32 key_count
        key[key_count]: f32 time, f32 rot[4] (x,y,z,w), f32 position[3]
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Sequence, Tuple

from .binary import BinaryError, Reader, Writer

SMESH_MAGIC = b"SMSH"
SANM_MAGIC = b"SANM"
PACKAGE_VERSION = 1
VERTEX_STRIDE = 40


@dataclass
class Texture:
    width: int
    height: int
    rgba: bytes

    def validate(self) -> None:
        if len(self.rgba) != self.width * self.height * 4:
            raise ValueError("texture payload does not match width/height")


@dataclass
class Material:
    base_color: Tuple[float, float, float, float] = (0.8, 0.8, 0.85, 1.0)
    rim_color: Tuple[float, float, float, float] = (0.35, 0.45, 0.7, 1.0)
    params: Tuple[float, float, float, float] = (0.25, 16.0, 0.0, 0.5)
    albedo: int = -1


@dataclass
class Bone:
    name_hash: int
    parent: int
    inverse_bind: Sequence[float]  # 16 floats, column major


@dataclass
class Vertex:
    position: Tuple[float, float, float]
    normal: Tuple[float, float, float]
    uv: Tuple[float, float] = (0.0, 0.0)
    joints: Tuple[int, int, int, int] = (0, 0, 0, 0)
    weights: Tuple[int, int, int, int] = (255, 0, 0, 0)


@dataclass
class SubMesh:
    index_offset: int
    index_count: int
    material: int


@dataclass
class MeshAsset:
    name: str = ""
    vertices: List[Vertex] = field(default_factory=list)
    indices: List[int] = field(default_factory=list)
    submeshes: List[SubMesh] = field(default_factory=list)
    materials: List[Material] = field(default_factory=list)
    bones: List[Bone] = field(default_factory=list)
    textures: List[Texture] = field(default_factory=list)


@dataclass
class BoneKey:
    time: float
    rotation: Tuple[float, float, float, float]
    position: Tuple[float, float, float]


@dataclass
class BoneTrack:
    name_hash: int
    keys: List[BoneKey] = field(default_factory=list)


@dataclass
class AnimClip:
    name: str = ""
    duration: float = 0.0
    loop: bool = True
    tracks: List[BoneTrack] = field(default_factory=list)


# --------------------------------------------------------------------------
# writing
# --------------------------------------------------------------------------
def write_mesh(asset: MeshAsset) -> bytes:
    if len(asset.vertices) > 0xFFFFFFFF:
        raise ValueError("too many vertices")
    for texture in asset.textures:
        texture.validate()
    writer = Writer("<")
    writer.raw(SMESH_MAGIC).u32(PACKAGE_VERSION)
    writer.u32(len(asset.vertices)).u32(len(asset.indices))
    writer.u32(len(asset.submeshes)).u32(len(asset.materials))
    writer.u32(len(asset.bones)).u32(len(asset.textures))

    for texture in asset.textures:
        writer.u32(texture.width).u32(texture.height).raw(texture.rgba)

    for material in asset.materials:
        writer.f32s(material.base_color).f32s(material.rim_color)
        writer.f32s(material.params).i32(material.albedo)

    for bone in asset.bones:
        if len(bone.inverse_bind) != 16:
            raise ValueError(f"bone {bone.name_hash:#x}: inverse_bind must have 16 floats")
        writer.u32(bone.name_hash).i32(bone.parent).f32s(bone.inverse_bind)

    for submesh in asset.submeshes:
        writer.u32(submesh.index_offset).u32(submesh.index_count)
        writer.i32(submesh.material)

    for vertex in asset.vertices:
        writer.f32s(vertex.position).f32s(vertex.normal).f32s(vertex.uv)
        writer.raw(bytes(vertex.joints)).raw(bytes(vertex.weights))

    for index in asset.indices:
        writer.u32(index)
    return writer.bytes()


def write_anim(clip: AnimClip) -> bytes:
    writer = Writer("<")
    writer.raw(SANM_MAGIC).u32(PACKAGE_VERSION)
    writer.cstr(clip.name, 32)
    writer.f32(clip.duration).u32(1 if clip.loop else 0).u32(len(clip.tracks))
    for track in clip.tracks:
        writer.u32(track.name_hash).u32(len(track.keys))
        for key in track.keys:
            writer.f32(key.time).f32s(key.rotation).f32s(key.position)
    return writer.bytes()


# --------------------------------------------------------------------------
# reading (used by tools/tests; the C++ engine has its own loader)
# --------------------------------------------------------------------------
def read_mesh(data: bytes) -> MeshAsset:
    reader = Reader(data, 0, "<")
    reader.magic(SMESH_MAGIC)
    version = reader.u32()
    if version != PACKAGE_VERSION:
        raise BinaryError(f"unsupported smesh version {version}")
    counts = [reader.u32() for _ in range(6)]
    vertex_count, index_count, submesh_count, material_count, bone_count, texture_count = counts

    asset = MeshAsset()
    for _ in range(texture_count):
        width, height = reader.u32(), reader.u32()
        asset.textures.append(Texture(width, height, reader.bytes(width * height * 4)))
    for _ in range(material_count):
        base = tuple(reader.f32s(4))
        rim = tuple(reader.f32s(4))
        params = tuple(reader.f32s(4))
        asset.materials.append(Material(base, rim, params, reader.i32()))
    for _ in range(bone_count):
        asset.bones.append(Bone(reader.u32(), reader.i32(), tuple(reader.f32s(16))))
    for _ in range(submesh_count):
        asset.submeshes.append(SubMesh(reader.u32(), reader.u32(), reader.i32()))

    for _ in range(vertex_count):
        position = tuple(reader.f32s(3))
        normal = tuple(reader.f32s(3))
        uv = tuple(reader.f32s(2))
        joints = tuple(struct.unpack("<4B", reader.bytes(4)))
        weights = tuple(struct.unpack("<4B", reader.bytes(4)))
        asset.vertices.append(Vertex(position, normal, uv, joints, weights))

    asset.indices = list(struct.unpack_from(f"<{index_count}I", reader.data, reader.pos))
    reader.skip(index_count * 4)
    if reader.remaining:
        raise BinaryError(f"{reader.remaining} trailing bytes in smesh")
    return asset


def read_anim(data: bytes) -> AnimClip:
    reader = Reader(data, 0, "<")
    reader.magic(SANM_MAGIC)
    version = reader.u32()
    if version != PACKAGE_VERSION:
        raise BinaryError(f"unsupported sanm version {version}")
    clip = AnimClip()
    clip.name = reader.fixed_str(32)
    clip.duration = reader.f32()
    clip.loop = reader.u32() != 0
    bone_count = reader.u32()
    for _ in range(bone_count):
        name_hash = reader.u32()
        key_count = reader.u32()
        track = BoneTrack(name_hash)
        for _ in range(key_count):
            key = BoneKey(reader.f32(), tuple(reader.f32s(4)), tuple(reader.f32s(3)))
            track.keys.append(key)
        clip.tracks.append(track)
    return clip


def describe_mesh(asset: MeshAsset) -> str:
    triangles = len(asset.indices) // 3
    bones = ", ".join(f"{b.name_hash:#010x}" for b in asset.bones[:6])
    return (
        f"vertices={len(asset.vertices)} triangles={triangles} "
        f"submeshes={len(asset.submeshes)} materials={len(asset.materials)} "
        f"bones={len(asset.bones)} textures={len(asset.textures)}"
        + (f" [{bones}{' ...' if len(asset.bones) > 6 else ''}]" if bones else "")
    )
