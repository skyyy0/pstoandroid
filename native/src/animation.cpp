#include "storm/animation.h"

#include <algorithm>
#include <cmath>

namespace storm {
namespace {

const Mat4 kIdentity = Mat4::identity();

void sampleTrack(const BoneTrack& track, float time, Mat4& out) {
    if (track.keys.empty()) return;
    const auto& keys = track.keys;
    if (time <= keys.front().time) {
        out = makeTrs(keys.front().position, keys.front().rotation);
        return;
    }
    if (time >= keys.back().time) {
        out = makeTrs(keys.back().position, keys.back().rotation);
        return;
    }
    size_t index = 0;
    while (index + 1 < keys.size() && keys[index + 1].time <= time) ++index;
    const Keyframe& a = keys[index];
    const Keyframe& b = keys[std::min(index + 1, keys.size() - 1)];
    const float span = b.time - a.time;
    const float alpha = span <= 1e-6f ? 0.0f : clampf((time - a.time) / span, 0.0f, 1.0f);
    out = makeTrs(lerp(a.position, b.position, alpha), slerp(a.rotation, b.rotation, alpha));
}

}  // namespace

Mat4 inverseAffine(const Mat4& matrix) {
    const float a = matrix.m[0], b = matrix.m[4], c = matrix.m[8];
    const float d = matrix.m[1], e = matrix.m[5], f = matrix.m[9];
    const float g = matrix.m[2], h = matrix.m[6], i = matrix.m[10];
    const float det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    Mat4 out;
    if (std::fabs(det) < 1e-12f) return out;
    const float inv = 1.0f / det;
    out.m[0] = (e * i - f * h) * inv;
    out.m[1] = (f * g - d * i) * inv;
    out.m[2] = (d * h - e * g) * inv;
    out.m[4] = (c * h - b * i) * inv;
    out.m[5] = (a * i - c * g) * inv;
    out.m[6] = (b * g - a * h) * inv;
    out.m[8] = (b * f - c * e) * inv;
    out.m[9] = (c * d - a * f) * inv;
    out.m[10] = (a * e - b * d) * inv;
    const float tx = matrix.m[12], ty = matrix.m[13], tz = matrix.m[14];
    out.m[12] = -(out.m[0] * tx + out.m[4] * ty + out.m[8] * tz);
    out.m[13] = -(out.m[1] * tx + out.m[5] * ty + out.m[9] * tz);
    out.m[14] = -(out.m[2] * tx + out.m[6] * ty + out.m[10] * tz);
    out.m[3] = out.m[7] = out.m[11] = 0.0f;
    out.m[15] = 1.0f;
    return out;
}

void Animator::configure(const Mesh& mesh, const std::map<std::string, Clip>& clips) {
    mesh_ = &mesh;
    clips_.clear();
    for (const auto& entry : clips) clips_[entry.first] = &entry.second;
    const size_t boneCount = mesh.bones.size();
    restLocal_.assign(boneCount > 0 ? boneCount : 1, kIdentity);
    parents_.assign(boneCount > 0 ? boneCount : 1, -1);

    std::vector<Mat4> restWorld(boneCount, kIdentity);
    for (size_t index = 0; index < boneCount; ++index) {
        parents_[index] = mesh.bones[index].parent;
        restWorld[index] = inverseAffine(mesh.bones[index].inverseBind);
    }
    for (size_t index = 0; index < boneCount; ++index) {
        const int32_t parent = parents_[index];
        if (parent >= 0 && parent < static_cast<int32_t>(index)) {
            restLocal_[index] = inverseAffine(restWorld[parent]) * restWorld[index];
        } else {
            restLocal_[index] = restWorld[index];
        }
    }
    current_ = nullptr;
    previous_ = nullptr;
    currentName_.clear();
    currentTime_ = 0.0f;
    blendElapsed_ = blendDuration_;
    finished_ = false;
}

bool Animator::play(const std::string& name, float blendSeconds, bool restart) {
    const auto found = clips_.find(name);
    if (found == clips_.end()) return false;
    if (!restart && current_ != nullptr && currentName_ == name) return true;
    previous_ = current_;
    previousTime_ = currentTime_;
    current_ = found->second;
    currentName_ = name;
    currentTime_ = 0.0f;
    blendDuration_ = std::max(0.0f, blendSeconds);
    blendElapsed_ = 0.0f;
    finished_ = false;
    return true;
}

void Animator::stop() {
    current_ = nullptr;
    previous_ = nullptr;
    currentName_.clear();
    currentTime_ = 0.0f;
    finished_ = false;
}

void Animator::update(float dt) {
    if (current_ == nullptr) return;
    currentTime_ += dt;
    if (blendElapsed_ < blendDuration_) blendElapsed_ += dt;
    if (current_->loop) {
        if (current_->duration > 1e-5f) {
            currentTime_ = std::fmod(currentTime_, current_->duration);
            if (currentTime_ < 0.0f) currentTime_ += current_->duration;
        }
    } else if (currentTime_ >= current_->duration) {
        currentTime_ = current_->duration;
        finished_ = true;
    }
    if (previous_ != nullptr) {
        previousTime_ += dt;
        if (previous_->loop && previous_->duration > 1e-5f) {
            previousTime_ = std::fmod(previousTime_, previous_->duration);
        } else if (previousTime_ > previous_->duration) {
            previousTime_ = previous_->duration;
        }
    }
}

float Animator::normalizedTime() const {
    if (current_ == nullptr || current_->duration <= 1e-5f) return 0.0f;
    return clampf(currentTime_ / current_->duration, 0.0f, 1.0f);
}

void Animator::sampleLocal(const Clip& clip, float time, std::vector<Mat4>& out,
                           bool& foundAny) const {
    for (const BoneTrack& track : clip.tracks) {
        for (size_t bone = 0; bone < mesh_->bones.size(); ++bone) {
            if (mesh_->bones[bone].nameHash != track.nameHash) continue;
            sampleTrack(track, time, out[bone]);
            foundAny = true;
            break;
        }
    }
}

void Animator::computeWorld(const std::vector<Mat4>& local, Pose& pose) const {
    const size_t boneCount = local.size();
    pose.world.assign(boneCount, kIdentity);
    pose.skin.assign(boneCount, kIdentity);
    std::vector<uint8_t> resolved(boneCount, 0);

    // Bones are stored parent-before-child, but resolve defensively in case a
    // converted asset comes from a tool with a different ordering.
    for (size_t pass = 0; pass < boneCount + 1; ++pass) {
        bool progressed = false;
        for (size_t index = 0; index < boneCount; ++index) {
            if (resolved[index]) continue;
            const int32_t parent = parents_[index];
            if (parent >= 0 && static_cast<size_t>(parent) < boneCount && !resolved[parent]) continue;
            pose.world[index] = (parent >= 0 && static_cast<size_t>(parent) < boneCount)
                                    ? pose.world[parent] * local[index]
                                    : local[index];
            pose.skin[index] = pose.world[index] *
                               (mesh_ != nullptr && index < mesh_->bones.size()
                                    ? mesh_->bones[index].inverseBind
                                    : kIdentity);
            resolved[index] = 1;
            progressed = true;
        }
        if (!progressed) break;
    }
}

void Animator::evaluate(Pose& out) const {
    const size_t boneCount = restLocal_.size();
    out.resize(boneCount);
    out.local = restLocal_;

    if (current_ != nullptr) {
        std::vector<Mat4> evaluated = restLocal_;
        bool foundAny = false;
        sampleLocal(*current_, currentTime_, evaluated, foundAny);
        const float blend = blendDuration_ <= 1e-4f ? 1.0f : clampf(blendElapsed_ / blendDuration_, 0.0f, 1.0f);
        if (previous_ != nullptr && blend < 1.0f) {
            std::vector<Mat4> previous = restLocal_;
            bool previousFound = false;
            sampleLocal(*previous_, previousTime_, previous, previousFound);
            if (previousFound) {
                // Blending TRS components would need a decomposition; instead we
                // blend the final local matrices, which is exact for the rigid
                // bone transforms produced by our pipeline.
                for (size_t bone = 0; bone < boneCount; ++bone) {
                    const Mat4& from = previous[bone];
                    const Mat4& to = evaluated[bone];
                    Mat4 mixed;
                    for (int i = 0; i < 16; ++i) mixed.m[i] = lerpf(from.m[i], to.m[i], blend);
                    evaluated[bone] = mixed;
                }
            }
        }
        out.local = std::move(evaluated);
    }
    computeWorld(out.local, out);
}

}  // namespace storm
