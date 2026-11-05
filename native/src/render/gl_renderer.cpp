#include "render/gl_renderer.h"

#include <algorithm>
#include <cmath>
#include <cstring>

namespace storm {
namespace {

const char* kMainVertex = R"(#version 300 es
layout(location = 0) in vec3 aPosition;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec2 aUV;
layout(location = 3) in vec4 aJoints;
layout(location = 4) in vec4 aWeights;

uniform mat4 uViewProj;
uniform mat4 uModel;
uniform highp sampler2D uBones;
uniform int uSkinned;
uniform float uOutline;

out vec3 vNormal;
out vec2 vUV;
out vec3 vWorld;

mat4 fetchBone(int index) {
    int base = index * 4;
    vec4 c0 = texelFetch(uBones, ivec2(base + 0, 0), 0);
    vec4 c1 = texelFetch(uBones, ivec2(base + 1, 0), 0);
    vec4 c2 = texelFetch(uBones, ivec2(base + 2, 0), 0);
    vec4 c3 = texelFetch(uBones, ivec2(base + 3, 0), 0);
    return mat4(c0, c1, c2, c3);
}

void main() {
    vec4 localPosition = vec4(aPosition, 1.0);
    vec3 localNormal = aNormal;
    if (uSkinned == 1) {
        mat4 skin = fetchBone(int(aJoints.x)) * aWeights.x
                  + fetchBone(int(aJoints.y)) * aWeights.y
                  + fetchBone(int(aJoints.z)) * aWeights.z
                  + fetchBone(int(aJoints.w)) * aWeights.w;
        localPosition = skin * localPosition;
        localNormal = mat3(skin) * aNormal;
    }
    vec4 world = uModel * localPosition;
    vec3 normal = normalize(mat3(uModel) * localNormal);
    world.xyz += normal * uOutline;

    vWorld = world.xyz;
    vNormal = normal;
    vUV = aUV;
    gl_Position = uViewProj * world;
}
)";

const char* kMainFragment = R"(#version 300 es
precision mediump float;

in vec3 vNormal;
in vec2 vUV;
in vec3 vWorld;

uniform vec3 uLightDir;
uniform vec3 uCameraPos;
uniform vec4 uBaseColor;
uniform vec4 uRimColor;
uniform float uSpecular;
uniform float uShininess;
uniform int uHasTexture;
uniform sampler2D uAlbedo;
uniform float uFlash;
uniform int uOutlinePass;
uniform vec3 uOutlineColor;
uniform vec3 uFogColor;
uniform float uFogDensity;
uniform float uAmbient;

out vec4 fragColor;

void main() {
    if (uOutlinePass == 1) {
        fragColor = vec4(uOutlineColor, 1.0);
        return;
    }

    vec4 albedo = uBaseColor;
    if (uHasTexture == 1) {
        albedo *= texture(uAlbedo, vUV);
    }

    vec3 normal = normalize(vNormal);
    vec3 lightDir = normalize(-uLightDir);
    vec3 viewDir = normalize(uCameraPos - vWorld);

    // Three-band cel ramp with soft steps: keeps the Storm look at mobile ALU cost.
    float ndotl = dot(normal, lightDir);
    float lit = smoothstep(0.02, 0.12, ndotl);
    float mid = smoothstep(0.35, 0.52, ndotl);
    float shade = 0.55 + 0.28 * lit + 0.17 * mid;

    vec3 halfDir = normalize(lightDir + viewDir);
    float spec = pow(max(dot(normal, halfDir), 0.0), max(uShininess, 1.0));
    spec = smoothstep(0.18, 0.42, spec) * uSpecular;

    float rim = pow(1.0 - clamp(dot(normal, viewDir), 0.0, 1.0), 2.6);

    vec3 color = albedo.rgb * (uAmbient + shade * (1.0 - uAmbient));
    color += uRimColor.rgb * rim * uRimColor.a;
    color += vec3(spec);
    color = mix(color, vec3(1.0, 0.38, 0.30), uFlash * 0.55);

    float fog = 1.0 - exp(-uFogDensity * length(uCameraPos - vWorld));
    color = mix(color, uFogColor, clamp(fog, 0.0, 0.72));

    fragColor = vec4(color, albedo.a);
}
)";

const char* kBlobVertex = R"(#version 300 es
layout(location = 0) in vec3 aPosition;
uniform mat4 uViewProj;
uniform mat4 uModel;
out vec2 vLocal;
void main() {
    vLocal = aPosition.xz;
    gl_Position = uViewProj * uModel * vec4(aPosition, 1.0);
}
)";

const char* kBlobFragment = R"(#version 300 es
precision mediump float;
in vec2 vLocal;
out vec4 fragColor;
void main() {
    float distanceFromCenter = length(vLocal);
    float alpha = smoothstep(1.0, 0.15, distanceFromCenter) * 0.42;
    fragColor = vec4(0.02, 0.02, 0.04, alpha);
}
)";

GLuint compileShader(GLenum type, const char* source, std::string& error) {
    const GLuint shader = glCreateShader(type);
    if (shader == 0) {
        error = "glCreateShader failed";
        return 0;
    }
    glShaderSource(shader, 1, &source, nullptr);
    glCompileShader(shader);
    GLint status = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &status);
    if (status != GL_TRUE) {
        GLint logLength = 0;
        glGetShaderiv(shader, GL_INFO_LOG_LENGTH, &logLength);
        std::string log(static_cast<size_t>(logLength > 1 ? logLength : 1), '\0');
        glGetShaderInfoLog(shader, logLength, nullptr, log.data());
        error = std::string(type == GL_VERTEX_SHADER ? "vertex: " : "fragment: ") + log;
        glDeleteShader(shader);
        return 0;
    }
    return shader;
}

}  // namespace

bool GLRenderer::compileProgram(const char* vertexSource, const char* fragmentSource,
                                GLuint& program, std::string& error) {
    const GLuint vertex = compileShader(GL_VERTEX_SHADER, vertexSource, error);
    if (vertex == 0) return false;
    const GLuint fragment = compileShader(GL_FRAGMENT_SHADER, fragmentSource, error);
    if (fragment == 0) {
        glDeleteShader(vertex);
        return false;
    }
    program = glCreateProgram();
    glAttachShader(program, vertex);
    glAttachShader(program, fragment);
    glLinkProgram(program);
    glDeleteShader(vertex);
    glDeleteShader(fragment);

    GLint status = GL_FALSE;
    glGetProgramiv(program, GL_LINK_STATUS, &status);
    if (status != GL_TRUE) {
        GLint logLength = 0;
        glGetProgramiv(program, GL_INFO_LOG_LENGTH, &logLength);
        std::string log(static_cast<size_t>(logLength > 1 ? logLength : 1), '\0');
        glGetProgramInfoLog(program, logLength, nullptr, log.data());
        error = "link: " + log;
        glDeleteProgram(program);
        program = 0;
        return false;
    }
    return true;
}

bool GLRenderer::initialize(std::string& error) {
    if (!compileProgram(kMainVertex, kMainFragment, mainProgram_, error)) return false;
    if (!compileProgram(kBlobVertex, kBlobFragment, blobProgram_, error)) return false;

    mainUniforms_.viewProj = glGetUniformLocation(mainProgram_, "uViewProj");
    mainUniforms_.model = glGetUniformLocation(mainProgram_, "uModel");
    mainUniforms_.bones = glGetUniformLocation(mainProgram_, "uBones");
    mainUniforms_.skinned = glGetUniformLocation(mainProgram_, "uSkinned");
    mainUniforms_.outline = glGetUniformLocation(mainProgram_, "uOutline");
    mainUniforms_.cameraPos = glGetUniformLocation(mainProgram_, "uCameraPos");
    mainUniforms_.lightDir = glGetUniformLocation(mainProgram_, "uLightDir");
    mainUniforms_.baseColor = glGetUniformLocation(mainProgram_, "uBaseColor");
    mainUniforms_.rimColor = glGetUniformLocation(mainProgram_, "uRimColor");
    mainUniforms_.specular = glGetUniformLocation(mainProgram_, "uSpecular");
    mainUniforms_.shininess = glGetUniformLocation(mainProgram_, "uShininess");
    mainUniforms_.hasTexture = glGetUniformLocation(mainProgram_, "uHasTexture");
    mainUniforms_.albedo = glGetUniformLocation(mainProgram_, "uAlbedo");
    mainUniforms_.flash = glGetUniformLocation(mainProgram_, "uFlash");
    mainUniforms_.outlinePass = glGetUniformLocation(mainProgram_, "uOutlinePass");
    mainUniforms_.outlineColor = glGetUniformLocation(mainProgram_, "uOutlineColor");
    mainUniforms_.fogColor = glGetUniformLocation(mainProgram_, "uFogColor");
    mainUniforms_.fogDensity = glGetUniformLocation(mainProgram_, "uFogDensity");
    mainUniforms_.ambient = glGetUniformLocation(mainProgram_, "uAmbient");

    blobUniforms_.viewProj = glGetUniformLocation(blobProgram_, "uViewProj");
    blobUniforms_.model = glGetUniformLocation(blobProgram_, "uModel");

    boneScratch_.assign(static_cast<size_t>(kMaxBones) * 16, 0.0f);
    for (int bone = 0; bone < kMaxBones; ++bone) {
        float* target = boneScratch_.data() + bone * 16;
        target[0] = target[5] = target[10] = target[15] = 1.0f;
    }

    createBlobMesh();

    // Bone palette: 4 RGBA32F texels per bone, fetched with texelFetch in the
    // vertex shader. Texture unit 0 is the palette, unit 1 is albedo.
    glActiveTexture(GL_TEXTURE0);
    glGenTextures(1, &boneTexture_);
    glBindTexture(GL_TEXTURE_2D, boneTexture_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, kMaxBones * 4, 1, 0, GL_RGBA, GL_FLOAT, nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glUniform1i(mainUniforms_.bones, 0);
    glUniform1i(mainUniforms_.albedo, 1);

    glDisable(GL_BLEND);
    glEnable(GL_DEPTH_TEST);
    glDepthFunc(GL_LEQUAL);
    glEnable(GL_CULL_FACE);
    glCullFace(GL_BACK);
    glFrontFace(GL_CCW);
    return true;
}

void GLRenderer::shutdown() {
    for (auto& entry : meshes_) {
        GpuMesh& gpu = entry.second;
        if (gpu.vbo) glDeleteBuffers(1, &gpu.vbo);
        if (gpu.ibo) glDeleteBuffers(1, &gpu.ibo);
        if (gpu.vao) glDeleteVertexArrays(1, &gpu.vao);
        for (GLuint texture : gpu.textures) glDeleteTextures(1, &texture);
    }
    meshes_.clear();
    if (blobVbo_) glDeleteBuffers(1, &blobVbo_);
    if (blobVao_) glDeleteVertexArrays(1, &blobVao_);
    blobVbo_ = blobVao_ = 0;
    destroyTargets();
    if (boneTexture_) glDeleteTextures(1, &boneTexture_);
    boneTexture_ = 0;
    if (mainProgram_) glDeleteProgram(mainProgram_);
    if (blobProgram_) glDeleteProgram(blobProgram_);
    mainProgram_ = blobProgram_ = 0;
}

void GLRenderer::createBlobMesh() {
    constexpr int kSegments = 20;
    std::vector<float> vertices;
    vertices.reserve(static_cast<size_t>(kSegments + 2) * 3);
    vertices.push_back(0.0f);
    vertices.push_back(0.0f);
    vertices.push_back(0.0f);
    for (int segment = 0; segment <= kSegments; ++segment) {
        const float angle = static_cast<float>(segment) / kSegments * 6.2831853f;
        vertices.push_back(std::cos(angle));
        vertices.push_back(0.0f);
        vertices.push_back(std::sin(angle));
    }
    blobIndexCount_ = static_cast<GLuint>(kSegments) * 3;

    glGenVertexArrays(1, &blobVao_);
    glBindVertexArray(blobVao_);
    glGenBuffers(1, &blobVbo_);
    glBindBuffer(GL_ARRAY_BUFFER, blobVbo_);
    glBufferData(GL_ARRAY_BUFFER, static_cast<GLsizeiptr>(vertices.size() * sizeof(float)),
                 vertices.data(), GL_STATIC_DRAW);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, 3 * sizeof(float), nullptr);
    glBindVertexArray(0);
}

GLRenderer::GpuMesh& GLRenderer::meshFor(const Mesh& mesh) {
    auto found = meshes_.find(&mesh);
    if (found == meshes_.end()) {
        GpuMesh gpu;
        uploadMesh(mesh, gpu);
        found = meshes_.emplace(&mesh, std::move(gpu)).first;
    }
    return found->second;
}

void GLRenderer::uploadMesh(const Mesh& mesh, GpuMesh& gpu) {
    glGenVertexArrays(1, &gpu.vao);
    glBindVertexArray(gpu.vao);

    glGenBuffers(1, &gpu.vbo);
    glBindBuffer(GL_ARRAY_BUFFER, gpu.vbo);
    glBufferData(GL_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(mesh.vertices.size() * sizeof(VertexData)),
                 mesh.vertices.data(), GL_STATIC_DRAW);

    const GLsizei stride = sizeof(VertexData);
    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(VertexData, position)));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(VertexData, normal)));
    glEnableVertexAttribArray(2);
    glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(VertexData, uv)));
    glEnableVertexAttribArray(3);
    glVertexAttribPointer(3, 4, GL_UNSIGNED_BYTE, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(VertexData, joints)));
    glEnableVertexAttribArray(4);
    glVertexAttribPointer(4, 4, GL_UNSIGNED_BYTE, GL_FALSE, stride,
                          reinterpret_cast<void*>(offsetof(VertexData, weights)));

    glGenBuffers(1, &gpu.ibo);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, gpu.ibo);
    glBufferData(GL_ELEMENT_ARRAY_BUFFER,
                 static_cast<GLsizeiptr>(mesh.indices.size() * sizeof(uint32_t)),
                 mesh.indices.data(), GL_STATIC_DRAW);
    gpu.indexCount = static_cast<GLuint>(mesh.indices.size());

    gpu.drawList.reserve(mesh.submeshes.size());
    for (const SubMeshData& submesh : mesh.submeshes) {
        if (submesh.indexCount == 0) continue;
        gpu.drawList.push_back(&submesh);
    }
    std::sort(gpu.drawList.begin(), gpu.drawList.end(),
              [](const SubMeshData* a, const SubMeshData* b) {
                  if (a->material != b->material) return a->material < b->material;
                  return a->indexOffset < b->indexOffset;
              });

    gpu.textures.reserve(mesh.textures.size());
    for (const TextureData& texture : mesh.textures) {
        GLuint id = 0;
        glGenTextures(1, &id);
        glBindTexture(GL_TEXTURE_2D, id);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, static_cast<GLsizei>(texture.width),
                     static_cast<GLsizei>(texture.height), 0, GL_RGBA, GL_UNSIGNED_BYTE,
                     texture.rgba.data());
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
        glGenerateMipmap(GL_TEXTURE_2D);
        gpu.textures.push_back(id);
    }
    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
}

bool GLRenderer::createTargets(int width, int height) {
    destroyTargets();
    if (width <= 0 || height <= 0) return false;
    fboWidth_ = width;
    fboHeight_ = height;

    glGenTextures(1, &colorTexture_);
    glBindTexture(GL_TEXTURE_2D, colorTexture_);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE,
                 nullptr);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);

    glGenRenderbuffers(1, &depthBuffer_);
    glBindRenderbuffer(GL_RENDERBUFFER, depthBuffer_);
    glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height);

    glGenFramebuffers(1, &fbo_);
    glBindFramebuffer(GL_FRAMEBUFFER, fbo_);
    glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, colorTexture_, 0);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER, depthBuffer_);
    const GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    if (status != GL_FRAMEBUFFER_COMPLETE) {
        destroyTargets();
        return false;
    }
    return true;
}

void GLRenderer::destroyTargets() {
    if (fbo_) glDeleteFramebuffers(1, &fbo_);
    if (colorTexture_) glDeleteTextures(1, &colorTexture_);
    if (depthBuffer_) glDeleteRenderbuffers(1, &depthBuffer_);
    fbo_ = colorTexture_ = depthBuffer_ = 0;
    fboWidth_ = fboHeight_ = 0;
}

void GLRenderer::resize(int width, int height) {
    surfaceWidth_ = width > 0 ? width : 1;
    surfaceHeight_ = height > 0 ? height : 1;
}

void GLRenderer::uploadBones(const Pose& pose) {
    const size_t boneCount = std::min(pose.skin.size(), static_cast<size_t>(kMaxBones));
    if (boneCount == 0) return;
    // Only the bones the pose actually has are copied and uploaded; unused
    // palette slots keep their identity matrices from initialize().
    for (size_t bone = 0; bone < boneCount; ++bone) {
        std::memcpy(boneScratch_.data() + bone * 16, pose.skin[bone].m, 16 * sizeof(float));
    }
    glActiveTexture(GL_TEXTURE0);
    glBindTexture(GL_TEXTURE_2D, boneTexture_);
    glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, static_cast<GLsizei>(boneCount * 4), 1, GL_RGBA,
                    GL_FLOAT, boneScratch_.data());
}

void GLRenderer::drawBlob(const DrawItem& item, const FrameView& frame) {
    if (item.pose == nullptr) return;
    glUseProgram(blobProgram_);
    glUniformMatrix4fv(blobUniforms_.viewProj, 1, GL_FALSE, frame.viewProjection.m);
    Mat4 model = Mat4::translation(item.model.translationPart() + Vec3{0.0f, 0.02f, 0.0f}) *
                 Mat4::scale(0.92f);
    glUniformMatrix4fv(blobUniforms_.model, 1, GL_FALSE, model.m);
    glBindVertexArray(blobVao_);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 22);
    drawCalls_ += 1;
}

void GLRenderer::drawItem(const DrawItem& item, bool outlinePass) {
    if (item.mesh == nullptr) return;
    GpuMesh& gpu = meshFor(*item.mesh);
    if (gpu.indexCount == 0) return;

    const bool skinned = item.pose != nullptr && !item.pose->skin.empty();
    if (skinned && uploadedPose_ != item.pose) {
        uploadBones(*item.pose);
        uploadedPose_ = item.pose;
    }

    glUniformMatrix4fv(mainUniforms_.model, 1, GL_FALSE, item.model.m);
    glUniform1i(mainUniforms_.skinned, skinned ? 1 : 0);
    glUniform1i(mainUniforms_.outlinePass, outlinePass ? 1 : 0);
    glUniform1f(mainUniforms_.outline, outlinePass ? 0.018f : 0.0f);
    glUniform1f(mainUniforms_.flash, item.flash);

    glBindVertexArray(gpu.vao);
    for (const SubMeshData* entry : gpu.drawList) {
        const SubMeshData& submesh = *entry;
        if (outlinePass) {
            glUniform4f(mainUniforms_.baseColor, 0.03f, 0.03f, 0.05f, 1.0f);
            glUniform1i(mainUniforms_.hasTexture, 0);
        } else if (submesh.material >= 0 &&
                   submesh.material < static_cast<int32_t>(item.mesh->materials.size())) {
            const MaterialData& material = item.mesh->materials[submesh.material];
            glUniform4f(mainUniforms_.baseColor, material.baseColor.x, material.baseColor.y,
                        material.baseColor.z, material.baseColor.w);
            glUniform4f(mainUniforms_.rimColor, material.rimColor.x, material.rimColor.y,
                        material.rimColor.z,
                        qualityTier_ >= 3 ? material.rimColor.w : 0.0f);
            glUniform1f(mainUniforms_.specular,
                        qualityTier_ >= 3 ? material.specular : 0.0f);
            glUniform1f(mainUniforms_.shininess, material.shininess);
            if (material.albedo >= 0 &&
                material.albedo < static_cast<int32_t>(gpu.textures.size())) {
                glActiveTexture(GL_TEXTURE1);
                glBindTexture(GL_TEXTURE_2D, gpu.textures[static_cast<size_t>(material.albedo)]);
                glUniform1i(mainUniforms_.hasTexture, 1);
            } else {
                glUniform1i(mainUniforms_.hasTexture, 0);
            }
        } else {
            glUniform4f(mainUniforms_.baseColor, 0.7f, 0.7f, 0.7f, 1.0f);
            glUniform1i(mainUniforms_.hasTexture, 0);
        }

        glDrawElements(GL_TRIANGLES, static_cast<GLsizei>(submesh.indexCount), GL_UNSIGNED_INT,
                       reinterpret_cast<const void*>(
                           static_cast<uintptr_t>(submesh.indexOffset) * sizeof(uint32_t)));
        drawCalls_ += 1;
    }
    glBindVertexArray(0);
}

void GLRenderer::render(const FrameView& frame) {
    if (mainProgram_ == 0 || surfaceWidth_ <= 0 || surfaceHeight_ <= 0) return;

    const float scale = std::clamp(frame.resolutionScale, 0.25f, 1.0f);
    // The offscreen target is allocated once per surface size. Changing the
    // internal resolution only moves the viewport, so the governor can retune
    // every few frames without reallocating textures (a driver stall on weak
    // GPUs, and the main source of visible hitching during fights).
    if (fbo_ == 0 || fboWidth_ != surfaceWidth_ || fboHeight_ != surfaceHeight_) {
        if (!createTargets(surfaceWidth_, surfaceHeight_)) {
            // Fall back to the default framebuffer rather than showing nothing.
            destroyTargets();
        }
    }
    renderWidth_ = std::max(1, static_cast<int>(surfaceWidth_ * scale));
    renderHeight_ = std::max(1, static_cast<int>(surfaceHeight_ * scale));
    qualityTier_ = frame.qualityTier;
    uploadedPose_ = nullptr;

    drawCalls_ = 0;
    const bool offscreen = fbo_ != 0;
    glBindFramebuffer(GL_FRAMEBUFFER, offscreen ? fbo_ : 0);
    glViewport(0, 0, offscreen ? renderWidth_ : surfaceWidth_,
               offscreen ? renderHeight_ : surfaceHeight_);

    // Warm dusk sky matching the stage lighting.
    glClearColor(0.09f, 0.10f, 0.16f, 1.0f);
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);

    glUseProgram(mainProgram_);
    glUniformMatrix4fv(mainUniforms_.viewProj, 1, GL_FALSE, frame.viewProjection.m);
    glUniform3f(mainUniforms_.cameraPos, frame.cameraPosition.x, frame.cameraPosition.y,
                frame.cameraPosition.z);
    glUniform3f(mainUniforms_.lightDir, frame.lightDirection.x, frame.lightDirection.y,
                frame.lightDirection.z);
    glUniform3f(mainUniforms_.outlineColor, 0.02f, 0.02f, 0.04f);
    glUniform3f(mainUniforms_.fogColor, 0.09f, 0.10f, 0.16f);
    glUniform1f(mainUniforms_.fogDensity, 0.0075f);
    glUniform1f(mainUniforms_.ambient, 0.42f);
    glUniform1i(mainUniforms_.bones, 0);
    glUniform1i(mainUniforms_.albedo, 1);

    // Contact shadows first (blended, no depth writes).
    if (frame.qualityTier >= 2) {
        glEnable(GL_BLEND);
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        glDepthMask(GL_FALSE);
        for (const DrawItem& item : frame.items) {
            if (item.castShadow) drawBlob(item, frame);
        }
        glDepthMask(GL_TRUE);
        glDisable(GL_BLEND);
    }

    glUseProgram(mainProgram_);
    glUniformMatrix4fv(mainUniforms_.viewProj, 1, GL_FALSE, frame.viewProjection.m);

    // Cel outline pass: expand along the normal with front faces culled.
    if (frame.qualityTier >= 1) {
        glCullFace(GL_FRONT);
        for (const DrawItem& item : frame.items) drawItem(item, true);
        glCullFace(GL_BACK);
    }
    for (const DrawItem& item : frame.items) drawItem(item, false);

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    if (offscreen) {
        glBindFramebuffer(GL_READ_FRAMEBUFFER, fbo_);
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
        glBlitFramebuffer(0, 0, renderWidth_, renderHeight_, 0, 0, surfaceWidth_, surfaceHeight_,
                          GL_COLOR_BUFFER_BIT, GL_LINEAR);
        glBindFramebuffer(GL_FRAMEBUFFER, 0);
    }
}

}  // namespace storm
