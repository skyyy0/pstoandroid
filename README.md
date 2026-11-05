# pstoandroid — Storm Revolution di Android

Porting **Naruto Shippuden: Ultimate Ninja Storm Revolution (PS3)** ke Android
lewat jalur *native ARM64 + pipeline konversi aset*, bukan emulasi PS3.

Repo ini berisi empat bagian yang bisa diuji terpisah:

| lapisan | isi | status |
| --- | --- | --- |
| `tools/stormtools` | toolchain Python: baca `data.cpk`, scan `*.xfbin`, pack glTF → `.smesh`/`.sanm`, generate aset demo | 8 test lulus |
| `native/` | engine C++17 portabel: loader, skinning, animator, duel 60 Hz, AI, kamera, perf governor | 3.775 cek host lulus |
| `native/src/render` | renderer GLES 3: toon ramp 3 band, outline, rim, bayangan kontak, dynamic resolution berbasis viewport | lolos smoke test emulator (SwiftShader) di CI |
| `android/` | shell Kotlin: GLSurfaceView, kontrol sentuh, HUD FPS + suhu chipset, Gradle | build hanya di CI/Android Studio |

Aset retail (karakter, animasi, audio, tekstur) **tidak** disertakan. Yang ada di
`android/app/src/main/assets/storm/` adalah aset demo prosedural orisinal supaya
engine, HUD, dan build APK bisa dijalankan tanpa file game.

Loading screen aplikasi menampilkan credit porter: **SKY** — engine, renderer,
dan pipeline build dikerjakan oleh sky.

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

## Performa di HP entry-level (mis. Snapdragon 685 / Adreno 610)

Tiga lapis yang membuat frame tetap rata tanpa drop:

1. **Profil perangkat otomatis.** Core, RAM class, dan nama GPU dibaca saat init.
   Adreno di bawah 640, Mali-G5x, dan PowerVR dianggap entry-level: mulai dari
   skala render 0.72 (bukan native), batas bawah 0.40, evaluasi lebih sering.
2. **Governor berjenjang.** Resolusi dulu → tier → target fps 30 saat termal
   tinggi. Tier: 0 toon polos, 1 +outline, 2 +blob shadow, 3 +rim/specular.
   Ada cooldown setelah turun kualitas supaya tidak osilasi (osilasi = stutter
   walau rata-rata FPS terlihat bagus).
3. **Nol realokasi saat adaptasi.** FBO dialokasikan sekali seukuran surface;
   perubahan skala hanya menggeser viewport + area blit. Bone pose diunggah
   sekali per frame, bukan dua kali (pass outline + warna).

HUD kiri atas menampilkan FPS, suhu, skala, tier, draw call, dan resolusi render
supaya angka di HP sungguhan bisa dibandingkan langsung.

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

### Trik CI: hemat memori, build cepat, kuota gratis aman

Akun GitHub Free punya kuota **Actions storage ±500 MB** (artifact + package),
plus batas menit build. Repo ini sengaja "ngakalin" CI supaya tidak menghabiskan
keduanya — dan supaya build selesai cepat:

| trik | kenapa |
| --- | --- |
| build biasa **tidak** mengunggah artifact | artifact adalah penyebab utama kuota 500 MB habis; build push/PR hanya memverifikasi compile |
| artifact hanya saat `workflow_dispatch` (`upload_artifact`, default `false`) + retensi **1 hari** | kalau butuh APK untuk debugging, tetap dibatasi |
| distribusi lewat **GitHub Release** untuk tag `v*` | aset Release tidak dihitung sebagai artifact storage |
| `concurrency` + `cancel-in-progress` | commit beruntun membatalkan run lama, bukan menumpuk antrean |
| `paths-ignore: docs/**, **/*.md` | commit dokumentasi tidak memicu build Android sama sekali |
| satu ABI (`arm64-v8a`), tanpa matrix | setengah ukuran native payload, setengah waktu build; emulator memakai override `-Pstorm.abi=x86_64` |
| R8 + `shrinkResources` + `debugSymbolLevel = "none"` | APK lebih kecil, upload/unduh lebih cepat |
| `gradle --no-daemon`, heap **2 GB** (`android/gradle.properties`) | runner hanya punya ±7 GB RAM; daemon + heap besar membuat OOM/killer |
| cache **hanya** Gradle (`gradle/actions/setup-gradle`) | cache punya kuota terpisah; NDK/SDK penuh (ratusan MB) tidak di-cache karena cepat basi dan memakan kuota |
| smoke test emulator **tidak** jalan di PR maupun di build tag | boot emulator ±6–10 menit; PR cukup compile + host test, dan build tag mengemas commit yang sudah di-smoke di `main` |
| job `tests` → `apk`/`smoke` paralel | gerbang cepat dulu, build berat berjalan bersamaan |
| `7z -mx=9 -mmt=2` hanya untuk transfer | `.so` disimpan uncompressed di APK, jadi 7z yang mengecilkan; `-mmt=2` membatasi CPU runner |

Ringkasnya: **nol byte artifact** untuk build harian, build hanya jalan saat ada
perubahan kode, dan pekerjaan terberat (emulator) di-skip di PR dan build tag.
Detail lengkap, hitungan kuota, dan cara pruning: `docs/GITHUB_ACTIONS_STORAGE.md`.

### Rilis versi bebas (lewat tag)

Tidak perlu unggah artifact sama sekali: satu tag menghasilkan GitHub Release
berisi APK, `.apk.7z`, dan `SHA256SUMS.txt`.

```bash
git tag v1.0.0-free
git push origin v1.0.0-free
```

Workflow berjalan ±4 menit (tests + APK, tanpa emulator) lalu menerbitkan
Release. Agar hemat kuota, jangan push tag untuk commit yang belum pernah lolos
smoke di `main`; aset Release sendiri tidak dihitung ke kuota 500 MB.

## Batas kejujuran proyek ini

- Emulator PS3 di Android (RPCS3 belum punya build Android; aPS3e/RPCSX butuh
  Snapdragon 8 Gen 2+ dan RAM 12 GB) tidak dipakai. Lihat `docs/FEASIBILITY.md`.
- Renderer sudah boot dan render di emulator CI (SwiftShader, GLES 3.0), tetapi
  belum diukur di perangkat fisik. Angka FPS di HP sungguhan (mis. Snapdragon
  685) masih perlu diambil; `docs/ROADMAP.md` mencantumkan langkah validasinya.
- Runtime **belum** memutar audio, belum memakai ASTC, dan belum punya shadow
  map. Semua itu ada di roadmap dengan urutan yang jelas.
- Nama, karakter, dan aset Naruto adalah milik Bandai Namco / CyberConnect2.
  Repo tidak mendistribusikannya. Lihat `docs/LEGAL.md`.

Dibuat oleh **sky**.
