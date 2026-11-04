# Pipeline aset

Aset retail tidak disertakan di repo. Pipeline ini menerima data dari **game yang
Anda miliki sendiri** dan mengubahnya menjadi paket yang dibaca engine.

## Alur

```
data.cpk
  │  python3 -m stormtools cpk list data.cpk
  │  python3 -m stormtools cpk extract data.cpk out/
  ▼
*.xfbin  (mesh, animasi, tekstur, material)
  │  python3 -m stormtools scan out/            # inventaris signature
  │  Blender + XFBIN importer (tool komunitas)
  ▼
*.glb (glTF 2.0, rig + animasi)
  │  python3 -m stormtools pack model.glb \
  │      --out android/app/src/main/assets/storm \
  │      --manifest android/app/src/main/assets/storm/manifest.txt \
  │      --prefix storm
  ▼
*.smesh / *.sanm / manifest.txt  →  APK
```

## Perintah yang tersedia

```bash
cd tools

python3 -m stormtools cpk list  /path/data.cpk
python3 -m stormtools cpk extract /path/data.cpk /tmp/storm_raw
python3 -m stormtools scan /tmp/storm_raw
python3 -m stormtools info android/app/src/main/assets/storm/fighter.smesh
python3 -m stormtools pack hero.glb --out ../android/app/src/main/assets/storm \
    --manifest ../android/app/src/main/assets/storm/manifest.txt --prefix storm --scale 1.0
python3 -m stormtools demo          # regenerate aset demo orisinal
```

`data.cpk` yang memakai entri `CRILAYLA` terkompresi akan ditolak dengan pesan
jelas: repo ini sengaja tidak menebak-nebak decoder LZ yang belum tervalidasi.
Gunakan CriPakTools untuk mengekstrak, lalu lanjutkan dengan `scan`/`pack`.

## Manifest

Grammar di `android/app/src/main/assets/storm/manifest.txt`:

```
mesh <nama> <path relatif assets>
anim <nama mesh> <nama clip> <path relatif assets>
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
audio. Keduanya butuh perubahan loader, jadi dicatat sebagai fase P5 di
`ROADMAP.md`.

## Reproduksi aset demo

`python3 -m stormtools demo` menghasilkan 10 file (132 KB): dua karakter 17
tulang, satu arena, tujuh clip. Semua prosedural, tanpa IP, dan dipakai oleh test
host maupun APK.
