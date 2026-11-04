// Lightweight CPU opponent. Deterministic per (frame, seed) so replays and host
// tests behave identically; difficulty is expressed in reaction time and
// aggression rather than cheating on damage.
#include "storm/game.h"

#include <cmath>

namespace storm {
namespace {

uint32_t hash(uint32_t value) {
    value ^= value >> 16;
    value *= 0x7feb352du;
    value ^= value >> 15;
    value *= 0x846ca68bu;
    value ^= value >> 16;
    return value;
}

float randomUnit(uint32_t seed, uint32_t frame, uint32_t salt) {
    return static_cast<float>(hash(seed ^ (frame * 2654435761u) ^ salt) % 10000u) / 10000.0f;
}

}  // namespace

InputState cpuThink(const World& world, int selfIndex, uint32_t seed, bool& guardLatch) {
    InputState input;
    const Fighter& self = world.fighter(selfIndex);
    const Fighter& opponent = world.fighter(1 - selfIndex);
    if (world.phase() == MatchPhase::Finished || self.state == FighterState::KO) {
        return input;
    }

    const float dx = opponent.position.x - self.position.x;
    const float dz = opponent.position.z - self.position.z;
    const float distance = std::sqrt(dx * dx + dz * dz);
    const uint32_t frame = static_cast<uint32_t>(world.frame());
    const float roll = randomUnit(seed, frame, 0x9e3779b9u);
    const float tick = randomUnit(seed, frame / 8u, 0x85ebca6bu);

    // Face the opponent along the arena basis used by the simulation: +Y in the
    // input stick means "towards the opponent".
    const float toward = distance > 0.05f ? 1.0f : 0.0f;
    const bool opponentBusy = isAttackState(opponent.state) || opponent.state == FighterState::Jump;

    if (distance > 4.2f) {
        input.moveY = toward;
        if (distance > 7.0f && roll > 0.72f && self.grounded) {
            input.dash = true;
        }
        if (roll > 0.955f && self.grounded) input.jump = true;
    } else if (distance > 2.6f) {
        input.moveY = toward * 0.85f;
        input.moveX = (tick - 0.5f) * 0.6f;
        if (roll > 0.80f && self.chakra >= 25.0f) input.chakra = true;
    } else {
        if (opponentBusy && roll > 0.42f) {
            // Block when the opponent commits, unless we decide to counter.
            guardLatch = true;
        }
        if (guardLatch && roll > 0.55f) {
            input.guard = true;
            if (roll > 0.93f) guardLatch = false;
        } else {
            guardLatch = false;
            if (roll > 0.18f) input.attack = true;
            if (roll > 0.90f && self.chakra >= 25.0f) input.chakra = true;
            if (roll > 0.965f && self.grounded) input.jump = true;
            if (roll < 0.12f) input.moveY = -0.7f;
        }
    }

    if (self.hp < 28.0f && distance < 5.0f && roll > 0.5f) {
        input.moveY = -0.9f;
        input.attack = false;
    }
    return input;
}

}  // namespace storm
