# Pipeline aset

Aset retail tidak disertakan di repo. Pipeline ini menerima data dari **game yang
Anda miliki sendiri**, mengeluarkannya dari container aslinya, dan mengubahnya
menjadi paket yang dibaca engine.

Dua jalur yang berbeda, jangan dicampur:

| jalur | status | dipakai untuk |
| --- | --- | --- |
| **retail** — `data.cpk` → CRILAYLA → XFBIN → chunk | container nyata, parser payload belum ada | target sebenarnya |
| **glTF** — `.glb` → `.smesh`/`.sanm` | nyata dan teruji | membawa hasil impor/konversi ke engine |

## Alur retail

```
data.cpk
  │  python3 -m stormtools cpk list data.cpk          # inventaris entri
  │  python3 -m stormtools retail unpack data.cpk out/ # decode + split
  ▼
out/chara/naruto.xfbin               (berkas utuh, sudah didekode)
out/chara/naruto_chunks/000_body.nud (payload per chunk, apa adanya)
out/chara/naruto_chunks/001_face.nut
out/chara/naruto_chunks/002_idle00.anm
out/report.json                      (tipe, ukuran, peringatan struktur)
```

Contoh:

```bash
cd tools
python3 -m stormtools cpk list /path/data.cpk | head -20
python3 -m stormtools retail unpack /path/data.cpk /tmp/storm --only chara --ext .xfbin --limit 50
python3 -m stormtools xfbin list /tmp/storm/chara/naruto.xfbin
```

`retail unpack` **tidak** menafsirkan isi `.nud`/`.nut`/`.anm`: payload ditulis
persis seperti di container, dan `report.json` mencatat setiap chunk. Chunk tanpa
parser tetap bisa diperiksa dengan tool komunitas (xfbin_lib/UNSME) tanpa perlu
mengekstrak ulang CPK.

Batasan yang harus diingat: `report.json` yang menunjukkan `"chunks": 0` atau
`"failed" > 0` untuk berkas yang seharusnya berisi model berarti layout belum
cocok. Perbaiki parser — jangan melonggarkan validasi agar "kelihatan jalan".

## Alur konversi ke engine

```
chunk retail → (importer, belum ada) → .glb
.glb → python3 -m stormtools pack → .smesh / .sanm + manifest.txt
     → storage/port/ di perangkat  atau  android/app/src/main/assets/storm/
```

Paket hasil konversi taruh di storage aplikasi (tanpa membangun ulang APK):

```
Android/data/com.sky.stormrev/files/port/
    manifest.txt
    chara/naruto.smesh
    chara/naruto_idle.sanm
```

Saat init engine mencoba berurutan: `port/` di storage → `assets/port/` →
`assets/storm/` (harness). Logcat mencetak manifest yang dipakai.

## Perintah yang tersedia

```bash
cd tools

python3 -m stormtools cpk list  /path/data.cpk
python3 -m stormtools cpk extract /path/data.cpk /tmp/storm_raw   # decode CRILAYLA
python3 -m stormtools retail unpack /path/data.cpk /tmp/storm     # + split xfbin
python3 -m stormtools xfbin list /tmp/storm/chara/naruto.xfbin
python3 -m stormtools xfbin extract /tmp/storm/chara/naruto.xfbin /tmp/storm/naruto_chunks
python3 -m stormtools scan /tmp/storm
python3 -m stormtools info android/app/src/main/assets/storm/fighter.smesh

python3 -m stormtools pack hero.glb tmp/out \
    --name hero \
    --manifest tmp/out/manifest.txt \
    --scale 1.0

python3 -m stormtools demo          # regenerate aset harness (bukan retail)
```

Entri CPK yang terkompresi didekode oleh `crilayla.py`. Frame yang ukurannya tidak
konsisten dengan `ExtractSize` ditolak dengan pesan jelas, bukan dipotong diam-diam.

## Manifest

Grammar di `android/app/src/main/assets/storm/manifest.txt` (path relatif
terhadap root sumber aset yang dipilih):

```
mesh <nama> <path>
anim <nama mesh> <nama clip> <path>
character <id> <nama mesh> <skala>
arena <id> <nama mesh>
```

Contoh:

```
mesh fighter storm/fighter.smesh
anim fighter idle storm/fighter_idle.sanm
character rookie fighter 1.0
arena dojo fighter
```

Manifest parser mengabaikan baris tak dikenal dan mencatatnya di `warnings`
(ditampilkan di logcat saat init), jadi manifest lama tidak membuat app gagal
start.

## Format `.smesh`

Little-endian, header + tabel section:

| field | tipe | catatan |
| --- | --- | --- |
| magic | `SMESH\0` | 8 byte |
| version | u32 | 1 |
| boundsMin/Max | 3×f32 | untuk kamera dan culling |
| counts | u32 × 6 | texture, material, bone, submesh, vertex, index |
| textures | RGBA8 | lebar, tinggi, data |
| materials | f32 × 10 + i32 | baseColor, rimColor, spec, shininess, emissive, alphaCutoff, albedo |
| bones | u32 + i32 + 4×4 f32 | nameHash, parent, inverseBind |
| submeshes | u32, u32, i32 | indexOffset, indexCount, material |
| vertices | 40 byte | pos 12, normal 12, uv 8, joints 4×u8, weights 4×u8 |
| indices | u32 | segitiga |

`weights` selalu berjumlah 255. Batas: 96 tulang, 4 pengaruh per vertex.
Packer menolak rig lebih besar dari 96 tulang dengan `PackError`.

## Format `.sanm`

Header + clip (nama 32 byte, durasi, loop) + track per tulang (`nameHash`, jumlah
key, key `{time, quat, pos}`). Rotasi selalu dinormalisasi saat load; animator
melakukan crossfade di ruang matriks lokal.

## Menuju aset 2 GB

Rencana pengurangan ukuran tanpa menurunkan kualitas (belum diimplementasikan):

| aset | sekarang | rencana | perkiraan |
| --- | --- | --- | --- |
| tekstur | PNG RGBA8 | ASTC 4x4 (karakter) / 6x6 (arena) | 2–2,5× lebih kecil, decode gratis di GPU |
| audio | belum ada | Opus 48–64 kbps | 3–4× lebih kecil dari WAV/ADX |
| vertex | 40 byte | posisi 16-bit + normal oktahderal + joint u16 | ~16 byte |
| animasi | key tiap frame | kurva + key reduction | 2–5× lebih kecil |
| duplikat | tidak dicek | hash tekstur/mesh, pakai satu | 5–15% |

Langkah pertama yang berdampak besar dan murah: ASTC untuk tekstur dan Opus untuk
audio. Keduanya butuh perubahan loader, jadi dicatat sebagai fase P6 di
`ROADMAP.md`.

## Reproduksi aset harness

`python3 -m stormtools demo` menghasilkan 10 file (132 KB): dua karakter 17
tulang, satu arena, tujuh clip. Semua prosedural, tanpa IP, dan dipakai oleh test
host maupun APK. Ini **alat uji regresi**, bukan konten game.
