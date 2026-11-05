# Strategi hemat kuota artifact GitHub Actions

Dokumen ini menjawab satu masalah konkret: **akun GitHub Free dipakai bersama
beberapa repo, dan kuota artifact-nya kecil.** Build pstoandroid tidak boleh
menghabiskannya.

## 1. Aturan dasar yang dipakai repo ini

| aturan | implementasi | efek |
| --- | --- | --- |
| Build biasa tidak mengunggah artifact | `android.yml` hanya `assembleRelease`; tidak ada `upload-artifact` di jalur push/PR | 0 byte artifact per build |
| Artifact bersifat opt-in | input `upload_artifact` pada `workflow_dispatch` (default `false`) | hanya saat debugging |
| Retensi minimum | `retention-days: 1` (batas terendah GitHub) | artifact hilang sendiri besok |
| Tanpa kompresi ulang | `compression-level: 0` untuk `.7z` yang sudah padat | upload cepat, ukuran tidak membengkak |
| Distribusi lewat Releases | job membuat GitHub Release untuk tag `v*` | aset Release **tidak** dihitung sebagai artifact storage |
| Run tidak menumpuk | `concurrency: android-${{ github.ref }}` + `cancel-in-progress: true` | commit berturut-turut membatalkan run lama |
| Pruning otomatis | `prune-artifacts.yml` harian, hapus artifact > 1 hari | jaring pengaman bila retensi terlewat |
| Payload native minimal | `abiFilters = arm64-v8a`, R8, `debugSymbolLevel = "none"`, `.so` di-strip | APK lebih kecil sejak awal |
| Cache terpisah | hanya Gradle cache lewat `gradle/actions/setup-gradle` | cache punya kuota sendiri (10 GB/repo) dan di-evict setelah 7 hari tidak dipakai |

Artinya: **pstoandroid tidak pernah menyimpan APK di artifact storage kecuali
Anda memintanya secara manual**, dan kalaupun diminta, maksimal 1 hari.

## 2. Kenapa ini penting (hitungan kuota)

Kuota GitHub Free kurang lebih 500 MB untuk Actions storage + Packages
(angka dapat berubah; cek *Settings → Billing*). Artifact dihitung selama masih
disimpan.

Contoh tanpa kebijakan di atas, APK 8 MB + 7z 6 MB, 20 build/bulan, retensi
default 90 hari:

```
20 build × 14 MB = 280 MB tersimpan, dan belum tentu terhapus
```

Dengan kebijakan di atas:

```
build biasa        : 0 MB
unggahan manual    : 14 MB, hidup 1 hari, maksimal beberapa file
tag/release        : 0 MB artifact (masuk Releases, bukan Actions storage)
```

## 3. Kompresi hasil build

APK adalah ZIP. Mengompres ulang ZIP hampir tidak menghasilkan apa-apa, **kecuali**
untuk file yang disimpan tanpa kompresi. Di APK ini, `.so` native sengaja
disimpan uncompressed (`useLegacyPackaging = false`) supaya bisa di-*mmap* saat
load, jadi di situlah keuntungan besarnya.

Workflow memakai 7z LZMA2:

```bash
7z a -t7z -mx=9 -mmt=2 dist/stormrev.apk.7z dist/stormrev.apk
```

Perkiraan rasio untuk build saat ini (APK ±4–8 MB, mayoritas `.so` + Kotlin):

| metode | perkiraan ukuran | catatan |
| --- | --- | --- |
| APK apa adanya | 100% | langsung bisa `adb install` |
| `7z -mx=9` | 55–75% | terbaik untuk `.so`; butuh ekstrak dulu |
| `zstd --ultra -22` | 60–80% | dekompresi jauh lebih cepat, cocok untuk konten besar |
| `xz -9` | 55–75% | lambat, tidak lebih baik dari 7z+LZMA2 |

Untuk APK berisi 2 GB aset, rasio 7z akan mendekati 1:1 pada tekstur yang sudah
dikompresi. Di situ kompresi transfer bukan lagi alat utama — lihat bagian 5.

Batas praktis: satu aset Release maksimum 2 GB. Jika arsip melebihi itu, pecah:
`7z a -v1900m ...` lalu unggah semua volume.

## 4. Di mana hasil build sebaiknya diletakkan

| tujuan | tempat | kuota |
| --- | --- | --- |
| verifikasi compile di PR | tidak diunggah | 0 |
| debugging manual | Actions artifact, retensi 1 hari | kecil, sementara |
| build yang dibagikan | **GitHub Release** | tidak dihitung artifact storage |
| distribusi massal | Play Store (AAB) / situs sendiri | di luar GitHub |

Karena itu `android.yml` punya dua jalur: build (selalu) dan publish
(hanya untuk tag). Untuk merilis:

```bash
git tag v0.1.0 && git push origin v0.1.0
```

Release akan berisi `*.apk`, `*.apk.7z`, dan `SHA256SUMS.txt`.

## 5. Kalau aplikasi terpasang 2 GB: bagaimana membuat distribusinya jauh lebih kecil

Penting dipisahkan dua hal:

1. **Ukuran distribusi** (yang diunduh) — bisa jauh lebih kecil.
2. **Ukuran terpasang** (yang menempati penyimpanan setelah instalasi) — tidak
   bisa lebih kecil dari data yang harus dibaca GPU/CPU, kecuali format asetnya
   diganti.

### 5a. Rincian contoh 2 GB terpasang

| komponen | ukuran | bisa dikecilkan? |
| --- | --- | --- |
| tekstur | 1,1 GB | ya, ASTC 4x4/6x6 + dedupe + buang mip berlebih |
| audio | 0,35 GB | ya, Opus 48–64 kbps |
| mesh + animasi | 0,25 GB | ya, kuantisasi 16-bit + keyframe reduction |
| video cutscene | 0,15 GB | ya, AV1/HEVC |
| native lib + kode | 0,04 GB | sudah minimal (1 ABI, R8, strip) |
| data lain | 0,11 GB | sebagian |

Kalau semua langkah diterapkan, total terpasang realistis turun ke **±0,9–1,1 GB**
tanpa mengubah model, jumlah karakter, atau durasi animasi. Yang berubah hanya
representasi datanya, bukan isi game.

### 5b. Tiga pola distribusi

**Pola A — satu APK + 7z (paling sederhana).**
Terpasang 2 GB, unduhan ±1,6–1,9 GB. Sideload bisa, tapi APK mendekati batas
ZIP64/instalasi dan proses update mahal. Tidak disarankan untuk 2 GB.

**Pola B — bootstrap APK + content pack (disarankan untuk sideload).**
APK ±50 MB (engine + UI). Saat pertama dibuka, aplikasi mengunduh 1–3 pack
`*.zst` (masing-masing 300–600 MB) lalu men-decompress ke
`filesDir/content/`. Unduhan ±1,0–1,3 GB, terpasang tetap ±2 GB, dan pack bisa
diperbarui per arc tanpa mengunduh ulang semuanya. Ini yang paling cocok dengan
kebutuhan "distribusi jauh lebih kecil, kualitas sama".

**Pola C — Play Asset Delivery (AAB).**
Base module dibatasi 200 MB, sisa konten jadi asset pack *install-time* /
*fast-follow* / *on-demand*. Play yang mengompres dan mengirim; tidak ada
artifact GitHub sama sekali. Ini jalur yang benar bila targetnya Play Store.

### 5c. Yang **tidak** boleh diklaim

- Men-decompress saat instalasi tidak membuat ukuran terpasang lebih kecil.
  Data harus tetap ada di disk.
- "Kompresi tinggi" pada tekstur yang sudah terkompresi (PNG/JPEG) tidak
  menghasilkan rasio besar. Yang benar-benar mengecilkan adalah **format GPU
  native (ASTC)** dan **codec audio modern (Opus)**.
- Menghapus aset untuk mengecilkan ukuran = mengurangi kualitas; tidak dipakai.

## 6. Status implementasi di repo ini

Sudah ada:

- kebijakan CI di atas (tanpa artifact default, retensi 1 hari, prune harian,
  Release untuk tag);
- 7z LZMA2 pada jalur build;
- APK arm64-only, R8 + resource shrinking, symbol native dibuang;
- packer menolak rig > 128 bone (gagal di CI, bukan di HP).

Belum ada (roadmap, lihat `ROADMAP.md`):

- loader content pack `zstd` + unduhan bertahap (Pola B);
- import ASTC di `stormtools` dan di renderer (butuh ekstensi
  `GL_KHR_texture_compression_astc_ldr`, tersedia di hampir semua GPU 2016+);
- audio Opus (saat ini runtime belum memutar audio);
- AAB + Play Asset Delivery.

## 7. Perawatan kuota untuk repo lain di akun yang sama

Artifact hanya bisa dihapus per repo. Untuk repo lain, jalankan:

```bash
# daftar artifact yang masih hidup
gh api --paginate "repos/OWNER/REPO/actions/artifacts?per_page=100" \
  --jq '.artifacts[] | "\(.id) \(.name) \(.size_in_bytes) \(.created_at)"'

# hapus satu artifact
gh api -X DELETE "repos/OWNER/REPO/actions/artifacts/ID"

# bersihkan cache repo (kuota cache terpisah, 10 GB)
gh cache delete --all --repo OWNER/REPO
```

Atau salin `prune-artifacts.yml` ke repo tersebut; satu baris `repository`
default ke repo tempat workflow berjalan, jadi tidak perlu token tambahan.

## 8. Jebakan yang sudah dihindari

- **Retensi 0 hari** tidak valid; minimum 1.
- **Artifact dari PR fork** tetap dihitung; karena itu tidak ada upload di PR.
- **Cache Gradle** bukan artifact storage, tetapi tetap ada batasnya; jangan
  menambahkan cache NDK/SDK penuh (ratusan MB, cepat basi).
- **Menyimpan APK debug** dua kali (debug + release) menggandakan biaya; CI
  hanya membuat release.
- **`actions/upload-artifact` v3** sudah dihentikan; workflow memakai v4.
- **Matrix build** memperbanyak artifact; di sini hanya satu ABI, satu job.
- **Komentar `#` di dalam block scalar YAML (`>` atau `|`) adalah isi, bukan
  komentar.** Satu komentar yang terselip di `emulator-options` membuat emulator
  menerima argumen nyasar dan boot menggantung ±38 menit sampai run dibatalkan;
  catatan panjang ditaruh di atas step, bukan di dalam nilai.
- **`adb exec-out screencap` bisa menggantung di SwiftShader.** Screenshot
  bersifat diagnostik dan dibatasi `timeout 45`, sehingga kegagalannya tidak
  pernah menahan job yang sebenarnya membuktikan engine jalan (assertion
  `engine ready` di logcat).
