// Skinning pose evaluation with clip cross-fading.
#pragma once

#include <map>
#include <string>
#include <vector>

#include "storm/asset.h"
#include "storm/math.h"

namespace storm {

struct Pose {
    std::vector<Mat4> local;
    std::vector<Mat4> world;
    std::vector<Mat4> skin;

    void resize(size_t boneCount) {
        local.resize(boneCount);
        world.resize(boneCount);
        skin.resize(boneCount);
    }
    size_t boneCount() const { return local.size(); }
};

// Inverse of an affine (rotation + translation + uniform scale) matrix.
Mat4 inverseAffine(const Mat4& matrix);

class Animator {
public:
    void configure(const Mesh& mesh, const std::map<std::string, Clip>& clips);

    // Starts `name` with an optional cross-fade. Re-playing the active clip is a
    // no-op unless `restart` is set, which keeps looping states stable.
    bool play(const std::string& name, float blendSeconds = 0.12f, bool restart = false);
    void stop();

    void update(float dt);

    const std::string& currentClip() const { return currentName_; }
    bool finished() const { return finished_; }
    float normalizedTime() const;
    void evaluate(Pose& out) const;

    const Mesh* mesh() const { return mesh_; }
    bool ready() const { return mesh_ != nullptr && !restLocal_.empty(); }

private:
    void sampleLocal(const Clip& clip, float time, std::vector<Mat4>& out, bool& foundAny) const;
    void computeWorld(const std::vector<Mat4>& local, Pose& pose) const;

    const Mesh* mesh_ = nullptr;
    std::map<std::string, const Clip*> clips_;
    std::vector<Mat4> restLocal_;
    std::vector<int32_t> parents_;

    const Clip* current_ = nullptr;
    const Clip* previous_ = nullptr;
    std::string currentName_;
    float currentTime_ = 0.0f;
    float previousTime_ = 0.0f;
    float blendDuration_ = 0.12f;
    float blendElapsed_ = 0.12f;
    bool finished_ = false;
};

}  // namespace storm
