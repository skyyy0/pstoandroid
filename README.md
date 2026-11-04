# pstoandroid — Storm Revolution di Android

Porting **Naruto Shippuden: Ultimate Ninja Storm Revolution (PS3)** ke Android
lewat jalur *native ARM64 + pipeline konversi aset*, bukan emulasi PS3.

Repo ini berisi empat bagian yang bisa diuji terpisah:

| lapisan | isi | status |
| --- | --- | --- |
| `tools/stormtools` | toolchain Python: baca `data.cpk`, scan `*.xfbin`, pack glTF → `.smesh`/`.sanm`, generate aset demo | 8 test lulus |
| `native/` | engine C++17 portabel: loader, skinning, animator, duel 60 Hz, AI, kamera, perf governor | 3.775 cek host lulus |
| `native/src/render` | renderer GLES 3: toon ramp 3 band, outline, rim, bayangan kontak, dynamic resolution | belum diuji di GPU |
| `android/` | shell Kotlin: GLSurfaceView, kontrol sentuh, HUD FPS + suhu chipset, Gradle | build hanya di CI/Android Studio |

Aset retail (karakter, animasi, audio, tekstur) **tidak** disertakan. Yang ada di
`android/app/src/main/assets/storm/` adalah aset demo prosedural orisinal supaya
engine, HUD, dan build APK bisa dijalankan tanpa file game.

## Mulai cepat

```bash
# 1. test toolchain aset
cd tools && python3 -m unittest discover -s tests

# 2. test engine tanpa GPU (Linux/macOS/WSL)
g++ -std=c++17 -O2 -I native/include \
    native/src/asset.cpp native/src/animation.cpp native/src/game.cpp \
    native/src/ai.cpp native/src/perf.cpp native/src/scene.cpp \
    native/tests/host_tests.cpp -o build/host_tests
./build/host_tests android/app/src/main/assets

# 3. build APK (butuh JDK 17 + Android SDK/NDK; bisa juga lewat GitHub Actions)
cd android && gradle :app:assembleRelease
```

APK hasil build: `android/app/build/outputs/apk/release/app-release.apk`
(arm64-v8a, `minSdk 26`).

## Kontrol

| aksi | kontrol |
| --- | --- |
| gerak | stik kiri (muncul di mana pun Anda menekan sisi kiri) |
| serangan | `ATK` |
| chakra burst | `CHK` |
| guard | `GRD` (tahan) |
| lompat | `JMP` |
| dash | `DSH` |
| rematch | tombol setelah K.O. |

HUD kiri atas menampilkan **FPS aktual**, **suhu chipset** (sensor SoC bila
terbaca, jika tidak sensor baterai), status termal platform, skala resolusi,
tier kualitas, jumlah draw call, dan resolusi render. Nilai suhu yang sama
dipakai `PerfGovernor` untuk menurunkan resolusi/tier dan akhirnya mengunci 30
fps saat perangkat panas.

## Pipeline aset

```
data.cpk ──stormtools cpk──▶ *.xfbin
        ──XFBIN importer + Blender──▶ .glb
        ──stormtools pack──▶ .smesh / .sanm + manifest.txt
        ──▶ android/app/src/main/assets/storm/
```

Detail format dan langkah Blender: `docs/ASSET_PIPELINE.md`.

## Build & CI

- `docs/BUILD.md` — build lokal, signing, NDK, troubleshooting.
- `.github/workflows/android.yml` — test toolchain + engine, build APK rilis,
  rilis otomatis untuk tag `v*`.
- `docs/GITHUB_ACTIONS_STORAGE.md` — kebijakan hemat kuota artifact (artefak
  tidak diunggah pada build biasa, retensi 1 hari untuk unggahan manual,
  distribusi lewat GitHub Releases, pruning otomatis).

## Batas kejujuran proyek ini

- Emulator PS3 di Android (RPCS3 belum punya build Android; aPS3e/RPCSX butuh
  Snapdragon 8 Gen 2+ dan RAM 12 GB) tidak dipakai. Lihat `docs/FEASIBILITY.md`.
- Renderer belum pernah dijalankan di perangkat nyata. `docs/ROADMAP.md`
  mencantumkan langkah validasi GPU pertama.
- Runtime **belum** memutar audio, belum memakai ASTC, dan belum punya shadow
  map. Semua itu ada di roadmap dengan urutan yang jelas.
- Nama, karakter, dan aset Naruto adalah milik Bandai Namco / CyberConnect2.
  Repo tidak mendistribusikannya. Lihat `docs/LEGAL.md`.

Dibuat oleh **sky**.
