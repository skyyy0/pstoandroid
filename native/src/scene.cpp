#include "storm/scene.h"

#include <algorithm>

namespace storm {
namespace {

bool loadPackage(AssetSource& source, const std::string& path, Mesh& mesh, std::string& error) {
    std::vector<uint8_t> bytes;
    if (!source.read(path, bytes)) {
        error = "asset not found: " + path;
        return false;
    }
    std::string parseError;
    if (!parseMesh(bytes.data(), bytes.size(), mesh, parseError)) {
        error = path + ": " + parseError;
        return false;
    }
    return true;
}

bool loadClips(AssetSource& source, const Manifest& manifest, const std::string& meshName,
               std::map<std::string, Clip>& clips, std::string& error) {
    const auto found = manifest.animations.find(meshName);
    if (found == manifest.animations.end()) {
        error = "manifest has no animations for mesh '" + meshName + "'";
        return false;
    }
    for (const auto& entry : found->second) {
        std::vector<uint8_t> bytes;
        if (!source.read(entry.second, bytes)) {
            error = "animation not found: " + entry.second;
            return false;
        }
        Clip clip;
        std::string parseError;
        if (!parseClip(bytes.data(), bytes.size(), clip, parseError)) {
            error = entry.second + ": " + parseError;
            return false;
        }
        if (clip.name.empty()) clip.name = entry.first;
        clips[entry.first] = std::move(clip);
    }
    return true;
}

}  // namespace

std::string Scene::clipFor(FighterState state) {
    switch (state) {
        case FighterState::Idle: return "idle";
        case FighterState::Run: return "run";
        case FighterState::Dash: return "run";
        case FighterState::Jump: return "jump";
        case FighterState::Attack: return "attack";
        case FighterState::Kick: return "kick";
        case FighterState::Guard: return "guard";
        case FighterState::Hit: return "hit";
        case FighterState::GuardBroken: return "hit";
        case FighterState::Knockdown: return "hit";
        case FighterState::KO: return "hit";
    }
    return "idle";
}

bool Scene::load(AssetSource& source, const Manifest& manifest, std::string& error) {
    ready_ = false;

    std::string arenaId = "dojo";
    if (manifest.arenas.find(arenaId) == manifest.arenas.end()) {
        if (manifest.arenas.empty()) {
            error = "manifest has no arena";
            return false;
        }
        arenaId = manifest.arenas.begin()->first;
    }
    const std::string arenaMeshName = manifest.arenas.at(arenaId);
    const auto arenaPath = manifest.meshes.find(arenaMeshName);
    if (arenaPath == manifest.meshes.end()) {
        error = "manifest arena mesh '" + arenaMeshName + "' is not declared";
        return false;
    }
    if (!loadPackage(source, arenaPath->second, arena_, error)) return false;

    // Player 1 is "rookie", player 2 "rival" when present, otherwise the first
    // two characters declared in the manifest.
    std::vector<std::string> characterIds;
    for (const auto& entry : manifest.characters) characterIds.push_back(entry.first);
    if (characterIds.size() < 2) {
        error = "manifest needs at least two characters";
        return false;
    }
    std::string first = manifest.characters.count("rookie") ? "rookie" : characterIds[0];
    std::string second = manifest.characters.count("rival") ? "rival" : characterIds[1];
    if (first == second) second = characterIds[1];

    const Manifest::CharacterEntry& entryA = manifest.characters.at(first);
    const Manifest::CharacterEntry& entryB = manifest.characters.at(second);
    const auto meshA = manifest.meshes.find(entryA.mesh);
    const auto meshB = manifest.meshes.find(entryB.mesh);
    if (meshA == manifest.meshes.end() || meshB == manifest.meshes.end()) {
        error = "manifest character mesh is not declared";
        return false;
    }
    if (!loadPackage(source, meshA->second, fighter_, error)) return false;
    if (!loadPackage(source, meshB->second, rival_, error)) return false;

    if (!loadClips(source, manifest, entryA.mesh, fighterClips_, error)) return false;
    // Characters that share a skeleton (the common case for palette swaps) may
    // reuse the first mesh's clip set instead of duplicating every animation.
    if (entryB.mesh == entryA.mesh || manifest.animations.find(entryB.mesh) == manifest.animations.end()) {
        rivalClips_ = fighterClips_;
    } else if (!loadClips(source, manifest, entryB.mesh, rivalClips_, error)) {
        return false;
    }

    fighterScale_[0] = entryA.scale;
    fighterScale_[1] = entryB.scale;
    animators_[0].configure(fighter_, fighterClips_);
    animators_[1].configure(rival_, rivalClips_);
    for (int i = 0; i < 2; ++i) {
        animators_[i].play("idle", 0.0f, true);
        animators_[i].update(0.0f);
        animators_[i].evaluate(poses_[i]);
        playing_[i] = "idle";
    }
    ready_ = true;
    return true;
}

void Scene::update(float dt, const World& world) {
    if (!ready_) return;
    for (int i = 0; i < 2; ++i) {
        const std::string desired = clipFor(world.fighter(i).state);
        if (desired != playing_[i]) {
            const float blend = world.fighter(i).state == FighterState::Hit ? 0.05f : 0.14f;
            if (animators_[i].play(desired, blend, true)) {
                playing_[i] = desired;
            }
        }
        animators_[i].update(dt);
        animators_[i].evaluate(poses_[i]);
    }
}

void Scene::build(const World& world, const PerfGovernor& perf, float aspect, float seconds,
                  FrameView& out) {
    const CameraRig rig = computeCamera(world, aspect, seconds);
    out.view = rig.view;
    out.projection = rig.projection;
    out.viewProjection = rig.viewProjection;
    out.cameraPosition = rig.position;
    out.cameraTarget = rig.target;
    out.resolutionScale = perf.resolutionScale();
    out.qualityTier = perf.qualityTier();
    out.arenaRadius = world.config().arenaRadius;
    out.winner = world.winner();
    out.phase = world.phase();
    out.timeLeft = world.timeLeft();
    out.hitFlash = world.lastHitMagnitude();

    out.items.clear();
    if (!ready_) return;

    DrawItem arena;
    arena.mesh = &arena_;
    arena.pose = nullptr;
    arena.model = Mat4::identity();
    arena.castShadow = false;
    out.items.push_back(arena);

    for (int i = 0; i < 2; ++i) {
        const Fighter& fighter = world.fighter(i);
        DrawItem item;
        item.mesh = i == 1 ? &rival_ : &fighter_;
        item.pose = &poses_[i];
        const Mat4 rotation = [] (float facing) {
            Mat4 matrix = Mat4::identity();
            const float c = std::cos(facing);
            const float s = std::sin(facing);
            matrix.m[0] = c;
            matrix.m[2] = -s;
            matrix.m[8] = s;
            matrix.m[10] = c;
            return matrix;
        }(fighter.facing);
        item.model = Mat4::translation(fighter.position) * rotation *
                     Mat4::scale(fighterScale_[i]);
        item.flash = fighter.hitFlash;
        item.castShadow = true;
        out.items.push_back(item);
        out.hp[i] = fighter.hpFraction();
        out.chakra[i] = fighter.chakraFraction();
    }
}

std::string Scene::stateSummary(int index) const {
    if (!ready_) return "unloaded";
    return playing_[index] + " (" + animators_[index].currentClip() + ")";
}

}  // namespace storm
