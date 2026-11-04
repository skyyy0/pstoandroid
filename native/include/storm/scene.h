// Turns world state into a flat, renderer-agnostic frame description.
#pragma once

#include <map>
#include <string>
#include <vector>

#include "storm/animation.h"
#include "storm/asset.h"
#include "storm/asset_source.h"
#include "storm/game.h"
#include "storm/perf.h"

namespace storm {

struct DrawItem {
    const Mesh* mesh = nullptr;
    const Pose* pose = nullptr;
    Mat4 model;
    float flash = 0.0f;
    bool castShadow = true;
};

struct FrameView {
    Mat4 view;
    Mat4 projection;
    Mat4 viewProjection;
    Vec3 cameraPosition;
    Vec3 cameraTarget;
    Vec3 lightDirection{-0.42f, -0.78f, -0.46f};
    std::vector<DrawItem> items;
    float resolutionScale = 1.0f;
    int qualityTier = 3;
    float arenaRadius = 11.5f;
    int winner = -1;
    MatchPhase phase = MatchPhase::Fighting;
    float timeLeft = 99.0f;
    float hp[2] = {1.0f, 1.0f};
    float chakra[2] = {1.0f, 1.0f};
    float hitFlash = 0.0f;
};

class Scene {
public:
    bool load(AssetSource& source, const Manifest& manifest, std::string& error);

    // Selects animation clips from fighter state and advances the animators.
    void update(float dt, const World& world);

    void build(const World& world, const PerfGovernor& perf, float aspect, float seconds,
               FrameView& out);

    bool ready() const { return ready_; }
    const Mesh& arenaMesh() const { return arena_; }
    const Mesh& fighterMesh(int index) const { return index == 1 ? rival_ : fighter_; }
    std::string stateSummary(int index) const;

private:
    static std::string clipFor(FighterState state);

    Mesh arena_;
    Mesh fighter_;
    Mesh rival_;
    std::map<std::string, Clip> fighterClips_;
    std::map<std::string, Clip> rivalClips_;
    Animator animators_[2];
    Pose poses_[2];
    std::string playing_[2];
    float fighterScale_[2] = {1.0f, 1.0f};
    bool ready_ = false;
};

}  // namespace storm
