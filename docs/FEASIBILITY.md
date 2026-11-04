# Kelayakan teknis: kenapa bukan emulator

## Ringkasan

| pendekatan | realistis di Android? | alasan |
| --- | --- | --- |
| Emulasi PS3 (RPCS3) | tidak | RPCS3 tidak punya target Android; butuh JIT x86→host, memori besar, dan GPU desktop-class |
| Emulator PS3 Android komunitas (aPS3e/RPCSX) | sangat terbatas | laporan komunitas: Snapdragon 8 Gen 2 ke atas, RAM 12 GB, frame rate tidak stabil |
| Streaming dari PC | ya, tapi bukan port | butuh PC + jaringan; bukan APK mandiri |
| **Native ARM64 + konversi aset** | **ya** | pola yang sudah terbukti di proyek *static recompilation* (XenonRecomp dkk.) |

Kesimpulan: target "entry level sampai flagship tetap lancar" tidak bisa dicapai
dengan emulasi. Yang bisa dikendalikan penuh adalah engine native: berapa draw
call, berapa tekstur, berapa resolusi render, dan kapan harus turun kualitas.

## Mengapa proyek komunitas bisa 30 fps di perangkat menengah

Proyek seperti XenonRecomp mengubah binary game menjadi kode C++ yang dikompilasi
native, lalu menjalankan aset asli lewat renderer baru. Tidak ada translasi
instruksi saat runtime, tidak ada emulasi GPU RSX. Biaya terbesar pindah ke
desain renderer dan format aset — persis yang dikerjakan repo ini.

## Konsekuensi yang harus diterima

1. **Butuh aset dari game yang Anda miliki.** Repo tidak memuatnya.
2. **Bukan 1:1 dengan PS3.** Model, tekstur, dan animasi bisa sama; shader,
   pencahayaan, dan post-processing ditulis ulang untuk mobile.
3. **Butuh pipeline per game/versi.** Format `xfbin`/`cpk` CyberConnect2 tidak
   terdokumentasi resmi; tool komunitas menutup sebagian besar celah.
4. **Bukan pekerjaan satu rilis.** Roadmap dibagi per fase dengan kriteria
   terima yang jelas.

## Anggaran performa yang dipakai

| metrik | target | catatan |
| --- | --- | --- |
| frame time p95 | ≤ 16,7 ms @ 60 fps | tier 3, resolusi 1.0x |
| draw call | ≤ 120 | arena + 2 karakter + outline + bayangan |
| resolusi | 0.55x–1.0x dinamis | governor menurunkan lebih dulu sebelum fps |
| tulang per karakter | ≤ 96 | batas uniform array GLES 3 |
| suhu | < 62 °C nyaman, > 72 °C throttle | dikunci 30 fps saat tekanan termal tinggi |
| RAM | < 700 MB | aset demo 132 KB; aset retail perlu streaming |

Angka ini adalah anggaran desain, bukan hasil pengukuran di perangkat. Pengukuran
pertama ada di roadmap fase P1.
