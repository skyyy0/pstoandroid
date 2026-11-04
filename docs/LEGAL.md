# Legal dan batasan distribusi

## Ringkasan

Repo ini **tidak** memuat aset, kode, atau data dari game komersial. Yang ada
hanya engine, toolchain, dan aset demo prosedural.

## Yang tidak boleh dilakukan

- Mengunggah `data.cpk`, `*.xfbin`, tekstur, model, animasi, audio, atau video
  dari game ke repo publik, Release, artifact, atau layanan file-sharing.
- Mendistribusikan APK yang berisi aset retail.
- Menjual, menyewakan, atau memonetisasi build yang memuat aset pihak ketiga.

Naruto Shippuden: Ultimate Ninja Storm Revolution adalah milik Bandai Namco
Entertainment / CyberConnect2. Nama, karakter, logo, dan asetnya dilindungi hak
cipta dan merek dagang.

## Penggunaan pribadi

Pipeline ini ditujukan untuk membuat build yang berjalan di perangkat Anda dari
salinan game yang Anda miliki sendiri. Status hukum *porting* pribadi berbeda di
tiap yurisdiksi; dokumen ini bukan nasihat hukum.

## Clean-room

- Format file (`cpk`, `xfbin`, `smesh`, `sanm`) diimplementasikan ulang dari
  observasi dan dokumentasi komunitas, bukan dari SDK resmi.
- Renderer, gameplay, dan UI ditulis dari nol.
- Aset demo dihasilkan oleh `tools/stormtools/demo_assets.py`.

## Takedown

Jika Anda pemegang hak dan menemukan materi yang melanggar, buka issue dengan
tautan spesifik; materi tersebut akan dihapus.

## Lisensi kode

Belum ditetapkan. Sebelum distribusi publik, pilih lisensi (misalnya MIT untuk
kode engine, dengan catatan bahwa itu tidak memberi hak atas aset game).
