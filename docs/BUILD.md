# Build

## Yang dibutuhkan

| alat | versi | catatan |
| --- | --- | --- |
| JDK | 17 | AGP 8.5.2 |
| Android SDK | platform 34, build-tools 34.0.0 | `sdkmanager` |
| Android NDK | 26.1.10909125 | dipakai `native/CMakeLists.txt` |
| CMake | 3.22.1 | diinstal AGP bila belum ada |
| Gradle | 8.7 | `gradle/actions/setup-gradle` di CI |
| Python | 3.10+ | hanya untuk toolchain aset/test |

Tidak perlu Android Studio, tapi project bisa dibuka langsung (`android/`).

## Build APK

```bash
cd android
gradle :app:assembleRelease
# hasil: app/build/outputs/apk/release/app-release.apk
```

Tanpa keystore, build release memakai debug signing supaya tetap bisa
`adb install`. Untuk signature stabil:

```bash
gradle :app:assembleRelease \
  -Pstorm.storeFile=/path/keystore.jks \
  -Pstorm.storePassword=... \
  -Pstorm.keyAlias=storm \
  -Pstorm.keyPassword=...
```

Pasang:

```bash
adb install -r app/build/outputs/apk/release/app-release.apk
adb logcat -s StormPort
```

## Signing di CI

Workflow memakai empat secret opsional:

| secret | isi |
| --- | --- |
| `STORM_KEYSTORE_BASE64` | `base64 -w0 keystore.jks` |
| `STORM_STORE_PASSWORD` | password keystore |
| `STORM_KEY_ALIAS` | alias kunci |
| `STORM_KEY_PASSWORD` | password kunci |

Tanpa secret tersebut, CI membuat keystore sementara. Build tetap installable,
tetapi update berikutnya harus di-uninstall dulu karena signature berbeda.

## Test

```bash
# toolchain aset
cd tools && python3 -m unittest discover -s tests

# engine (tanpa GPU)
mkdir -p build && g++ -std=c++17 -O2 -I native/include \
  native/src/asset.cpp native/src/animation.cpp native/src/game.cpp \
  native/src/ai.cpp native/src/perf.cpp native/src/scene.cpp \
  native/tests/host_tests.cpp -o build/host_tests
./build/host_tests android/app/src/main/assets

# CMake (opsional)
cmake -S native -B build/native -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build/native -j
ctest --test-dir build/native --output-on-failure
```

## Rilis

```bash
git tag v0.1.0
git push origin v0.1.0
```

`android.yml` akan menjalankan test, membangun APK, membuat `*.apk.7z`, dan
membuat GitHub Release. Artifact Actions tidak dipakai (lihat
`GITHUB_ACTIONS_STORAGE.md`).

## Troubleshooting

| gejala | penyebab umum | solusi |
| --- | --- | --- |
| layar hitam, log "native init failed" | aset tidak ada / manifest salah | cek `android/app/src/main/assets/storm/manifest.txt`, `adb logcat -s StormPort` |
| "Menyiapkan engine…" terus | `NativeBridge.init` gagal | lihat log; pastikan `stormjni` ter-load |
| crash saat start | GLES 3 tidak tersedia | perangkat wajib `glEsVersion 0x00030000` |
| 20–30 fps di HP murah | resolusi penuh | governor akan turun; cek HUD `scale`/`tier`; suhu > 72 °C mengunci 30 fps |
| `UnsatisfiedLinkError` | ABI tidak cocok | hanya `arm64-v8a`; emulator x86 tidak didukung |
| Gradle gagal `NDK not configured` | NDK belum ada | `sdkmanager "ndk;26.1.10909125"` |
| APK tidak terpasang | signature/target SDK | `adb install -r`, cek `minSdk 26` |
