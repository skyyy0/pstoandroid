# Arsitektur

```
┌──────────────────────────── Android shell (Kotlin) ─────────────────────────┐
│ MainActivity ── StormGLSurfaceView (GLES3) ── TouchOverlayView (Canvas HUD) │
│                        │                              │                     │
│                   NativeBridge (JNI)            ThermalMonitor              │
└────────────────────────┼──────────────────────────────┼─────────────────────┘
                         │                              │ suhu / status
┌────────────────────────▼──────────────────────────────▼─────────────────────┐
│ jni_bridge.cpp: fixed-step accumulator, input edge detection, thermal feed  │
│                                                                             │
│  World (game.cpp/ai.cpp)      Scene (scene.cpp)        PerfGovernor         │
│  ├─ 2 Fighter, 60 Hz          ├─ pilih clip per state  ├─ p95 frame time    │
│  ├─ damage/guard/hitstop      ├─ Animator + Pose       ├─ scale 0.55–1.0    │
│  └─ kamera (computeCamera)    └─ FrameView (DrawItem)  └─ tier 1–3, 30 fps  │
│                                                          saat panas         │
│  GLRenderer: toon + outline + rim + blob shadow + FBO blit                  │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Prinsip

1. **Simulasi tidak tahu renderer.** `World` hanya menghitung posisi, state, dan
   kamera. Bisa diuji tanpa GPU (3.775 cek).
2. **Renderer tidak tahu gameplay.** `FrameView` adalah daftar datar
   `{mesh, pose, model, flash}`.
3. **Fixed timestep 60 Hz.** Frame render boleh 30–120 fps; input dan tabrakan
   selalu 1/60 s sehingga hasil deterministik dan replay-nya sama.
4. **Kualitas dikendalikan governor, bukan tebakan.** Resolusi dulu, lalu tier,
   lalu target fps.

## Threading

| thread | pekerjaan |
| --- | --- |
| UI | sentuh layar, HUD 10 Hz, pembacaan sensor 1 Hz |
| GL | semuanya: init, simulasi, build frame, draw |
| native input | atomik (`moveX`, `moveY`, `buttons`, `thermalCelsius`) |

Tidak ada lock antara UI dan GL. `resetMatch()` hanya men-set flag atomik yang
dikonsumsi frame berikutnya.

## Loop per frame

```
dt = clamp(now - last, 0, 100 ms)
perf.pushFrame(dt)
perf.setThermalPressure(thermalPressureFromCelsius(suhu))
akumulasi += dt
while akumulasi >= 1/60 dan langkah < 4:
    world.step(playerInput, cpuThink(...))
    scene.update(1/60, world)
    akumulasi -= 1/60
scene.build(world, perf, aspect, waktu, frame)
renderer.render(frame)
```

Batas 4 langkah mencegah *spiral of death* saat frame drop berat.

## Renderer

- **Satu program** untuk toon + outline (uniform `uOutlinePass`), satu program
  kecil untuk blob shadow. Shader dikompilasi sekali saat start.
- **Vertex** 40 byte: posisi, normal, uv, 4 join (u8), 4 bobot (u8).
- **Bone** diunggah per draw item lewat bone palette texture `RGBA32F` 4 texel/bone (`kMaxBones = 128`) dan dibaca dengan `texelFetch` di vertex shader. Uniform `mat4[]`/uniform block akan melewati batas 256 vec4 uniform vertex di perangkat entry-level.
- **Toon**: 3 band (`smoothstep`), rim, specular bertingkat, fog eksponensial,
  flash merah saat kena hit.
- **Outline**: pass kedua, `glCullFace(GL_FRONT)`, ekspansi sepanjang normal
  0.018 unit.
- **Dynamic resolution**: render ke FBO `RGBA8 + DEPTH24`, lalu
  `glBlitFramebuffer` ke default framebuffer. FBO dialokasikan **sekali per
  ukuran surface**; perubahan skala hanya menggeser `glViewport` dan area blit,
  jadi governor bisa menurunkan resolusi tanpa realokasi tekstur (penyebab
  hitch paling kentara di GPU entry-level). Gagal membuat FBO → jatuh ke
  framebuffer default, bukan layar hitam.
- **Bayangan**: blob kontak di bawah karakter (murah, tidak butuh shadow map).
  Shadow map/cascade ada di roadmap.
- **Tier**: 0 = toon polos, 1 = +outline, 2 = +blob shadow, 3 = +rim/specular.
  Governor memilih tier ini bersama skala resolusi; semuanya hanya mengubah
  uniform/pass, bukan shader atau alokasi.
- **Upload bone**: setiap pose diunggah sekali per frame (bukan sekali per pass
  outline + warna) dan hanya sejumlah bone yang benar-benar dipakai.
- **Profil perangkat**: saat init, jumlah core, RAM class, dan string GPU dipakai
  untuk memilih `PerfConfig`. GPU entry-level (Adreno < 640, Mali-G5x, PowerVR)
  start di skala 0.72 dan boleh turun ke 0.40, sehingga frame pertama sudah
  lancar, bukan menunggu governor menyesuaikan diri.

## Format runtime

`.smesh` dan `.sanm` didokumentasikan di `tools/stormtools/formats.py`
(little-endian, section tabel, vertex stride 40 byte). Loader memvalidasi semua
indeks, parent tulang, dan batas submesh; input rusak ditolak dengan pesan,
tidak pernah crash.

## Batas yang disengaja

- Maksimum 96 tulang per mesh (uniform array).
- Maksimum 4 pengaruh tulang per vertex.
- Satu material per submesh, satu tekstur albedo per material.
- Belum ada audio, partikel, shadow map, atau post-processing.
