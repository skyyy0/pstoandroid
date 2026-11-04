// Runtime package loading (.smesh / .sanm) and the asset manifest.
#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <vector>

#include "storm/math.h"

namespace storm {

struct TextureData {
    uint32_t width = 0;
    uint32_t height = 0;
    std::vector<uint8_t> rgba;
};

struct MaterialData {
    Vec4 baseColor{0.8f, 0.8f, 0.85f, 1.0f};
    Vec4 rimColor{0.35f, 0.45f, 0.7f, 1.0f};
    float specular = 0.25f;
    float shininess = 16.0f;
    float emissive = 0.0f;
    float alphaCutoff = 0.5f;
    int32_t albedo = -1;
};

struct BoneData {
    uint32_t nameHash = 0;
    int32_t parent = -1;
    Mat4 inverseBind;
};

struct SubMeshData {
    uint32_t indexOffset = 0;
    uint32_t indexCount = 0;
    int32_t material = 0;
};

struct VertexData {
    Vec3 position;
    Vec3 normal;
    Vec2 uv;
    uint8_t joints[4] = {0, 0, 0, 0};
    uint8_t weights[4] = {255, 0, 0, 0};
};

struct Mesh {
    std::string name;
    std::vector<VertexData> vertices;
    std::vector<uint32_t> indices;
    std::vector<SubMeshData> submeshes;
    std::vector<MaterialData> materials;
    std::vector<BoneData> bones;
    std::vector<TextureData> textures;
    Vec3 boundsMin;
    Vec3 boundsMax;
    Vec3 boundsCenter() const { return (boundsMin + boundsMax) * 0.5f; }
    float height() const { return boundsMax.y - boundsMin.y; }
};

struct Keyframe {
    float time = 0.0f;
    Quat rotation;
    Vec3 position;
};

struct BoneTrack {
    uint32_t nameHash = 0;
    std::vector<Keyframe> keys;
};

struct Clip {
    std::string name;
    float duration = 0.0f;
    bool loop = true;
    std::vector<BoneTrack> tracks;
};

// Loaders return false and fill `error` on malformed input; they never throw.
bool parseMesh(const uint8_t* data, size_t size, Mesh& out, std::string& error);
bool parseClip(const uint8_t* data, size_t size, Clip& out, std::string& error);

// Manifest grammar (paths are relative to the APK assets root):
//   mesh <name> <path>
//   anim <mesh> <clip> <path>
//   character <id> <mesh> <scale>
//   arena <id> <mesh>
struct Manifest {
    struct CharacterEntry {
        std::string mesh;
        float scale = 1.0f;
    };
    std::map<std::string, std::string> meshes;
    std::map<std::string, std::map<std::string, std::string>> animations;
    std::map<std::string, CharacterEntry> characters;
    std::map<std::string, std::string> arenas;
    std::vector<std::string> warnings;

    bool parse(const std::string& text);
};

}  // namespace storm
