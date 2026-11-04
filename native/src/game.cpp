#include "storm/game.h"

#include <algorithm>
#include <cmath>

namespace storm {
namespace {

constexpr float kGravity = -26.0f;
constexpr float kRunSpeed = 4.6f;
constexpr float kAirControlScale = 0.85f;
constexpr float kJumpVelocity = 7.9f;
constexpr float kDashSpeed = 11.0f;
constexpr float kDashDuration = 0.18f;
constexpr float kGuardChakraDrain = 13.0f;
constexpr float kChakraRegen = 9.0f;
constexpr float kChakraCost = 25.0f;
constexpr float kMinSeparation = 1.15f;
constexpr float kAttackTotal = 0.62f;
constexpr float kAttackActiveStart = 0.14f;
constexpr float kAttackActiveEnd = 0.30f;
constexpr float kKickTotal = 0.80f;
constexpr float kKickActiveStart = 0.22f;
constexpr float kKickActiveEnd = 0.42f;
constexpr float kKickDamage = 34.0f;
constexpr float kBodyRadius = 0.45f;

Vec3 flatDirection(const Vec3& from, const Vec3& to, const Vec3& fallback) {
    const Vec3 delta{to.x - from.x, 0.0f, to.z - from.z};
    const float length = delta.length();
    if (length < 1e-4f) return fallback;
    return delta * (1.0f / length);
}

void enter(Fighter& fighter, FighterState state) {
    if (fighter.state == state) return;
    fighter.state = state;
    fighter.stateTime = 0.0f;
}

}  // namespace

const char* toString(FighterState state) {
    switch (state) {
        case FighterState::Idle: return "idle";
        case FighterState::Run: return "run";
        case FighterState::Dash: return "dash";
        case FighterState::Jump: return "jump";
        case FighterState::Attack: return "attack";
        case FighterState::Kick: return "kick";
        case FighterState::Guard: return "guard";
        case FighterState::Hit: return "hit";
        case FighterState::GuardBroken: return "guardbreak";
        case FighterState::Knockdown: return "knockdown";
        case FighterState::KO: return "ko";
    }
    return "idle";
}

bool isAttackState(FighterState state) {
    return state == FighterState::Attack || state == FighterState::Kick;
}

void World::configure(const MatchConfig& config) {
    config_ = config;
    reset();
}

void World::reset() {
    fighters_[0] = Fighter{};
    fighters_[1] = Fighter{};
    fighters_[0].position = {-2.2f, 0.0f, 0.0f};
    fighters_[1].position = {2.2f, 0.0f, 0.0f};
    fighters_[0].facing = kPi * 0.5f;
    fighters_[1].facing = -kPi * 0.5f;
    for (Fighter& fighter : fighters_) {
        fighter.hp = config_.startingHp;
        fighter.chakra = config_.startingChakra;
        fighter.state = FighterState::Idle;
        fighter.stateTime = 0.0f;
    }
    phase_ = MatchPhase::Fighting;
    winner_ = -1;
    timeLeft_ = config_.roundSeconds;
    hitstop_ = 0.0f;
    cameraShake_ = 0.0f;
    lastHitMagnitude_ = 0.0f;
    roundEndTimer_ = 0.0f;
    frame_ = 0;
}

void World::startRoundEnd(int winner) {
    phase_ = MatchPhase::Finished;
    winner_ = winner;
    roundEndTimer_ = 3.0f;
}

void World::updateFighter(int index, const InputState& input, float dt) {
    Fighter& fighter = fighters_[index];
    const Fighter& opponent = fighters_[1 - index];
    fighter.stateTime += dt;
    fighter.hitFlash = std::max(0.0f, fighter.hitFlash - dt * 4.0f);

    if (fighter.state == FighterState::KO) return;
    fighter.chakra = clampf(fighter.chakra + kChakraRegen * dt, 0.0f, 100.0f);

    const Vec3 fallback{std::sin(fighter.facing), 0.0f, std::cos(fighter.facing)};
    const Vec3 forward = flatDirection(fighter.position, opponent.position, fallback);
    const Vec3 right{forward.z, 0.0f, -forward.x};
    const bool locked = isAttackState(fighter.state) || fighter.state == FighterState::Hit ||
                        fighter.state == FighterState::GuardBroken ||
                        fighter.state == FighterState::Knockdown;

    if (!locked && opponent.state != FighterState::KO) {
        fighter.facing = std::atan2(forward.x, forward.z);
    }

    Vec3 move;
    if (!locked) {
        move = right * input.moveX + forward * input.moveY;
        const float length = std::sqrt(move.x * move.x + move.z * move.z);
        if (length > 1.0f) move = move * (1.0f / length);
    }

    switch (fighter.state) {
        case FighterState::Idle:
        case FighterState::Run: {
            if (input.dash) {
                enter(fighter, FighterState::Dash);
                break;
            }
            if (input.jump && fighter.grounded) {
                fighter.velocityY = kJumpVelocity;
                fighter.grounded = false;
                enter(fighter, FighterState::Jump);
                break;
            }
            if (input.chakra && fighter.chakra >= kChakraCost) {
                fighter.chakra -= kChakraCost;
                fighter.hasConnected = false;
                fighter.comboStep = 0;
                enter(fighter, FighterState::Kick);
                break;
            }
            if (input.attack) {
                fighter.hasConnected = false;
                fighter.comboStep = 0;
                enter(fighter, FighterState::Attack);
                break;
            }
            if (input.guard && fighter.grounded) {
                enter(fighter, FighterState::Guard);
                break;
            }
            const float moveLength = std::sqrt(move.x * move.x + move.z * move.z);
            if (moveLength > 0.05f) {
                fighter.position += move * (kRunSpeed * dt);
                enter(fighter, FighterState::Run);
            } else if (fighter.state == FighterState::Run) {
                enter(fighter, FighterState::Idle);
            }
            break;
        }
        case FighterState::Dash:
            fighter.position += move * (kDashSpeed * dt);
            if (fighter.stateTime >= kDashDuration) {
                enter(fighter, FighterState::Run);
            }
            break;
        case FighterState::Jump:
            fighter.position += move * (kRunSpeed * kAirControlScale * dt);
            if (input.attack) {
                fighter.hasConnected = false;
                fighter.comboStep = 0;
                enter(fighter, FighterState::Attack);
            }
            break;
        case FighterState::Attack:
            // Chain into the next hit once the active window has passed.
            if (fighter.stateTime > kAttackActiveEnd && input.attack && fighter.comboStep < 2) {
                fighter.comboStep += 1;
                fighter.stateTime = 0.0f;
                fighter.hasConnected = false;
            } else if (fighter.stateTime >= kAttackTotal) {
                enter(fighter, fighter.grounded ? FighterState::Idle : FighterState::Jump);
                fighter.comboStep = 0;
            }
            break;
        case FighterState::Kick:
            if (fighter.stateTime < 0.26f) {
                fighter.position += forward * (7.5f * dt);
            }
            if (fighter.stateTime >= kKickTotal) {
                enter(fighter, fighter.grounded ? FighterState::Idle : FighterState::Jump);
            }
            break;
        case FighterState::Guard:
            fighter.chakra -= kGuardChakraDrain * dt;
            if (fighter.chakra <= 0.0f) {
                fighter.chakra = 0.0f;
                enter(fighter, FighterState::GuardBroken);
            } else if (!input.guard) {
                enter(fighter, FighterState::Idle);
            }
            break;
        case FighterState::Hit:
            if (fighter.stateTime >= fighter.stunDuration) {
                enter(fighter, fighter.grounded ? FighterState::Idle : FighterState::Jump);
            }
            break;
        case FighterState::GuardBroken:
            if (fighter.stateTime >= 0.9f) enter(fighter, FighterState::Idle);
            break;
        case FighterState::Knockdown:
            if (fighter.stateTime >= 0.7f) enter(fighter, FighterState::Idle);
            break;
        case FighterState::KO:
            break;
    }

    if (!fighter.grounded || fighter.position.y > 1e-4f) {
        fighter.velocityY += kGravity * dt;
        fighter.position.y += fighter.velocityY * dt;
        if (fighter.position.y <= 0.0f) {
            fighter.position.y = 0.0f;
            fighter.velocityY = 0.0f;
            if (!fighter.grounded) {
                fighter.grounded = true;
                if (fighter.state == FighterState::Jump) enter(fighter, FighterState::Idle);
            }
        }
    }
}

void World::resolveSpace() {
    Fighter& a = fighters_[0];
    Fighter& b = fighters_[1];
    if (a.state == FighterState::KO || b.state == FighterState::KO) return;
    const Vec3 delta{b.position.x - a.position.x, 0.0f, b.position.z - a.position.z};
    const float distance = delta.length();
    if (distance >= kMinSeparation) return;
    const Vec3 direction = distance > 1e-4f ? delta * (1.0f / distance) : Vec3{0.0f, 0.0f, 1.0f};
    const float push = (kMinSeparation - distance) * 0.5f;
    a.position -= direction * push;
    b.position += direction * push;
}

void World::clampToArena(int index) {
    Fighter& fighter = fighters_[index];
    const float limit = config_.arenaRadius - kBodyRadius;
    const float distance = std::sqrt(fighter.position.x * fighter.position.x +
                                     fighter.position.z * fighter.position.z);
    if (distance <= limit || distance < 1e-4f) return;
    const float scale = limit / distance;
    fighter.position.x *= scale;
    fighter.position.z *= scale;
}

void World::resolveCombat(int attackerIndex) {
    Fighter& attacker = fighters_[attackerIndex];
    Fighter& defender = fighters_[1 - attackerIndex];
    if (attacker.hasConnected || defender.state == FighterState::KO) return;

    float range = 0.0f;
    float damage = 0.0f;
    float knockback = 0.0f;
    bool heavy = false;
    const float time = attacker.stateTime;

    if (attacker.state == FighterState::Attack && time >= kAttackActiveStart &&
        time <= kAttackActiveEnd) {
        range = 2.55f;
        damage = 15.0f + 4.0f * static_cast<float>(attacker.comboStep);
        knockback = 0.35f;
    } else if (attacker.state == FighterState::Kick && time >= kKickActiveStart &&
               time <= kKickActiveEnd) {
        range = 3.1f;
        damage = kKickDamage;
        knockback = 1.6f;
        heavy = true;
    } else {
        return;
    }

    const Vec3 fallback{std::sin(attacker.facing), 0.0f, std::cos(attacker.facing)};
    const Vec3 direction = flatDirection(attacker.position, defender.position, fallback);
    const float distance = std::sqrt(
        (defender.position.x - attacker.position.x) * (defender.position.x - attacker.position.x) +
        (defender.position.z - attacker.position.z) * (defender.position.z - attacker.position.z));
    if (distance > range) return;
    if (fallback.dot(direction) < 0.15f) return;

    attacker.hasConnected = true;
    applyHit(attackerIndex, 1 - attackerIndex, damage, knockback, heavy);
}

void World::applyHit(int attackerIndex, int defenderIndex, float damage, float knockback,
                     bool heavy) {
    Fighter& attacker = fighters_[attackerIndex];
    Fighter& defender = fighters_[defenderIndex];
    const Vec3 fallback{std::sin(attacker.facing), 0.0f, std::cos(attacker.facing)};
    const Vec3 direction = flatDirection(attacker.position, defender.position, fallback);

    bool blocked = defender.state == FighterState::Guard;
    if (blocked) {
        const Vec3 defenderForward{std::sin(defender.facing), 0.0f, std::cos(defender.facing)};
        // The guard only holds if it faces the incoming attack.
        if (defenderForward.dot(direction) < -0.1f) blocked = false;
    }

    if (blocked) {
        damage *= 0.15f;
        knockback *= 0.35f;
        defender.chakra = std::max(0.0f, defender.chakra - damage * 3.0f);
        if (defender.chakra <= 0.0f) enter(defender, FighterState::GuardBroken);
    } else {
        defender.state = heavy ? FighterState::Knockdown : FighterState::Hit;
        defender.stateTime = 0.0f;
        defender.stunDuration = heavy ? 0.55f : 0.34f;
        if (heavy) {
            defender.velocityY = 4.2f;
            defender.grounded = false;
        }
    }

    defender.hp = clampf(defender.hp - damage, 0.0f, 100.0f);
    defender.position += direction * knockback;
    defender.hitFlash = 1.0f;
    hitstop_ = std::max(hitstop_, blocked ? 0.03f : 0.06f);
    cameraShake_ = std::max(cameraShake_, blocked ? 0.10f : 0.22f);
    lastHitMagnitude_ = clampf(damage / kKickDamage, 0.0f, 1.0f);

    if (defender.hp <= 0.0f && phase_ == MatchPhase::Fighting) {
        defender.state = FighterState::KO;
        defender.stateTime = 0.0f;
        startRoundEnd(defenderIndex == 0 ? 1 : 0);
    }
}

void World::step(const InputState& playerOne, const InputState& playerTwo) {
    if (hitstop_ > 0.0f) {
        hitstop_ = std::max(0.0f, hitstop_ - kFixedDt);
        cameraShake_ = std::max(0.0f, cameraShake_ - kFixedDt * 1.5f);
        return;
    }
    frame_ += 1;
    cameraShake_ = std::max(0.0f, cameraShake_ - kFixedDt * 1.2f);
    lastHitMagnitude_ *= 0.92f;

    if (phase_ == MatchPhase::Finished) {
        for (Fighter& fighter : fighters_) fighter.stateTime += kFixedDt;
        roundEndTimer_ = std::max(0.0f, roundEndTimer_ - kFixedDt);
        return;
    }

    updateFighter(0, playerOne, kFixedDt);
    updateFighter(1, playerTwo, kFixedDt);
    resolveSpace();
    clampToArena(0);
    clampToArena(1);
    resolveCombat(0);
    resolveCombat(1);

    timeLeft_ = std::max(0.0f, timeLeft_ - kFixedDt);
    if (timeLeft_ <= 0.0f) {
        if (fighters_[0].hp > fighters_[1].hp) {
            startRoundEnd(0);
        } else if (fighters_[1].hp > fighters_[0].hp) {
            startRoundEnd(1);
        } else {
            startRoundEnd(-1);
        }
    }
}

CameraRig computeCamera(const World& world, float aspect, float seconds) {
    const Fighter& a = world.fighter(0);
    const Fighter& b = world.fighter(1);
    const Vec3 midpoint = (a.position + b.position) * 0.5f;
    const Vec3 delta{b.position.x - a.position.x, 0.0f, b.position.z - a.position.z};
    const float separation = delta.length();
    const Vec3 forward = separation > 1e-3f ? delta * (1.0f / separation) : Vec3{0.0f, 0.0f, 1.0f};
    const Vec3 side{forward.z, 0.0f, -forward.x};
    const float distance = clampf(5.6f + separation * 0.42f, 5.2f, 9.5f);
    const float height = 2.35f + separation * 0.13f;

    Vec3 eye = midpoint - forward * (distance * 0.62f) + side * (distance * 0.55f) +
               Vec3{0.0f, height, 0.0f};
    const float shake = world.cameraShake() * 0.42f;
    if (shake > 0.0f) {
        eye += Vec3{std::sin(seconds * 57.0f) * shake, std::sin(seconds * 83.0f) * shake * 0.7f,
                    std::cos(seconds * 43.0f) * shake};
    }
    const Vec3 target = midpoint + Vec3{0.0f, 1.15f + (a.position.y + b.position.y) * 0.12f, 0.0f};

    CameraRig rig;
    rig.position = eye;
    rig.target = target;
    rig.view = lookAt(eye, target, Vec3{0.0f, 1.0f, 0.0f});
    rig.projection = perspective(56.0f * kDeg2Rad, aspect, 0.1f, 140.0f);
    rig.viewProjection = rig.projection * rig.view;
    return rig;
}

}  // namespace storm
