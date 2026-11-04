# Roadmap

Setiap fase punya kriteria terima yang bisa diperiksa, bukan sekadar daftar ide.

## P0 — Fondasi (selesai)

- toolchain `cpk`/`scan`/`pack`, 8 test Python lulus;
- engine C++ portabel + 3.775 cek host lulus;
- aset demo prosedural, APK arm64, HUD FPS + suhu chipset;
- CI tanpa penumpukan artifact, rilis via GitHub Releases.

## P1 — Validasi GPU pertama (berikutnya)

Tujuan: membuktikan renderer benar di perangkat nyata sebelum menambah konten.

- jalankan APK di minimal 3 perangkat: entry (SD 6xx/7xx), mid (SD 778G),
  flagship (SD 8 Gen 2);
- rekam: fps p50/p95, resolusi efektif, suhu setelah 10 menit, RAM;
- perbaiki bug shader/VAO/tekstur yang hanya muncul di driver Mali/Adreno;
- kalibrasi ulang `PerfConfig` (ambang downshift, thermalFramesBeforeCap).

Kriteria terima: 60 fps stabil 10 menit di mid-range pada skala ≥ 0.75, tidak ada
crash, suhu < 70 °C dengan casing normal.

## P2 — Kedalaman pertarungan

- chakra cost & cooldown, substitution, awakening, ultimate;
- guard break, knockdown get-up, air combo;
- 3 arena dengan batas dan kamera berbeda;
- CPU difficulty bertingkat;
- hitbox dari animation events, bukan konstanta.

Kriteria terima: duel 99 detik terasa seperti Storm (bukan beat'em up), dan
simulasi tetap deterministik (replay test lulus 10.000 frame).

## P3 — Pipeline aset retail

- Blender XFBIN importer terdokumentasi langkahnya;
- dukungan tekstur non-albedo (normal/emissive) dan material multi-tekstur;
- import stage geometry + collision;
- validasi otomatis: bone ≤ 96, indeks, ukuran tekstur.

Kriteria terima: satu karakter + satu arena retail tampil benar di APK lokal.

## P4 — Audio

- mixer ringan (miniaudio/AAudio), 48 kHz, voice limit 24;
- konversi ADX/ATRAC3 → Opus di toolchain;
- sinkronisasi VO/impact dengan frame simulasi.

Kriteria terima: efek pukulan sinkron ±30 ms, tidak ada stutter saat 20 suara.

## P5 — Ukuran & distribusi

- ASTC 4x4/6x6 di packer + renderer (fallback RGBA8 untuk GPU lama);
- loader content pack `zstd` + unduhan bertahap (bootstrap APK);
- kuantisasi mesh 16-bit, keyframe reduction;
- AAB + Play Asset Delivery (opsional).

Kriteria terima: konten 2 GB terpasang ≤ 1,2 GB tanpa penurunan kualitas yang
terlihat pada jarak main normal; unduhan awal ≤ 100 MB.

## P6 — Poles

- shadow map cascade ringan untuk tier 3;
- post-processing hemat: bloom half-res, color grading LUT;
- UI menu, pemilihan karakter, pause, pengaturan grafis;
- save data & stats;
- aksesibilitas: remap tombol, skala UI, mode 30/60 fps pilihan pengguna.
