// JNI surface between the Kotlin shell (GLSurfaceView + touch overlay) and the
// C++ engine. All GL work happens on the GL thread; touch input is delivered
// through atomics so the UI thread never blocks the renderer.
#include <android/asset_manager.h>
#include <android/asset_manager_jni.h>
#include <android/log.h>
#include <jni.h>

#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <memory>
#include <string>
#include <vector>

#include "storm/asset_source.h"
#include "storm/game.h"
#include "storm/perf.h"
#include "storm/scene.h"
#include "render/gl_renderer.h"

namespace {

constexpr const char* kTag = "StormPort";

struct InputBits {
    static constexpr int Attack = 1 << 0;
    static constexpr int Chakra = 1 << 1;
    static constexpr int Guard = 1 << 2;
    static constexpr int Jump = 1 << 3;
    static constexpr int Dash = 1 << 4;
};

class AndroidAssetSource : public storm::AssetSource {
public:
    explicit AndroidAssetSource(AAssetManager* manager) : manager_(manager) {}

    bool read(const std::string& path, std::vector<uint8_t>& out) override {
        if (manager_ == nullptr) return false;
        AAsset* asset = AAssetManager_open(manager_, path.c_str(), AASSET_MODE_BUFFER);
        if (asset == nullptr) return false;
        const long long length = static_cast<long long>(AAsset_getLength64(asset));
        if (length <= 0) {
            AAsset_close(asset);
            return false;
        }
        out.resize(static_cast<size_t>(length));
        const int bytesRead = AAsset_read(asset, out.data(), out.size());
        AAsset_close(asset);
        return bytesRead == static_cast<int>(length);
    }

private:
    AAssetManager* manager_ = nullptr;
};

struct Engine {
    storm::Manifest manifest;
    storm::Scene scene;
    storm::World world;
    storm::PerfGovernor perf;
    storm::GLRenderer renderer;
    storm::FrameView frame;
    bool ready = false;

    double accumulator = 0.0;
    double elapsed = 0.0;
    std::chrono::steady_clock::time_point lastFrame = std::chrono::steady_clock::now();

    std::atomic<int> buttons{0};
    std::atomic<float> moveX{0.0f};
    std::atomic<float> moveY{0.0f};
    std::atomic<bool> resetRequested{false};
    std::atomic<float> thermalCelsius{-1000.0f};
    int previousButtons = 0;
    bool guardLatch = false;
    uint32_t seed = 0x5eed1234u;
    int surfaceWidth = 1;
    int surfaceHeight = 1;
};

std::unique_ptr<Engine> g_engine;

void logError(const std::string& message) {
    __android_log_print(ANDROID_LOG_ERROR, kTag, "%s", message.c_str());
}

}  // namespace

extern "C" {

JNIEXPORT jboolean JNICALL
Java_com_sky_stormrev_NativeBridge_initialize(JNIEnv* env, jobject /*thiz*/, jobject assetManager) {
    g_engine = std::make_unique<Engine>();
    if (assetManager == nullptr) {
        logError("assets manager is null");
        return JNI_FALSE;
    }
    AAssetManager* manager = AAssetManager_fromJava(env, assetManager);
    if (manager == nullptr) {
        logError("AAssetManager_fromJava failed");
        return JNI_FALSE;
    }
    AndroidAssetSource source(manager);

    std::vector<uint8_t> manifestBytes;
    if (!source.read("storm/manifest.txt", manifestBytes)) {
        logError("storm/manifest.txt missing from APK assets");
        return JNI_FALSE;
    }
    const std::string manifestText(manifestBytes.begin(), manifestBytes.end());
    if (!g_engine->manifest.parse(manifestText)) {
        logError("manifest is empty or unparsable");
        return JNI_FALSE;
    }
    for (const std::string& warning : g_engine->manifest.warnings) {
        __android_log_print(ANDROID_LOG_WARN, kTag, "manifest: %s", warning.c_str());
    }

    std::string error;
    if (!g_engine->scene.load(source, g_engine->manifest, error)) {
        logError("scene load failed: " + error);
        return JNI_FALSE;
    }
    if (!g_engine->renderer.initialize(error)) {
        logError("renderer init failed: " + error);
        return JNI_FALSE;
    }

    storm::MatchConfig config;
    g_engine->world.configure(config);
    g_engine->perf.reset();
    g_engine->lastFrame = std::chrono::steady_clock::now();
    g_engine->ready = true;
    __android_log_print(ANDROID_LOG_INFO, kTag, "engine ready (GLES %s)",
                        reinterpret_cast<const char*>(glGetString(GL_VERSION)));
    return JNI_TRUE;
}

JNIEXPORT void JNICALL
Java_com_sky_stormrev_NativeBridge_shutdown(JNIEnv*, jobject /*thiz*/) {
    if (g_engine) {
        g_engine->renderer.shutdown();
        g_engine.reset();
    }
}

JNIEXPORT void JNICALL
Java_com_sky_stormrev_NativeBridge_resize(JNIEnv*, jobject /*thiz*/, jint width, jint height) {
    if (!g_engine) return;
    g_engine->surfaceWidth = width > 0 ? static_cast<int>(width) : 1;
    g_engine->surfaceHeight = height > 0 ? static_cast<int>(height) : 1;
    g_engine->renderer.resize(g_engine->surfaceWidth, g_engine->surfaceHeight);
}

JNIEXPORT void JNICALL
Java_com_sky_stormrev_NativeBridge_setInput(JNIEnv*, jobject /*thiz*/, jfloat moveX, jfloat moveY,
                                            jint buttons) {
    if (!g_engine) return;
    g_engine->moveX.store(storm::clampf(moveX, -1.0f, 1.0f));
    g_engine->moveY.store(storm::clampf(moveY, -1.0f, 1.0f));
    g_engine->buttons.store(static_cast<int>(buttons));
}

JNIEXPORT void JNICALL
Java_com_sky_stormrev_NativeBridge_setThermal(JNIEnv*, jobject /*thiz*/, jfloat celsius) {
    if (!g_engine) return;
    g_engine->thermalCelsius.store(celsius);
}

JNIEXPORT void JNICALL
Java_com_sky_stormrev_NativeBridge_resetMatch(JNIEnv*, jobject /*thiz*/) {
    if (!g_engine) return;
    g_engine->resetRequested.store(true);
}

JNIEXPORT void JNICALL
Java_com_sky_stormrev_NativeBridge_frame(JNIEnv*, jobject /*thiz*/) {
    if (!g_engine || !g_engine->ready) return;

    const auto now = std::chrono::steady_clock::now();
    float dt = std::chrono::duration<float>(now - g_engine->lastFrame).count();
    g_engine->lastFrame = now;
    if (!(dt >= 0.0f)) dt = 0.0f;
    dt = storm::clampf(dt, 0.0f, 0.1f);
    g_engine->elapsed += dt;
    g_engine->perf.pushFrame(dt * 1000.0f);
    g_engine->perf.setThermalPressure(
        storm::thermalPressureFromCelsius(g_engine->thermalCelsius.load()));

    if (g_engine->resetRequested.exchange(false)) {
        g_engine->world.reset();
        g_engine->scene.update(storm::kFixedDt, g_engine->world);
    }

    const int held = g_engine->buttons.load();
    const int pressed = held & ~g_engine->previousButtons;
    g_engine->previousButtons = held;

    storm::InputState player;
    player.moveX = g_engine->moveX.load();
    player.moveY = g_engine->moveY.load();
    player.attack = (pressed & InputBits::Attack) != 0;
    player.chakra = (pressed & InputBits::Chakra) != 0;
    player.guard = (pressed & InputBits::Guard) != 0;
    player.jump = (pressed & InputBits::Jump) != 0;
    player.dash = (pressed & InputBits::Dash) != 0;

    g_engine->accumulator += dt;
    int steps = 0;
    while (g_engine->accumulator >= storm::kFixedDt && steps < 4) {
        storm::InputState cpu =
            storm::cpuThink(g_engine->world, 1, g_engine->seed, g_engine->guardLatch);
        g_engine->world.step(player, cpu);
        g_engine->scene.update(storm::kFixedDt, g_engine->world);
        g_engine->accumulator -= storm::kFixedDt;
        ++steps;
        // Edge-triggered buttons only fire on the first simulated step.
        player.attack = false;
        player.chakra = false;
        player.jump = false;
        player.dash = false;
    }
    if (steps == 0) {
        g_engine->scene.update(0.0f, g_engine->world);
    }

    const float aspect = static_cast<float>(g_engine->surfaceWidth) /
                         static_cast<float>(g_engine->surfaceHeight > 0 ? g_engine->surfaceHeight : 1);
    g_engine->scene.build(g_engine->world, g_engine->perf, aspect,
                          static_cast<float>(g_engine->elapsed), g_engine->frame);
    g_engine->renderer.render(g_engine->frame);
}

JNIEXPORT jstring JNICALL
Java_com_sky_stormrev_NativeBridge_stats(JNIEnv* env, jobject /*thiz*/) {
    char buffer[320];
    if (!g_engine || !g_engine->ready) {
        std::snprintf(buffer, sizeof(buffer), "{\"ready\":false}");
        return env->NewStringUTF(buffer);
    }
    int phase = 0;
    if (g_engine->world.phase() == storm::MatchPhase::Finished) {
        const int winner = g_engine->world.winner();
        phase = winner == 0 ? 1 : (winner == 1 ? 2 : 3);
    }
    std::snprintf(
        buffer, sizeof(buffer),
        "{\"ready\":true,\"hp0\":%.3f,\"hp1\":%.3f,\"ck0\":%.3f,\"ck1\":%.3f,"
        "\"fps\":%.1f,\"scale\":%.2f,\"tier\":%d,\"phase\":%d,\"time\":%.1f,"
        "\"draws\":%d,\"rw\":%d,\"rh\":%d,\"thermal\":%s,\"celsius\":%.1f}",
        g_engine->world.fighter(0).hpFraction(), g_engine->world.fighter(1).hpFraction(),
        g_engine->world.fighter(0).chakraFraction(), g_engine->world.fighter(1).chakraFraction(),
        g_engine->perf.averageFps(), g_engine->perf.resolutionScale(),
        g_engine->perf.qualityTier(), phase, g_engine->world.timeLeft(),
        g_engine->renderer.drawCalls(), g_engine->renderer.renderWidth(),
        g_engine->renderer.renderHeight(), g_engine->perf.thermalCapped() ? "true" : "false",
        g_engine->thermalCelsius.load());
    return env->NewStringUTF(buffer);
}

}  // extern "C"
