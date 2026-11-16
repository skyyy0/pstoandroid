# Roadmap

Targetnya satu: menjalankan konten **Storm Revolution asli** di Android. Setiap
fase punya kriteria terima yang bisa diperiksa, bukan sekadar daftar ide. Status
implementasi saat ini ada di `docs/AUDIT.md`.

## P0 — Fondasi engine (selesai)

- engine C++17 portabel + renderer GLES 3, governor performa, 3.782 cek host;
- toolchain Python (CPK/UTF, CRILAYLA, XFBIN/NUCC, scan, pack), 21 test;
- APK arm64, HUD FPS + suhu chipset, CI tanpa penumpukan artifact, rilis via tag.

Aset duel 60 Hz + AI di `game.cpp`/`ai.cpp` adalah **harness uji**, bukan target
produk. Kode itu dipertahankan karena menjadi tes regresi skinning/kamera/HUD.

## P1 — Validasi GPU di perangkat fisik (berikutnya)

Tujuan: membuktikan renderer benar di HP nyata sebelum menambah konten.

- jalankan APK di minimal 3 perangkat: entry (SD 6xx/7xx), mid (SD 778G),
  flagship (SD 8 Gen 2);
- rekam: fps p50/p95, resolusi efektif, suhu setelah 10 menit, RAM;
- perbaiki bug shader/VAO/tekstur yang hanya muncul di driver Mali/Adreno;
- kalibrasi ulang `PerfConfig` (ambang downshift, thermalFramesBeforeCap).

Kriteria terima: 60 fps stabil 10 menit di mid-range pada skala ≥ 0.75, tanpa
crash, suhu < 70 °C dengan casing normal.

## P2 — Container retail (selesai sebagian)

Sudah: UTF/CPK, CRILAYLA (dengan validasi), XFBIN/NUCC (header, indeks chunk,
ekstraksi). Belum: validasi terhadap `data.cpk` retail.

- jalankan `stormtools retail unpack` pada `data.cpk` asli, mulai dari
  `--only chara --ext .xfbin --limit 20`;
- periksa `report.json`: jumlah chunk per berkas, tipe yang muncul, peringatan
  `map_index`/`align`;
- perbaiki layout yang meleset **berdasarkan data**, bukan dengan melonggarkan
  validator;
- tambahkan contoh sintetis untuk setiap kasus yang ditemukan.

Kriteria terima: untuk 20 berkas karakter, tidak ada `failed`, setiap model
menghasilkan chunk `nuccChunkModel` dengan ukuran masuk akal, dan tipe tekstur
serta animasi ikut terdaftar.

## P3 — Importer payload retail

Ini fase penentu: tanpa parser payload, aset retail tetap biner.

- NUD (`NDP3`): vertex buffer, indeks, submesh, bone/skeleton, bounding box;
- NUT (`NTP3`/GIDX): header tekstur, format (DXT/BC, RGBA), mipmap;
- ANM retail: track tulang per clip, termasuk curve/sampling;
- material: pemetaan `nuccMaterial` → `MaterialData` engine (albedo, rim,
  specular, alpha cutoff);
- konversi ke `.smesh`/`.sanm` + manifest, langsung ke direktori `port/` perangkat.

Kriteria terima (harus dibuktikan dengan log + tangkapan layar build tersebut):
satu karakter retail tampil dengan tekstur dan animasi idle, satu stage retail
tampil, tanpa crash; log mencantumkan jumlah vertex/indeks/tekstur/track yang
dimuat.

## P4 — Perilaku dan antarmuka dari data retail

- state pertarungan dari moveset/param retail (bukan konstanta di `game.cpp`);
- kamera retail (termasuk camera animation dari xfbin);
- HUD pertarungan, character select, menu pause;
- script/misi (`nuccChunkBinary`, XML internal) untuk alur single player.

Kriteria terima: satu pertarungan 99 detik berjalan dengan aturan retail (guard,
substitution, awakening) dan HUD asli, tanpa ada parameter gameplay yang
di-hardcode.

## P5 — VFX dan audio

- partikel, afterimage, efek jutsu, bloom hemat untuk tier atas;
- mixer ringan (miniaudio/AAudio), 48 kHz, voice limit 24;
- konversi ADX/HCA → Opus di toolchain; sinkronisasi VO/impact dengan frame.

Kriteria terima: efek pukulan sinkron ±30 ms, tidak ada stutter saat 20 suara.

## P6 — Ukuran & distribusi

- ASTC 4x4/6x6 di packer + renderer (fallback RGBA8 untuk GPU lama);
- loader content pack `zstd` + unduhan bertahap (bootstrap APK tanpa aset);
- kuantisasi mesh 16-bit, keyframe reduction;
- verifikasi bahwa APK distribusi tetap nol byte aset retail.

Kriteria terima: konten 2 GB terpasang ≤ 1,2 GB tanpa penurunan kualitas yang
terlihat pada jarak main normal; unduhan awal ≤ 100 MB.

## P7 — Poles

- shadow map cascade ringan untuk tier 3;
- post-processing hemat: bloom half-res, color grading LUT;
- pengaturan grafis, remap tombol, skala UI, mode 30/60 fps;
- save data & stats.
