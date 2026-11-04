// Host-side tests for everything that does not need a GPU: package loading,
// skinning/animation, the fixed-step duel simulation, the camera and the
// adaptive performance governor.  Run by CI and locally with:
//
//     g++ -std=c++17 -O2 -I native/include native/src/*.cpp \
//         native/tests/host_tests.cpp -o build/host_tests && ./build/host_tests
#include <cmath>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

#include "storm/animation.h"
#include "storm/asset_source.h"
#include "storm/game.h"
#include "storm/perf.h"
#include "storm/scene.h"

namespace {

int g_failures = 0;
int g_checks = 0;

#define CHECK(condition)                                                                  \
    do {                                                                                  \
        ++g_checks;                                                                       \
        if (!(condition)) {                                                               \
            std::printf("  FAIL %s:%d: %s\n", __FILE__, __LINE__, #condition);            \
            ++g_failures;                                                                 \
        }                                                                                 \
    } while (0)

#define CHECK_NEAR(a, b, tolerance)                                                       \
    do {                                                                                  \
        ++g_checks;                                                                       \
        const double _va = (a);                                                           \
        const double _vb = (b);                                                           \
        if (!(std::fabs(_va - _vb) <= (tolerance))) {                                     \
            std::printf("  FAIL %s:%d: %s (%.5f) != %s (%.5f)\n", __FILE__, __LINE__, #a, \
                        _va, #b, _vb);                                                    \
            ++g_failures;                                                                 \
        }                                                                                 \
    } while (0)

bool isFinite(const storm::Mat4& matrix) {
    for (float value : matrix.m) {
        if (!std::isfinite(value)) return false;
    }
    return true;
}

bool isFinite(const storm::Vec3& value) {
    return std::isfinite(value.x) && std::isfinite(value.y) && std::isfinite(value.z);
}

std::string readText(const std::string& path) {
    std::ifstream stream(path, std::ios::binary);
    std::ostringstream buffer;
    buffer << stream.rdbuf();
    return buffer.str();
}

void testMath() {
    std::printf("math\n");
    const storm::Mat4 identity = storm::Mat4::identity();
    const storm::Mat4 translation = storm::Mat4::translation({1.0f, 2.0f, 3.0f});
    const storm::Vec3 point = (translation * identity).transformPoint({0.0f, 0.0f, 0.0f});
    CHECK_NEAR(point.x, 1.0f, 1e-5);
    CHECK_NEAR(point.y, 2.0f, 1e-5);
    CHECK_NEAR(point.z, 3.0f, 1e-5);

    const storm::Quat quarter = storm::Quat::fromAxisAngle({0, 1, 0}, storm::kPi * 0.5f);
    const storm::Vec3 rotated = quarter.rotate({0, 0, 1});
    CHECK_NEAR(rotated.x, 1.0f, 1e-4);
    CHECK_NEAR(rotated.z, 0.0f, 1e-4);

    const storm::Quat halfway = storm::slerp(storm::Quat::identity(), quarter, 0.5f);
    CHECK_NEAR(halfway.length(), 1.0f, 1e-5);

    const storm::Mat4 view = storm::lookAt({0, 0, 5}, {0, 0, 0}, {0, 1, 0});
    const storm::Vec3 eyeSpace = view.transformPoint({0, 0, 0});
    CHECK_NEAR(eyeSpace.z, -5.0f, 1e-4);

    const storm::Mat4 composed = storm::Mat4::translation({2, 0, 0}) * storm::Mat4::scale(2.0f);
    const storm::Vec3 scaled = composed.transformPoint({1, 0, 0});
    CHECK_NEAR(scaled.x, 4.0f, 1e-5);

    const storm::Mat4 inverse = storm::inverseAffine(composed);
    const storm::Vec3 roundTrip = inverse.transformPoint(scaled);
    CHECK_NEAR(roundTrip.x, 1.0f, 1e-4);
    CHECK(isFinite(inverse));
}

void testManifest() {
    std::printf("manifest\n");
    storm::Manifest manifest;
    const std::string text =
        "# comment\n"
        "mesh fighter storm/fighter.smesh\n"
        "anim fighter idle storm/fighter_idle.sanm\n"
        "anim fighter attack storm/fighter_attack.sanm\n"
        "character rookie fighter 1.25\n"
        "arena dojo fighter\n"
        "nonsense line\n";
    CHECK(manifest.parse(text));
    CHECK(manifest.meshes.size() == 1);
    CHECK(manifest.animations["fighter"].size() == 2);
    CHECK_NEAR(manifest.characters["rookie"].scale, 1.25f, 1e-6);
    CHECK(manifest.characters["rookie"].mesh == "fighter");
    CHECK(manifest.arenas["dojo"] == "fighter");
    CHECK(manifest.warnings.size() == 1);
}

class Assets {
public:
    explicit Assets(const std::string& root) : root_(root) {}

    bool load(storm::Manifest& manifest) const {
        const std::string text = readText(root_ + "/storm/manifest.txt");
        return !text.empty() && manifest.parse(text);
    }
    storm::FileAssetSource source() const { return storm::FileAssetSource(root_); }
    const std::string& root() const { return root_; }

private:
    std::string root_;
};

void testPackages(const Assets& assets) {
    std::printf("packages\n");
    storm::Manifest manifest;
    CHECK(assets.load(manifest));
    storm::FileAssetSource source = assets.source();

    std::vector<uint8_t> bytes;
    CHECK(source.read("storm/fighter.smesh", bytes));
    storm::Mesh mesh;
    std::string error;
    CHECK(storm::parseMesh(bytes.data(), bytes.size(), mesh, error));
    CHECK(mesh.bones.size() == 17);
    CHECK(mesh.vertices.size() > 100);
    CHECK(mesh.indices.size() % 3 == 0);
    CHECK(!mesh.submeshes.empty());
    CHECK(mesh.height() > 1.5f);
    CHECK(mesh.boundsMin.y > -0.1f);
    CHECK_NEAR(mesh.height(), 1.87f, 0.25f);

    for (const storm::VertexData& vertex : mesh.vertices) {
        const int sum = vertex.weights[0] + vertex.weights[1] + vertex.weights[2] + vertex.weights[3];
        CHECK(sum == 255);
    }

    // Corrupt input must be rejected, never crash.
    std::vector<uint8_t> broken = bytes;
    broken[0] = 'X';
    storm::Mesh ignored;
    error.clear();
    CHECK(!storm::parseMesh(broken.data(), broken.size(), ignored, error));
    CHECK(!error.empty());
    CHECK(!storm::parseMesh(bytes.data(), 8, ignored, error));

    std::vector<uint8_t> clipBytes;
    CHECK(source.read("storm/fighter_run.sanm", clipBytes));
    storm::Clip clip;
    CHECK(storm::parseClip(clipBytes.data(), clipBytes.size(), clip, error));
    CHECK_NEAR(clip.duration, 1.0f, 0.01f);
    CHECK(!clip.tracks.empty());
    for (const storm::BoneTrack& track : clip.tracks) {
        CHECK(!track.keys.empty());
        for (const storm::Keyframe& key : track.keys) {
            CHECK_NEAR(key.rotation.length(), 1.0f, 1e-3);
        }
    }
}

void testAnimation(const Assets& assets) {
    std::printf("animation\n");
    storm::Manifest manifest;
    assets.load(manifest);
    storm::FileAssetSource source = assets.source();
    std::vector<uint8_t> bytes;

    storm::Mesh mesh;
    std::string error;
    source.read("storm/fighter.smesh", bytes);
    CHECK(storm::parseMesh(bytes.data(), bytes.size(), mesh, error));

    std::map<std::string, storm::Clip> clips;
    for (const char* name : {"idle", "run", "attack"}) {
        std::vector<uint8_t> clipBytes;
        const std::string path = "storm/fighter_" + std::string(name) + ".sanm";
        CHECK(source.read(path, clipBytes));
        storm::Clip clip;
        CHECK(storm::parseClip(clipBytes.data(), clipBytes.size(), clip, error));
        clips[name] = clip;
    }

    storm::Animator animator;
    animator.configure(mesh, clips);
    CHECK(animator.ready());
    CHECK(animator.play("idle", 0.0f, true));

    storm::Pose first;
    animator.evaluate(first);
    CHECK(first.boneCount() == mesh.bones.size());
    for (const storm::Mat4& matrix : first.world) CHECK(isFinite(matrix));

    for (int frame = 0; frame < 40; ++frame) animator.update(1.0f / 60.0f);
    storm::Pose later;
    animator.evaluate(later);
    float difference = 0.0f;
    for (size_t bone = 0; bone < later.world.size(); ++bone) {
        difference += std::fabs(later.world[bone].m[12] - first.world[bone].m[12]);
        difference += std::fabs(later.world[bone].m[13] - first.world[bone].m[13]);
    }
    CHECK(difference > 1e-4f);

    // Cross-fading to another clip must remain finite and keep the bone count.
    CHECK(animator.play("run", 0.15f, true));
    animator.update(0.05f);
    storm::Pose blended;
    animator.evaluate(blended);
    CHECK(blended.boneCount() == mesh.bones.size());
    for (const storm::Mat4& matrix : blended.world) CHECK(isFinite(matrix));
    CHECK(animator.play("does_not_exist") == false);
    CHECK(animator.finished() == false);

    // The root bone of the arena-style bind pose must stay at the origin.
    storm::Pose bind;
    animator.stop();
    animator.evaluate(bind);
    CHECK_NEAR(bind.skin[0].m[12], 0.0f, 1e-4);
    CHECK_NEAR(bind.skin[0].m[13], 0.0f, 1e-4);
}

void testSimulation() {
    std::printf("simulation\n");
    storm::World world;
    storm::MatchConfig config;
    world.configure(config);
    CHECK(world.phase() == storm::MatchPhase::Fighting);
    CHECK_NEAR(world.fighter(0).hp, 100.0f, 1e-5);
    CHECK_NEAR(world.timeLeft(), 99.0f, 1e-3);

    bool guardLatch = false;
    storm::InputState idle;
    int frames = 0;
    int damageFrames = 0;
    float lowestHp = 100.0f;
    while (world.phase() == storm::MatchPhase::Fighting && frames < 60 * 70) {
        const storm::Fighter& self = world.fighter(0);
        const storm::Fighter& opponent = world.fighter(1);
        const float dx = opponent.position.x - self.position.x;
        const float dz = opponent.position.z - self.position.z;
        const float distance = std::sqrt(dx * dx + dz * dz);

        storm::InputState player;
        if (distance > 2.0f) {
            player.moveY = 1.0f;
        } else {
            player.attack = true;
            if (frames % 47 == 0) player.chakra = true;
        }
        const storm::InputState cpu = storm::cpuThink(world, 1, 12345u, guardLatch);
        const float hpBefore = world.fighter(1).hp;
        world.step(player, cpu);
        if (world.fighter(1).hp < hpBefore) damageFrames += 1;
        lowestHp = std::min(lowestHp, world.fighter(1).hp);
        for (int i = 0; i < 2; ++i) {
            const storm::Fighter& fighter = world.fighter(i);
            CHECK(isFinite(fighter.position));
            CHECK(fighter.position.y >= 0.0f);
            CHECK(fighter.hp >= 0.0f && fighter.hp <= 100.0f);
            CHECK(fighter.chakra >= 0.0f && fighter.chakra <= 100.0f);
            const float radial = std::sqrt(fighter.position.x * fighter.position.x +
                                           fighter.position.z * fighter.position.z);
            CHECK(radial <= config.arenaRadius + 0.01f);
        }
        ++frames;
    }
    std::printf("  simulated %d frames, %d damaging frames, opponent hp %.1f\n", frames,
                damageFrames, lowestHp);
    CHECK(damageFrames > 0);
    CHECK(lowestHp < 99.0f);
    CHECK(world.phase() == storm::MatchPhase::Finished);
    CHECK(world.winner() == 0 || world.winner() == 1);
    if (world.winner() >= 0) {
        CHECK(world.fighter(1 - world.winner()).hp <= 0.01f);
        CHECK(world.fighter(world.winner()).hp > 0.0f);
    }

    // Deterministic replay: the same script must produce the same result.
    storm::World replay;
    replay.configure(config);
    bool latch = false;
    for (int frame = 0; frame < 600; ++frame) {
        storm::InputState player;
        player.attack = (frame % 25) < 6;
        player.moveY = (frame % 25) < 6 ? 0.0f : 1.0f;
        if (frame == 300) player.jump = true;
        replay.step(player, storm::cpuThink(replay, 1, 777u, latch));
    }
    storm::World replayAgain;
    replayAgain.configure(config);
    latch = false;
    for (int frame = 0; frame < 600; ++frame) {
        storm::InputState player;
        player.attack = (frame % 25) < 6;
        player.moveY = (frame % 25) < 6 ? 0.0f : 1.0f;
        if (frame == 300) player.jump = true;
        replayAgain.step(player, storm::cpuThink(replayAgain, 1, 777u, latch));
    }
    CHECK_NEAR(replay.fighter(0).position.x, replayAgain.fighter(0).position.x, 1e-5);
    CHECK_NEAR(replay.fighter(1).hp, replayAgain.fighter(1).hp, 1e-5);
}

void testCameraAndScene(const Assets& assets) {
    std::printf("scene\n");
    storm::Manifest manifest;
    CHECK(assets.load(manifest));
    storm::FileAssetSource source = assets.source();

    storm::Scene scene;
    std::string error;
    CHECK(scene.load(source, manifest, error));
    if (!error.empty()) std::printf("  load error: %s\n", error.c_str());
    CHECK(scene.ready());
    CHECK(scene.fighterMesh(0).bones.size() == 17);

    storm::World world;
    world.configure(storm::MatchConfig{});
    storm::PerfGovernor perf;
    storm::FrameView frame;

    for (int frameIndex = 0; frameIndex < 120; ++frameIndex) {
        storm::InputState player;
        player.moveY = 1.0f;
        if (frameIndex > 40) player.attack = frameIndex % 30 < 5;
        bool latch = false;
        world.step(player, storm::cpuThink(world, 1, 99u, latch));
        scene.update(storm::kFixedDt, world);
        perf.pushFrame(16.0f);
    }
    scene.build(world, perf, 16.0f / 9.0f, 2.0f, frame);
    CHECK(frame.items.size() == 3);
    if (frame.items.size() != 3) return;
    CHECK(frame.items[0].mesh == &scene.arenaMesh());
    CHECK(frame.items[0].castShadow == false);
    CHECK(frame.items[1].pose != nullptr);
    CHECK(frame.items[1].pose->boneCount() == scene.fighterMesh(0).bones.size());
    CHECK(isFinite(frame.viewProjection));
    CHECK(isFinite(frame.cameraPosition));
    CHECK(frame.hp[0] >= 0.0f && frame.hp[0] <= 1.0f);
    CHECK(frame.qualityTier >= 1 && frame.qualityTier <= 3);
    CHECK(frame.resolutionScale > 0.5f && frame.resolutionScale <= 1.0f);

    // The fighter must be in front of the camera (negative view-space depth).
    const storm::Vec3 cameraSpace = frame.view.transformPoint(world.fighter(0).position);
    CHECK(cameraSpace.z < 0.0f);

    // Arena + fighters are inside the frustum's near/far range.
    const storm::Vec3 clipPoint = frame.viewProjection.transformPoint(
        world.fighter(0).position + storm::Vec3{0.0f, 1.0f, 0.0f});
    CHECK(clipPoint.x > -8.0f && clipPoint.x < 8.0f);

    CHECK(scene.stateSummary(0) != "unloaded");
}

void testPerfGovernor() {
    std::printf("perf governor\n");
    storm::PerfGovernor governor;
    CHECK_NEAR(governor.resolutionScale(), 1.0f, 1e-5);
    CHECK(governor.qualityTier() == 3);

    for (int frame = 0; frame < 120; ++frame) governor.pushFrame(26.0f);
    const float dropped = governor.resolutionScale();
    std::printf("  after 120 slow frames: scale %.2f tier %d p95 %.1fms\n", dropped,
                governor.qualityTier(), governor.p95FrameMs());
    CHECK(dropped < 0.95f);
    CHECK(governor.averageFps() < 45.0f);
    CHECK(governor.p95FrameMs() > 20.0f);
    CHECK(governor.consumeResolutionChange());
    CHECK(!governor.consumeResolutionChange());

    for (int frame = 0; frame < 60; ++frame) governor.pushFrame(26.0f);
    CHECK(governor.qualityTier() <= 3);

    for (int frame = 0; frame < 400; ++frame) governor.pushFrame(7.0f);
    std::printf("  after 400 fast frames: scale %.2f tier %d p95 %.1fms\n",
                governor.resolutionScale(), governor.qualityTier(), governor.p95FrameMs());
    CHECK(governor.resolutionScale() > dropped);
    CHECK(governor.p95FrameMs() < 10.0f);
    CHECK(!governor.thermalCapped());

    // An unrecoverable 30 fps device ends up on the 30 fps pacing target.
    storm::PerfConfig slowConfig;
    slowConfig.thermalFramesBeforeCap = 240;
    slowConfig.minScale = 0.5f;
    storm::PerfGovernor slow(slowConfig);
    for (int frame = 0; frame < 3000; ++frame) slow.pushFrame(34.0f);
    std::printf("  thermal path: target %.0f fps, scale %.2f, tier %d\n", slow.targetFps(),
                slow.resolutionScale(), slow.qualityTier());
    CHECK(slow.thermalCapped());
    CHECK_NEAR(slow.targetFps(), 30.0f, 1e-4);
    CHECK(slow.resolutionScale() <= slowConfig.minScale + 1e-4f);
    CHECK(slow.qualityTier() >= slowConfig.minTier);

    // Platform thermal signal: hot chipset clamps quality immediately, cooling
    // restores the 60 fps pacing target.
    CHECK_NEAR(storm::thermalPressureFromCelsius(38.0f), 0.0f, 1e-6);
    CHECK_NEAR(storm::thermalPressureFromCelsius(61.0f), 0.5f, 1e-5);
    CHECK_NEAR(storm::thermalPressureFromCelsius(95.0f), 1.0f, 1e-6);
    storm::PerfGovernor hot;
    hot.setThermalPressure(storm::thermalPressureFromCelsius(88.0f));
    CHECK(hot.thermalCapped());
    CHECK_NEAR(hot.targetFps(), 30.0f, 1e-4);
    CHECK_NEAR(hot.resolutionScale(), hot.config().minScale, 1e-5);
    CHECK(hot.qualityTier() == hot.config().minTier);
    hot.setThermalPressure(storm::thermalPressureFromCelsius(40.0f));
    CHECK(!hot.thermalCapped());
    CHECK_NEAR(hot.targetFps(), 60.0f, 1e-4);

    governor.reset();
    CHECK_NEAR(governor.resolutionScale(), 1.0f, 1e-5);
    CHECK_NEAR(governor.thermalPressure(), 0.0f, 1e-6);
}

}  // namespace

int main(int argc, char** argv) {
    const std::string root = argc > 1 ? argv[1] : "android/app/src/main/assets";
    std::printf("storm host tests (assets: %s)\n", root.c_str());
    const Assets assets(root);

    testMath();
    testManifest();
    testPackages(assets);
    testAnimation(assets);
    testSimulation();
    testCameraAndScene(assets);
    testPerfGovernor();

    std::printf("\n%d checks, %d failure(s)\n", g_checks, g_failures);
    return g_failures == 0 ? 0 : 1;
}
