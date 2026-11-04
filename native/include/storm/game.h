// Fixed-step duel simulation. Kept free of rendering and platform code so the
// whole gameplay loop can be exercised by host unit tests.
#pragma once

#include <cstdint>

#include "storm/math.h"

namespace storm {

constexpr float kFixedDt = 1.0f / 60.0f;

enum class FighterState {
    Idle,
    Run,
    Dash,
    Jump,
    Attack,
    Kick,
    Guard,
    Hit,
    GuardBroken,
    Knockdown,
    KO,
};

const char* toString(FighterState state);
bool isAttackState(FighterState state);

struct InputState {
    float moveX = 0.0f;  // -1 left .. 1 right (arena relative)
    float moveY = 0.0f;  // -1 back .. 1 towards the opponent
    bool attack = false;
    bool chakra = false;
    bool guard = false;
    bool jump = false;
    bool dash = false;

    void clearButtons() {
        attack = false;
        chakra = false;
        guard = false;
        jump = false;
        dash = false;
    }
};

struct Fighter {
    Vec3 position;
    float facing = 0.0f;
    float velocityY = 0.0f;
    float hp = 100.0f;
    float chakra = 100.0f;
    FighterState state = FighterState::Idle;
    float stateTime = 0.0f;
    int comboStep = 0;
    bool hasConnected = false;
    bool grounded = true;
    float hitFlash = 0.0f;
    float stunDuration = 0.34f;

    float hpFraction() const { return clampf(hp / 100.0f, 0.0f, 1.0f); }
    float chakraFraction() const { return clampf(chakra / 100.0f, 0.0f, 1.0f); }
};

struct MatchConfig {
    float arenaRadius = 11.5f;
    float roundSeconds = 99.0f;
    float startingHp = 100.0f;
    float startingChakra = 100.0f;
};

enum class MatchPhase { Fighting, Finished };

class World {
public:
    void configure(const MatchConfig& config);
    void reset();

    // Advances the duel by exactly one fixed tick. Inputs are edge-triggered by
    // the caller: press jump once, not every frame.
    void step(const InputState& playerOne, const InputState& playerTwo);

    const Fighter& fighter(int index) const { return fighters_[index < 0 ? 0 : (index > 1 ? 1 : index)]; }
    Fighter& fighterMutable(int index) { return fighters_[index == 1 ? 1 : 0]; }

    MatchPhase phase() const { return phase_; }
    int winner() const { return winner_; }
    float timeLeft() const { return timeLeft_; }
    float hitstop() const { return hitstop_; }
    float cameraShake() const { return cameraShake_; }
    float lastHitMagnitude() const { return lastHitMagnitude_; }
    int frame() const { return frame_; }
    const MatchConfig& config() const { return config_; }
    void setPhase(MatchPhase phase) { phase_ = phase; }

private:
    void updateFighter(int index, const InputState& input, float dt);
    void resolveCombat(int attackerIndex);
    void resolveFacing(int index);
    void resolveSpace();
    void clampToArena(int index);
    void startRoundEnd(int winner);
    void applyHit(int attackerIndex, int defenderIndex, float damage, float knockback, bool heavy);

    MatchConfig config_;
    Fighter fighters_[2];
    MatchPhase phase_ = MatchPhase::Fighting;
    int winner_ = -1;
    float timeLeft_ = 99.0f;
    float hitstop_ = 0.0f;
    float cameraShake_ = 0.0f;
    float lastHitMagnitude_ = 0.0f;
    float roundEndTimer_ = 0.0f;
    int frame_ = 0;
};

// Deterministic, frame-counter driven CPU opponent (no global RNG state).
InputState cpuThink(const World& world, int selfIndex, uint32_t seed, bool& guardLatch);

struct CameraRig {
    Mat4 view;
    Mat4 projection;
    Mat4 viewProjection;
    Vec3 position;
    Vec3 target;
};

CameraRig computeCamera(const World& world, float aspect, float seconds);

}  // namespace storm
