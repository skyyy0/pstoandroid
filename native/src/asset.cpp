#include "storm/asset.h"

#include <algorithm>
#include <cstring>
#include <sstream>

namespace storm {
namespace {

constexpr char kMeshMagic[4] = {'S', 'M', 'S', 'H'};
constexpr char kClipMagic[4] = {'S', 'A', 'N', 'M'};
constexpr uint32_t kPackageVersion = 1;

class ByteReader {
public:
    ByteReader(const uint8_t* data, size_t size) : data_(data), size_(size) {}

    bool ok() const { return ok_; }
    size_t position() const { return position_; }

    bool skip(size_t count) {
        if (!ok_ || position_ + count > size_) {
            ok_ = false;
            return false;
        }
        position_ += count;
        return true;
    }

    bool magic(const char expected[4]) {
        if (!ok_ || position_ + 4 > size_) {
            ok_ = false;
            return false;
        }
        const bool matches = std::memcmp(data_ + position_, expected, 4) == 0;
        position_ += 4;
        if (!matches) ok_ = false;
        return matches;
    }

    uint32_t u32() {
        if (!ok_ || position_ + 4 > size_) {
            ok_ = false;
            return 0;
        }
        uint32_t value = 0;
        std::memcpy(&value, data_ + position_, 4);
        position_ += 4;
        return value;
    }

    int32_t i32() { return static_cast<int32_t>(u32()); }

    float f32() {
        if (!ok_ || position_ + 4 > size_) {
            ok_ = false;
            return 0.0f;
        }
        float value = 0.0f;
        std::memcpy(&value, data_ + position_, 4);
        position_ += 4;
        return value;
    }

    Vec2 vec2() {
        const float x = f32();
        const float y = f32();
        return {x, y};
    }

    Vec3 vec3() {
        const float x = f32();
        const float y = f32();
        const float z = f32();
        return {x, y, z};
    }

    Vec4 vec4() {
        const float x = f32();
        const float y = f32();
        const float z = f32();
        const float w = f32();
        return {x, y, z, w};
    }

    Mat4 mat4() {
        Mat4 out;
        for (int i = 0; i < 16; ++i) out.m[i] = f32();
        return out;
    }

    bool bytes(uint8_t* destination, size_t count) {
        if (!ok_ || position_ + count > size_) {
            ok_ = false;
            return false;
        }
        std::memcpy(destination, data_ + position_, count);
        position_ += count;
        return true;
    }

private:
    const uint8_t* data_;
    size_t size_;
    size_t position_ = 0;
    bool ok_ = true;
};

std::string fixedString(const uint8_t* data, size_t count) {
    size_t length = 0;
    while (length < count && data[length] != 0) ++length;
    return std::string(reinterpret_cast<const char*>(data), length);
}

}  // namespace

bool parseMesh(const uint8_t* data, size_t size, Mesh& out, std::string& error) {
    out = Mesh{};
    if (data == nullptr || size < 32) {
        error = "smesh: buffer too small";
        return false;
    }
    ByteReader reader(data, size);
    if (!reader.magic(kMeshMagic)) {
        error = "smesh: bad magic";
        return false;
    }
    const uint32_t version = reader.u32();
    if (version != kPackageVersion) {
        error = "smesh: unsupported version " + std::to_string(version);
        return false;
    }
    const uint32_t vertexCount = reader.u32();
    const uint32_t indexCount = reader.u32();
    const uint32_t submeshCount = reader.u32();
    const uint32_t materialCount = reader.u32();
    const uint32_t boneCount = reader.u32();
    const uint32_t textureCount = reader.u32();

    // Guard against absurd counts from corrupt files before allocating.
    constexpr uint32_t kMaxVertices = 8u * 1024u * 1024u;
    if (vertexCount > kMaxVertices || indexCount > kMaxVertices * 3u ||
        submeshCount > 4096u || materialCount > 4096u || boneCount > 512u ||
        textureCount > 512u) {
        error = "smesh: implausible section counts";
        return false;
    }

    out.textures.resize(textureCount);
    for (TextureData& texture : out.textures) {
        texture.width = reader.u32();
        texture.height = reader.u32();
        const uint64_t payload = static_cast<uint64_t>(texture.width) * texture.height * 4u;
        if (payload > size || payload > (64ull << 20)) {
            error = "smesh: texture payload too large";
            return false;
        }
        texture.rgba.resize(static_cast<size_t>(payload));
        if (!reader.bytes(texture.rgba.data(), texture.rgba.size())) {
            error = "smesh: truncated texture data";
            return false;
        }
    }

    out.materials.resize(materialCount);
    for (MaterialData& material : out.materials) {
        material.baseColor = reader.vec4();
        material.rimColor = reader.vec4();
        material.specular = reader.f32();
        material.shininess = reader.f32();
        material.emissive = reader.f32();
        material.alphaCutoff = reader.f32();
        material.albedo = reader.i32();
    }

    out.bones.resize(boneCount);
    for (BoneData& bone : out.bones) {
        bone.nameHash = reader.u32();
        bone.parent = reader.i32();
        bone.inverseBind = reader.mat4();
    }

    out.submeshes.resize(submeshCount);
    for (SubMeshData& submesh : out.submeshes) {
        submesh.indexOffset = reader.u32();
        submesh.indexCount = reader.u32();
        submesh.material = reader.i32();
    }

    out.vertices.resize(vertexCount);
    for (VertexData& vertex : out.vertices) {
        vertex.position = reader.vec3();
        vertex.normal = reader.vec3();
        vertex.uv = reader.vec2();
        uint8_t joints[4] = {0, 0, 0, 0};
        uint8_t weights[4] = {0, 0, 0, 0};
        if (!reader.bytes(joints, 4) || !reader.bytes(weights, 4)) {
            error = "smesh: truncated vertex data";
            return false;
        }
        std::memcpy(vertex.joints, joints, 4);
        std::memcpy(vertex.weights, weights, 4);
    }

    out.indices.resize(indexCount);
    for (uint32_t& index : out.indices) index = reader.u32();

    if (!reader.ok()) {
        error = "smesh: truncated file";
        return false;
    }
    if (indexCount % 3 != 0) {
        error = "smesh: index count is not a multiple of 3";
        return false;
    }
    if (out.vertices.empty()) {
        error = "smesh: mesh has no vertices";
        return false;
    }

    const uint32_t jointLimit = std::max<uint32_t>(1, boneCount);
    for (const VertexData& vertex : out.vertices) {
        for (int slot = 0; slot < 4; ++slot) {
            if (vertex.joints[slot] >= jointLimit) {
                error = "smesh: joint index out of range";
                return false;
            }
        }
    }
    for (uint32_t index : out.indices) {
        if (index >= vertexCount) {
            error = "smesh: index out of range";
            return false;
        }
    }
    for (const SubMeshData& submesh : out.submeshes) {
        if (submesh.indexOffset + submesh.indexCount > indexCount) {
            error = "smesh: submesh range out of range";
            return false;
        }
        if (submesh.material >= static_cast<int32_t>(materialCount)) {
            error = "smesh: submesh material out of range";
            return false;
        }
    }
    for (size_t boneIndex = 0; boneIndex < out.bones.size(); ++boneIndex) {
        const int32_t parent = out.bones[boneIndex].parent;
        if (parent >= static_cast<int32_t>(boneIndex) || parent < -1) {
            error = "smesh: bones must be ordered parent-before-child";
            return false;
        }
    }
    for (const MaterialData& material : out.materials) {
        if (material.albedo >= static_cast<int32_t>(textureCount)) {
            error = "smesh: material albedo out of range";
            return false;
        }
    }

    out.boundsMin = out.vertices.front().position;
    out.boundsMax = out.vertices.front().position;
    for (const VertexData& vertex : out.vertices) {
        out.boundsMin.x = std::min(out.boundsMin.x, vertex.position.x);
        out.boundsMin.y = std::min(out.boundsMin.y, vertex.position.y);
        out.boundsMin.z = std::min(out.boundsMin.z, vertex.position.z);
        out.boundsMax.x = std::max(out.boundsMax.x, vertex.position.x);
        out.boundsMax.y = std::max(out.boundsMax.y, vertex.position.y);
        out.boundsMax.z = std::max(out.boundsMax.z, vertex.position.z);
    }
    return true;
}

bool parseClip(const uint8_t* data, size_t size, Clip& out, std::string& error) {
    out = Clip{};
    if (data == nullptr || size < 52) {
        error = "sanm: buffer too small";
        return false;
    }
    ByteReader reader(data, size);
    if (!reader.magic(kClipMagic)) {
        error = "sanm: bad magic";
        return false;
    }
    const uint32_t version = reader.u32();
    if (version != kPackageVersion) {
        error = "sanm: unsupported version " + std::to_string(version);
        return false;
    }
    uint8_t name[32];
    if (!reader.bytes(name, sizeof(name))) {
        error = "sanm: truncated name";
        return false;
    }
    out.name = fixedString(name, sizeof(name));
    out.duration = reader.f32();
    out.loop = reader.u32() != 0;
    const uint32_t trackCount = reader.u32();
    if (trackCount > 512) {
        error = "sanm: implausible track count";
        return false;
    }
    out.tracks.resize(trackCount);
    for (BoneTrack& track : out.tracks) {
        track.nameHash = reader.u32();
        const uint32_t keyCount = reader.u32();
        if (keyCount > 65536) {
            error = "sanm: implausible key count";
            return false;
        }
        track.keys.resize(keyCount);
        for (Keyframe& key : track.keys) {
            key.time = reader.f32();
            key.rotation = {reader.f32(), reader.f32(), reader.f32(), reader.f32()};
            key.position = reader.vec3();
        }
    }
    if (!reader.ok()) {
        error = "sanm: truncated file";
        return false;
    }
    if (out.duration <= 0.0f) {
        out.duration = 0.001f;
    }
    return true;
}

bool Manifest::parse(const std::string& text) {
    meshes.clear();
    animations.clear();
    characters.clear();
    arenas.clear();
    warnings.clear();

    std::istringstream stream(text);
    std::string line;
    int lineNumber = 0;
    while (std::getline(stream, line)) {
        ++lineNumber;
        const size_t comment = line.find('#');
        if (comment != std::string::npos) line = line.substr(0, comment);
        std::istringstream tokens(line);
        std::string keyword;
        if (!(tokens >> keyword)) continue;

        if (keyword == "mesh") {
            std::string name, path;
            if (tokens >> name >> path) {
                meshes[name] = path;
            } else {
                warnings.push_back("line " + std::to_string(lineNumber) + ": bad mesh entry");
            }
        } else if (keyword == "anim") {
            std::string mesh, clip, path;
            if (tokens >> mesh >> clip >> path) {
                animations[mesh][clip] = path;
            } else {
                warnings.push_back("line " + std::to_string(lineNumber) + ": bad anim entry");
            }
        } else if (keyword == "character") {
            std::string id, mesh;
            float scale = 1.0f;
            if (tokens >> id >> mesh) {
                if (!(tokens >> scale)) scale = 1.0f;
                characters[id] = CharacterEntry{mesh, scale};
            } else {
                warnings.push_back("line " + std::to_string(lineNumber) + ": bad character entry");
            }
        } else if (keyword == "arena") {
            std::string id, mesh;
            if (tokens >> id >> mesh) {
                arenas[id] = mesh;
            } else {
                warnings.push_back("line " + std::to_string(lineNumber) + ": bad arena entry");
            }
        } else {
            warnings.push_back("line " + std::to_string(lineNumber) + ": unknown keyword '" + keyword + "'");
        }
    }
    return !meshes.empty() || !characters.empty();
}

}  // namespace storm
