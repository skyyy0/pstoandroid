#include "storm/perf.h"

#include <algorithm>
#include <numeric>

namespace storm {

PerfGovernor::PerfGovernor(const PerfConfig& config) : config_(config) {
    config_.windowFrames = std::max(16, config_.windowFrames);
    config_.evaluateEvery = std::max(4, config_.evaluateEvery);
    history_.assign(static_cast<size_t>(config_.windowFrames), 1000.0f / config_.targetFps);
    reset();
}

void PerfGovernor::reset() {
    std::fill(history_.begin(), history_.end(), 1000.0f / config_.targetFps);
    historyCursor_ = 0;
    historyCount_ = 0;
    framesSinceEvaluation_ = 0;
    slowStreakFrames_ = 0;
    totalFrames_ = 0;
    scale_ = config_.maxScale;
    tier_ = config_.maxTier;
    activeTargetFps_ = config_.targetFps;
    averageFps_ = config_.targetFps;
    p95Ms_ = 1000.0f / config_.targetFps;
    thermalCapped_ = false;
    resolutionDirty_ = false;
    thermalPressure_ = 0.0f;
}

void PerfGovernor::setThermalPressure(float pressure) {
    if (!(pressure >= 0.0f)) pressure = 0.0f;
    thermalPressure_ = std::min(pressure, 1.0f);
    if (thermalPressure_ >= 0.85f) {
        thermalCapped_ = true;
        activeTargetFps_ = std::min(activeTargetFps_, 30.0f);
        if (scale_ > config_.minScale + 1e-4f) {
            scale_ = config_.minScale;
            resolutionDirty_ = true;
        }
        tier_ = config_.minTier;
    } else if (thermalPressure_ >= 0.6f) {
        tier_ = std::max(config_.minTier, tier_ - 1);
    } else if (thermalPressure_ <= 0.35f && thermalCapped_) {
        // Cooled down: hand control back to the frame-time governor.
        thermalCapped_ = false;
        activeTargetFps_ = config_.targetFps;
        slowStreakFrames_ = 0;
    }
}

float thermalPressureFromCelsius(float celsius) {
    if (!(celsius > -40.0f)) return 0.0f;
    constexpr float kCool = 46.0f;
    constexpr float kHot = 76.0f;
    return std::clamp((celsius - kCool) / (kHot - kCool), 0.0f, 1.0f);
}

void PerfGovernor::pushFrame(float frameMs) {
    if (!(frameMs > 0.0f)) frameMs = 0.001f;
    history_[historyCursor_] = std::min(frameMs, 250.0f);
    historyCursor_ = (historyCursor_ + 1) % history_.size();
    if (historyCount_ < history_.size()) historyCount_ += 1;
    totalFrames_ += 1;
    framesSinceEvaluation_ += 1;
    if (framesSinceEvaluation_ >= config_.evaluateEvery) {
        framesSinceEvaluation_ = 0;
        evaluate();
    }
}

int PerfGovernor::samplesUntilEvaluation() const {
    return std::max(0, config_.evaluateEvery - framesSinceEvaluation_);
}

void PerfGovernor::evaluate() {
    if (historyCount_ == 0) return;
    std::vector<float> window;
    window.reserve(historyCount_);
    for (size_t i = 0; i < historyCount_; ++i) {
        const size_t index = (historyCursor_ + history_.size() - 1 - i) % history_.size();
        window.push_back(history_[index]);
    }
    std::sort(window.begin(), window.end());
    const size_t p95Index = std::min(window.size() - 1, static_cast<size_t>(window.size() * 0.95));
    p95Ms_ = window[p95Index];

    const float total = std::accumulate(window.begin(), window.end(), 0.0f);
    const float mean = total / static_cast<float>(window.size());
    averageFps_ = mean > 0.0f ? 1000.0f / mean : 0.0f;

    const float budget = 1000.0f / activeTargetFps_;
    const bool tooSlow = p95Ms_ > budget * config_.downshiftThreshold;
    const bool plentyOfHeadroom = p95Ms_ < budget * config_.upshiftThreshold;

    if (tooSlow) {
        slowStreakFrames_ += config_.evaluateEvery;
        if (scale_ > config_.minScale + 1e-4f) {
            scale_ = std::max(config_.minScale, scale_ - config_.downshiftStep);
            resolutionDirty_ = true;
        } else if (tier_ > config_.minTier) {
            tier_ -= 1;
        } else if (slowStreakFrames_ >= config_.thermalFramesBeforeCap &&
                   activeTargetFps_ > 30.5f) {
            // Pinned at the floor for a long time: the device is likely thermally
            // limited, so drop the pacing target instead of shredding quality.
            activeTargetFps_ = 30.0f;
            thermalCapped_ = true;
            p95Ms_ = 1000.0f / activeTargetFps_;
        }
    } else if (plentyOfHeadroom) {
        slowStreakFrames_ = 0;
        if (scale_ < config_.maxScale - 1e-4f) {
            scale_ = std::min(config_.maxScale, scale_ + config_.upshiftStep);
            resolutionDirty_ = true;
        } else if (tier_ < config_.maxTier) {
            tier_ += 1;
        }
    } else {
        slowStreakFrames_ = 0;
    }
}

bool PerfGovernor::consumeResolutionChange() {
    const bool changed = resolutionDirty_;
    resolutionDirty_ = false;
    return changed;
}

}  // namespace storm
