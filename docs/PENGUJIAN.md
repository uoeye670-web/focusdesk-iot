# Rencana & hasil pengujian

Isi tabel ini saat menguji dengan **dua HP fisik**, lalu salin ke PPT. Rekam layar dashboard dan kedua HP untuk video demo.

## Persiapan

- Nama HP A / HP B: …
- `.env`: `FOCUS_MINUTES=…`, `BREAK_MINUTES=…`, `LUX_LOW=…`, `DESK_ACTIVE_RMS=…`, `IDLE_SECONDS=…`
- Lokasi dan kondisi cahaya: …

## Kalibrasi sensor

| Kondisi | Nilai yang terukur |
|---|---|
| Lampu meja menyala (lux) | |
| Lampu mati (lux) | |
| Meja diam (`desk_rms`) | |
| Menulis di kertas (`desk_rms`) | |
| Mengetik di laptop (`desk_rms`) | |
| HP B tertelungkup (proximity, z) | |
| HP B dipegang (proximity, z) | |

## Skenario uji

| No | Skenario | Status yang diharapkan | Aksi yang diharapkan | Status aktual | Delay deteksi (detik) | Berhasil? |
|---|---|---|---|---|---|---|
| 1 | Menulis, HP B tertelungkup, lampu menyala | `FOKUS` | – | | | |
| 2 | Angkat HP B untuk scroll | `TERDISTRAKSI` | HP B getar + notifikasi | | | |
| 3 | Taruh kembali HP B | `FOKUS` | – | | | |
| 4 | Matikan lampu | `CAHAYA_KURANG` (setelah 30 dtk) | HP A bersuara | | | |
| 5 | Diam tanpa menulis | `MELAMUN` (setelah `IDLE_SECONDS`) | HP A bersuara | | | |
| 6 | Timer fokus habis | `ISTIRAHAT` | HP A suara, HP B getar | | | |
| 7 | Matikan Wi-Fi HP A | `MENUNGGU` (setelah 15 dtk) | – | | | |
| 8 | PAUSE lalu START | `JEDA`, lalu lanjut | Timer berhenti, lalu jalan lagi | | | |
| 9 | STOP | `IDLE` | HP A membacakan ringkasan | | | |

## Ringkasan sesi uji (dari dashboard)

| Sesi | Durasi | Waktu fokus | HP diambil | Skor rata-rata |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |

## Kesimpulan & kekurangan

- …
