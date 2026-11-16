# Audit: apa yang benar-benar jalan, apa yang masih tiruan

Dokumen ini menjawab satu pertanyaan: **kalau APK dipasang hari ini, apakah yang
tampil itu Naruto Storm Revolution yang asli?** Jawabannya belum. Audit di bawah
memisahkan tiga hal yang mudah tercampur:

1. **subsistem engine yang nyata** (renderer, skinning, animasi, governor) —
   ada kode, ada uji, dipakai tiap frame;
2. **konten harness** (adegan duel, AI, aset prosedural) — sengaja tiruan,
   fungsinya menguji engine, bukan meniru gameplay retail;
3. **subsistem retail yang belum ada** (importer model/tekstur retail, VFX,
   audio, script, UI) — belum ada sama sekali.

Status "MOCK" di bawah **bukan** berarti dihapus: kode itu berguna sebagai alat
uji regresi dan tetap dipakai CI. Yang salah adalah menganggapnya produk.

| Status | Arti |
| --- | --- |
| NYATA | berjalan dengan data nyata pada format yang dideklarasikan, diuji |
| PARSIAL | mekanismenya nyata, tetapi datanya/parameter masih harness |
| HARNESS | sengaja tiruan untuk menguji engine; bukan gameplay retail |
| HILANG | belum ada kode sama sekali |

## Ringkasan

| # | Subsistem | Status | Bukti |
| --- | --- | --- | --- |
| 1 | Renderer GLES 3 (toon, outline, blob shadow, FBO tetap, tier 0–3) | NYATA | `native/src/render/gl_renderer.cpp` |
| 2 | GPU skinning (palet tulang `RGBA32F` + `texelFetch`, 128/96 tulang) | NYATA | `gl_renderer.cpp:19-32`, `:204-226` |
| 3 | Sampling animasi + blend (loop, crossfade) | NYATA | `native/src/animation.cpp` |
| 4 | Loader paket `.smesh` / `.sanm` (format internal) | NYATA | `native/src/asset.cpp:117`, `:273` |
| 5 | Loader container retail: CPK/UTF, CRILAYLA, XFBIN/NUCC | PARSIAL | `tools/stormtools/cpk.py`, `crilayla.py`, `xfbin.py`, `retail.py` |
| 6 | Importer mesh retail `.nud` (NDP3) | HILANG | chunk hanya diekstrak, belum diparse |
| 7 | Importer tekstur retail `.nut` (NTP3/GIDX) | HILANG | idem |
| 8 | Material/shader retail (`nuccMaterial`, shader game) | HILANG | engine memakai material sendiri |
| 9 | VFX (partikel, jutsu, afterimage) | HILANG | tidak ada kode partikel |
| 10 | Audio (ADX/HCA di CPK, voice, BGM) | HILANG | `grep` audio = 0 berkas |
| 11 | Sistem pertarungan (HP, hitbox, state, cancel) | HARNESS | `native/src/game.cpp:64-366` |
| 12 | AI lawan | HARNESS | `native/src/ai.cpp` |
| 13 | Kamera | PARSIAL | kamera follow/deadzone sendiri, bukan kamera retail |
| 14 | Input sentuh → engine | NYATA | `TouchOverlayView.kt`, `jni_bridge.cpp` (atomics) |
| 15 | Menu, character select, HUD retail | HILANG | hanya overlay FPS/suhu |
| 16 | Script/misi (chunk binary/XML), tabel param & moveset | HILANG | belum ada pembaca |
| 17 | Sumber aset dari storage perangkat (di luar APK) | NYATA (baru) | `asset_source.h`, `jni_bridge.cpp` |

Cek host: **3.782 pemeriksaan lulus**. Cek Python: **21 test lulus**. Tidak ada
satu pun yang membuktikan aset retail termuat.

## Yang tampil di APK rilis `v1.0.0-free`

- ukuran 1.176.192 byte; isi aset hanya 132 KB di
  `android/app/src/main/assets/storm/` (`fighter.smesh`, `rival.smesh`,
  `arena.smesh`, 7 `*.sanm`, `manifest.txt`);
- fighter adalah mesh prosedural dari `tools/stormtools/demo_assets.py`;
- tidak ada `data.cpk`, tidak ada `*.xfbin`, tidak ada tekstur retail;
- duel 60 Hz + AI (`game.cpp`, `ai.cpp`) hanya menggerakkan mesh prosedural itu.

Artinya: **APK saat ini adalah engine + harness, bukan game Storm yang jalan.**
Kalau ada yang menyebutnya "game Naruto", itu klaim yang tidak didukung build.

## Kenapa belum bisa "langsung memuat aset retail"

Tiga hal berbeda, dan ketiganya harus selesai:

1. **Container** (dikerjakan pada perubahan ini): membuka `.cpk`, mendekode
   CRILAYLA, memecah `.xfbin` jadi chunk bertipe. Sekarang sudah nyata dan
   teruji secara struktural, tetapi **belum diuji dengan berkas retail**.
2. **Payload** (belum): chunk `.nud`/`.nut`/`.anm` harus diparse jadi vertex,
   indeks, tekstur, dan track tulang. Tanpa ini, chunk hanya berkas biner.
3. **Perilaku** (belum): state machine pertarungan, kamera, VFX, audio, dan
   script retail. `game.cpp` tidak memuat satu pun aturan dari game asli.

Selama (2) dan (3) belum ada, runtime tidak boleh mengklaim menjalankan game.
Loader yang belum punya spesifikasi harus **menolak** payload dan melaporkan
tipenya, bukan menggambar sampah — aturan itu sekarang dipegang `xfbin.py`
(chunk tak dikenal tetap diekstrak apa adanya, tanpa ditafsirkan).

## Status per subsistem

### Renderer & skinning — NYATA

`gl_renderer.cpp` membangun satu program toon (albedo + rim + outline + blob
shadow), memakai FBO warna tetap dengan resolusi yang dikendalikan governor, dan
mengunggah palet tulang sebagai tekstur float yang dibaca `texelFetch`. Semua
ini bekerja pada aset harness; kualitas visual retail (post-process, rim ganda,
outline per-material) belum ada.

### Animasi — NYATA di runtime, HARNESS di data

`animation.cpp` melakukan sampling keyframe, normalisasi quaternion, dan
percampuran antar-clip. Format `.sanm` adalah format internal (bukan ANM retail),
jadi klip yang diputar tetap animasi prosedural `demo_assets.py`.

### Pertarungan & AI — HARNESS

`World::step` memajukan dua fighter pada 60 Hz dengan HP, hitbox sederhana, dan
round timer (`game.cpp:259-366`). `ai.cpp` menunjukkan perilaku "lawan dummy"
dengan reaction time. **Tidak ada** state cancel, guard impact, chakra dash,
substitution, atau moveset dari data game. Ini alat uji: kalau skinning atau
kamera rusak, duel ini yang menunjukkan.

### Aset retail — container NYATA, payload HILANG

Baru tersedia:

- `crilayla.py` — dekompresi frame CRILAYLA dengan validasi ukuran;
- `xfbin.py` — header NUCC, tabel chunk, resolusi tipe/nama/path, ekstraksi
  payload per chunk dengan ekstensi sesuai tipe;
- `retail.py` — `stormtools retail unpack` menjalankan CPK → CRILAYLA → XFBIN →
  chunk, plus `report.json` yang mencatat setiap chunk dan peringatan struktur.

Belum tersedia: parser NDP3 (mesh), NTP3/GIDX (tekstur), ANM retail, material,
dan audio. Semua chunk itu diekstrak utuh agar bisa diproses bertahap tanpa
menebak isi.

### Runtime memuat aset dari perangkat — NYATA

`ChainedAssetSource` mencoba direktori `port/` di storage aplikasi lebih dulu,
lalu `assets/port/`, lalu `assets/storm/`. Log memuat nama manifest yang dipakai,
jadi build yang jatuh ke harness terlihat jelas di logcat:

```
manifest: manifest.txt (port directory)
```

Konsekuensi: pengguna bisa menaruh paket hasil konversi di
`Android/data/com.sky.stormrev/files/port/` tanpa membangun ulang APK, dan APK
distribusi tetap bebas aset retail (`docs/LEGAL.md`).

## Kriteria agar klaim berubah

Klaim "menjalankan Storm Revolution" baru boleh dipakai setelah, di perangkat:

1. `data.cpk` retail dibuka, satu karakter + satu stage berhasil diparse jadi
   mesh/tekstur/animasi (bukan sekadar diekstrak);
2. karakter itu tampil dengan tekstur dan animasi idle-nya di layar;
3. ada jejak verifikasi: log jumlah vertex/indeks/tekstur/track dan tangkapan
   layar dari build tersebut.

Sampai ketiganya ada, status proyek adalah **runtime + pipeline yang sedang
dibangun**, dan itu yang ditulis di README.
