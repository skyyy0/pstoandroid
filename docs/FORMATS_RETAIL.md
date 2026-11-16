# Format retail Storm Revolution: yang sudah terverifikasi dan yang belum

Runtime tidak boleh menebak layout biner. Dokumen ini memisahkan **spesifikasi
yang dipakai kode** dari **asumsi**, dan mencatat sumber tiap klaim. Yang belum
punya spesifikasi tidak diparse — payload-nya diekstrak utuh dan dilaporkan
sebagai belum didukung.

Referensi komunitas yang dipakai (implementasi, bukan tebakan):

- UTF/CPK: `kamikat/cpktools`, `Sewer56/CriFsV2Lib` (`CriPak`), `wmltogether/CriPakTools`;
- CRILAYLA: `the4chancup/pes-file-tools/lib/pes_file_tools/crilayla.py`,
  `Sewer56/CriFsV2Lib` (`CriLayla.cs`), deskripsi awal unknownbrackets;
- XFBIN/NUCC: `mosamadeeb/xfbin_lib` (Python), `KojoBailey/NUCC-010-Template-Library`
  (`Templates/xfbin.bt`, `nuccChunk.bt`, `nuccIndex.bt`), wiki
  `jojomodding.miraheze.org/wiki/NUCC`.

## 1. CPK (CriWare FileMajik) — NYATA di kode

`data.cpk` adalah pembungkus seluruh pohon aset. Yang dipakai `cpk.py`:

| Offset | Tipe | Isi |
| --- | --- | --- |
| 0x00 | char[4] | `@UTF` |
| 0x04 | u32 | ukuran tabel (termasuk header 0x20) |
| 0x08 | u32 | offset baris relatif ke awal tabel |
| 0x0C | u32 | offset tabel string |
| 0x10 | u32 | offset tabel data (kolom bertipe `data`) |
| 0x14 | u32 | offset nama tabel |
| 0x18 | u16 | jumlah kolom |
| 0x1A | u16 | panjang satu baris |
| 0x1C | u32 | jumlah baris |

Kolom yang relevan: `FileName` (string), `DirName` (string), `FileOffset` (u32),
`FileSize` (u32), `ExtractSize` (u32). Endianness **little-endian**, satu-satunya
bagian pipeline yang begitu — semua format di bawahnya big-endian.

Berkas retail menaruh tabel di belakang wrapper 16 byte, jadi `cpk.py` mencoba
setiap kandidat `@UTF` sampai satu berhasil diparse. Kolom dengan flag `0x50`
(nilai konstan) juga didukung karena dipakai beberapa CPK.

`FileSize != ExtractSize` berarti entri tersebut adalah frame CRILAYLA.

## 2. CRILAYLA — NYATA di kode (`tools/stormtools/crilayla.py`)

```
0x00  char[8]  "CRILAYLA"
0x08  u32      uncompressed_size   (tanpa prefix 0x100)
0x0C  u32      compressed_size
0x10  byte[compressed_size]        aliran bit
      byte[0x100]                  prefix verbatim (256 byte pertama berkas)
```

Panjang berkas hasil = `0x100 + uncompressed_size`; `ExtractSize` CPK harus sama
dengan nilai itu.

Aliran bit dibaca dari **byte terakhir ke belakang**, bit paling signifikan
dulu; output dibangun dari **ujung ke awal**, mulai indeks `0x100 + size - 1`
sampai `0x100`. Dua pola:

- literal — bit `0`, lalu 8 bit data;
- back-reference — bit `1`, 13 bit `jarak - 3`, lalu panjang mulai 3 yang
  ditambah potongan 2, 3, 5 bit, dan bila ketiganya jenuh dilanjutkan potongan
  8 bit selama nilainya `0xFF`.

Byte sumber dihitung ulang dari posisi tulis yang bergerak (`out[cursor] =
out[cursor + distance]`), sehingga match boleh menimpa byte yang baru ditulis;
itulah cara run panjang disimpan. Implementasi `crilayla.py` memvalidasi magic,
ukuran frame, `ExtractSize`, dan batas back-reference, lalu melempar
`CrilaylaError` alih-alih menghasilkan data terpotong.

## 3. XFBIN / NUCC — NYATA di kode (`tools/stormtools/xfbin.py`)

Satu berkas `.xfbin` berisi beberapa chunk bertipe plus indeks yang memberi nama.
Semuanya **big-endian**.

```
0x00  char[4]  "NUCC"
0x04  u32      versi xfbin
0x08  u16      flags.unk00
0x0A  char[2]  flags.language
0x0C  u16      flags.unk04
0x0E  u16      flags.unk06
```

Header chunk (12 byte) dipakai ulang untuk indeks dan setiap chunk berikutnya:

| Offset | Tipe | Isi |
| --- | --- | --- |
| +0x00 | u32 | ukuran payload |
| +0x04 | u32 | `map_index` (kunci ke indeks) |
| +0x08 | u16 | versi chunk |
| +0x0A | u16 | belum diketahui |

Chunk indeks (selalu chunk pertama, mulai 0x10) berisi 10 u32:

`chunk_type_count`, `chunk_type_size`, `file_path_count`, `file_path_size`,
`chunk_name_count`, `chunk_name_size`, `chunk_map_count`, `chunk_map_size`,
`chunk_map_indices_count`, `extra_map_indices_count`.

Lalu tabel string NUL-terminated (tipe, path, nama), padding ke 4 byte, tabel
chunk map `{u32 type_index, u32 path_index, u32 name_index}`, tabel extra map
`{u32 name_index, u32 map_index}`, dan tabel `chunk_map_indices` berisi u32.

Setiap chunk setelah indeks: header 12 byte + payload. `map_index` → indeks →
chunk map → (tipe, path, nama). Bila `map_index` di luar tabel, `xfbin.py`
mencoba memakainya langsung sebagai indeks chunk map dan mencatat peringatan —
inilah satu-satunya titik yang masih spekulatif, dan peringatan itu muncul di
laporan agar tidak lewat tanpa terlihat.

## 4. Payload chunk — BELUM ADA PARSER

| Chunk | Ekstensi hasil | Status |
| --- | --- | --- |
| `nuccChunkModel` (NUD, magic `NDP3`) | `.nud` | belum diparse |
| `nuccChunkTexture` (NUT, magic `NTP3`/GIDX) | `.nut` | belum diparse |
| `nuccChunkAnm` (animasi retail) | `.anm` | belum diparse |
| `nuccChunkBinary` (XML/script/data) | `.bin` | diekstrak apa adanya |
| `nuccChunkNub` (audio NUB) | `.nub` | diekstrak apa adanya |
| `nuccChunkCamera`, `nuccChunkLight`, `nuccChunkPage`, `nuccChunkNull` | `.cam`, `.light`, `.page`, `.null` | diekstrak apa adanya |

Chunk tak dikenal tetap ditulis dengan nama `NNN_<nama>.raw` dan dicatat di
`report.json`. Tidak ada tebakan isi: menafsirkan layout NUD/NTP3 tanpa
spesifikasi akan menghasilkan mesh rusak yang lebih sulit didiagnosis daripada
berkas utuh yang jelas belum didukung.

Parser NUD/NTP3/ANM akan ditulis dari `xfbin_lib`/UNSME sebagai referensi, lalu
diuji pada berkas retail milik pengguna (tidak pernah masuk repo, lihat
`docs/LEGAL.md`).

## 5. Audio — BELUM ADA

Retail memakai ADX/HCA di dalam CPK. Belum ada pembaca maupun pemutar; tidak ada
satu baris kode audio di engine. Ini subsistem terpisah, bukan bagian dari
pipeline container.

## 6. Cara verifikasi saat ini, dan batasnya

- `tools/tests/test_pipeline.py` membangun CPK, frame CRILAYLA (literal dan
  back-reference, termasuk panjang 8-bit), serta XFBIN sintetis menurut layout
  di atas, lalu memeriksa round-trip: ekstraksi harus mengembalikan byte yang
  identik, dan `report.json` harus mencatat tipe chunk yang benar.
- Tes itu membuktikan **konsistensi internal dan penanganan galat**, bukan
  kesesuaian dengan berkas retail. Encoder uji memakai asumsi yang sama dengan
  decoder, jadi kesalahan asumsi bersama tidak akan tertangkap.
- Validasi sesungguhnya butuh satu `data.cpk` retail. Perintahnya:

```
python3 -m stormtools cpk list data.cpk | head
python3 -m stormtools retail unpack data.cpk out/ --only chara --ext .xfbin --limit 20
```

Bila `report.json` menunjukkan `failed > 0` atau `chunks: 0` untuk berkas yang
seharusnya berisi model, artinya layout belum cocok dan parser harus
diperbaiki — bukan diakali dengan melonggarkan validasi.
