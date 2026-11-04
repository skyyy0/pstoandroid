// GLES 3.0 renderer for the toon-shaded arena slice.
//
// Deliberate choices for low-end Android:
//  * one uber shader (toon + outline) instead of many programs -> fewer state
//    switches and cheaper shader compilation at startup;
//  * dynamic-resolution offscreen target so the governor can trade pixels for
//    frame time without touching the UI layer;
//  * no shadow maps yet (blob contact shadows); the roadmap in docs/ lists the
//    cascaded shadow step once the base frame time is measured on real devices.
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <unordered_map>
#include <vector>

#include <GLES3/gl3.h>

#include "storm/scene.h"

namespace storm {

// Retail rigs reach ~110 bones. They are uploaded through a std140 uniform
// block (8 KiB at 128 bones) because a plain mat4[] uniform would exceed the
// 256 vec4 vertex-uniform minimum on entry-level GLES 3 devices.
constexpr int kMaxBones = 128;

class GLRenderer {
public:
    bool initialize(std::string& error);
    void shutdown();
    void resize(int width, int height);
    void render(const FrameView& frame);

    int drawCalls() const { return drawCalls_; }
    int renderWidth() const { return fboWidth_; }
    int renderHeight() const { return fboHeight_; }
    bool usingOffscreenTarget() const { return fbo_ != 0; }

private:
    struct GpuMesh {
        GLuint vao = 0;
        GLuint vbo = 0;
        GLuint ibo = 0;
        GLuint indexCount = 0;
        std::vector<GLuint> textures;
    };

    struct MainUniforms {
        GLint viewProj = -1;
        GLint model = -1;
        GLint skinned = -1;
        GLint outline = -1;
        GLint cameraPos = -1;
        GLint lightDir = -1;
        GLint baseColor = -1;
        GLint rimColor = -1;
        GLint specular = -1;
        GLint shininess = -1;
        GLint hasTexture = -1;
        GLint albedo = -1;
        GLint flash = -1;
        GLint outlinePass = -1;
        GLint outlineColor = -1;
        GLint fogColor = -1;
        GLint fogDensity = -1;
        GLint ambient = -1;
    };

    struct BlobUniforms {
        GLint viewProj = -1;
        GLint model = -1;
    };

    bool compileProgram(const char* vertexSource, const char* fragmentSource, GLuint& program,
                        std::string& error);
    bool createTargets(int width, int height);
    void destroyTargets();
    void createBlobMesh();
    GpuMesh& meshFor(const Mesh& mesh);
    void uploadMesh(const Mesh& mesh, GpuMesh& gpu);
    void drawItem(const DrawItem& item, const FrameView& frame, bool outlinePass);
    void drawBlob(const DrawItem& item, const FrameView& frame);
    void uploadBones(const Pose& pose);

    GLuint mainProgram_ = 0;
    GLuint blobProgram_ = 0;
    GLuint boneUbo_ = 0;
    MainUniforms mainUniforms_;
    BlobUniforms blobUniforms_;

    GLuint fbo_ = 0;
    GLuint colorTexture_ = 0;
    GLuint depthBuffer_ = 0;
    int fboWidth_ = 0;
    int fboHeight_ = 0;
    int surfaceWidth_ = 0;
    int surfaceHeight_ = 0;

    GLuint blobVao_ = 0;
    GLuint blobVbo_ = 0;
    GLuint blobIndexCount_ = 0;

    std::unordered_map<const Mesh*, GpuMesh> meshes_;
    std::vector<float> boneScratch_;
    int drawCalls_ = 0;
};

}  // namespace storm
