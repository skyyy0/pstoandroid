// Adaptive performance governor: dynamic resolution + quality tiers + thermal
// aware frame-rate fallback. Pure logic, fully unit tested on the host.
#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace storm {

struct PerfConfig {
    float targetFps = 60.0f;
    float minScale = 0.55f;
    float maxScale = 1.0f;
    int minTier = 1;
    int maxTier = 3;
    int windowFrames = 90;
    int evaluateEvery = 24;
    float downshiftThreshold = 1.08f;  // p95 above budget * threshold -> downscale
    float upshiftThreshold = 0.82f;    // p95 below budget * threshold -> upscale
    float downshiftStep = 0.08f;
    float upshiftStep = 0.03f;
    int thermalFramesBeforeCap = 1800;  // ~30s pinned at the floor
};

// Maps a chipset temperature (Celsius) to a 0..1 pressure value. SoC sensors
// below ~46 C are treated as cool, 76 C and above as fully throttled.
float thermalPressureFromCelsius(float celsius);

class PerfGovernor {
public:
    explicit PerfGovernor(const PerfConfig& config = PerfConfig{});

    void pushFrame(float frameMs);
    void reset();

    float resolutionScale() const { return scale_; }
    int qualityTier() const { return tier_; }
    float targetFps() const { return activeTargetFps_; }
    float averageFps() const { return averageFps_; }
    float p95FrameMs() const { return p95Ms_; }
    bool thermalCapped() const { return thermalCapped_; }
    int samplesUntilEvaluation() const;

    // Platform thermal signal, 0 = cool .. 1 = hard throttling. Pushing >= 0.85
    // immediately clamps quality and drops the pacing target to 30 fps; the
    // governor restores the original target once the device cools down.
    void setThermalPressure(float pressure);
    float thermalPressure() const { return thermalPressure_; }

    // Consumed by the renderer to rebuild attachments when the scale changes.
    bool consumeResolutionChange();

    // Health probe used by the HUD/diagnostics overlay.
    const PerfConfig& config() const { return config_; }

private:
    void evaluate();

    PerfConfig config_;
    std::vector<float> history_;
    size_t historyCursor_ = 0;
    size_t historyCount_ = 0;
    int framesSinceEvaluation_ = 0;
    int slowStreakFrames_ = 0;
    int totalFrames_ = 0;
    float scale_ = 1.0f;
    int tier_ = 3;
    float activeTargetFps_ = 60.0f;
    float averageFps_ = 60.0f;
    float p95Ms_ = 16.7f;
    bool thermalCapped_ = false;
    bool resolutionDirty_ = false;
    float thermalPressure_ = 0.0f;
};

}  // namespace storm
