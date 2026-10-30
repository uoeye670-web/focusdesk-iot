# FocusDesk IoT

**Pomodoro adaptif dengan deteksi distraksi otomatis.** Dua HP sebagai edge (cahaya, accelerometer, proximity/gyroscope), 4 data processing, algoritma **Pomodoro adaptif berbasis sensor fusion**, komunikasi **MQTT Cloud (HiveMQ)**, dan **dashboard di laptop**.

## Pomodoro adaptif

Dasar programnya teknik Pomodoro (25 menit fokus, 5 menit istirahat, istirahat panjang setiap 4 sesi), tetapi dijalankan oleh sensor:

| Fitur | Cara kerja |
|---|---|
| **Mulai sendiri** | HP B ditelungkupkan ≥ 3 detik, pomodoro langsung berjalan tanpa menekan START |
| **Jeda sendiri** | HP B tidak telungkup ≥ `AWAY_SECONDS` (60 detik), pengguna dianggap meninggalkan meja dan timer dijeda. Telungkupkan lagi untuk melanjutkan |
| **Istirahat adaptif** | Skor fokus rata-rata tiap pomodoro menentukan istirahat: ≥ 80 normal, 60–79 × 1,4, < 60 × 1,8 |
| **Laporan per pomodoro** | Skor, jumlah HP diambil, dan lama istirahat untuk setiap pomodoro tampil di dashboard |

## Masalah & ide

Mahasiswa sering merasa sudah belajar berjam-jam, padahal sebagian waktunya habis untuk mengecek HP, melamun, atau belajar di cahaya yang kurang. FocusDesk mengukur fokus secara objektif:

- **HP A (meja)** diletakkan di meja dengan layar menghadap ke atas. HP ini mengukur cahaya meja dan getaran meja saat kamu menulis atau mengetik.
- **HP B (pribadi)** ditelungkupkan di meja selama sesi dan berfungsi sebagai saklar Pomodoro. Kalau HP ini diangkat, HP B menegur.
- **Laptop** menggabungkan data kedua HP menjadi skor fokus 0–100, menjalankan Pomodoro adaptif, dan menampilkan dashboard.

## Cara kerja

```mermaid
flowchart LR
  subgraph WIFI["Satu Wi-Fi / hotspot"]
    A["HP A · edge1 · meja<br/>light + accelerometer"]
    B["HP B · edge2 · pribadi<br/>proximity + accelerometer"]
    L["Laptop · detector<br/>+ dashboard localhost:8000"]
  end
  A -->|telemetry| M["Broker MQTT Cloud<br/>HiveMQ"]
  B -->|telemetry| M
  M -->|telemetry| L
  L -->|status, alerts| M
  M -->|alerts/edge1: suara| A
  M -->|alerts/edge2: getar| B
```

| Kondisi saat sesi fokus | Status | Aksi |
|---|---|---|
| HP B tertelungkup, meja aktif, cahaya cukup | `FOKUS` | – |
| HP B diangkat | `TERDISTRAKSI` | HP B bergetar dan muncul notifikasi |
| Cahaya < 300 lux selama 30 detik | `CAHAYA_KURANG` | HP A bersuara "Nyalakan lampu meja" |
| Cahaya > 1500 lux selama 30 detik | `CAHAYA_SILAU` | HP A bersuara |
| Meja diam selama 3 menit | `MELAMUN` | HP A bersuara "Ayo lanjut belajar" |
| Timer fokus habis | `ISTIRAHAT` | HP A bersuara, HP B bergetar |

Detail rumus dan algoritma: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## 1. Laptop: detector & dashboard

Pastikan sudah ada **Python 3.10+** dan internet.

```bash
python -m pip install -r requirements.txt
cp .env.example .env
```

*Di Windows PowerShell, gunakan `Copy-Item .env.example .env`.*

Ganti `PROJECT_ID` di `.env` menjadi nama kelompok yang unik, misalnya `focusdesk_kelompok05`. Default memakai broker publik HiveMQ (tanpa akun, **jangan kirim data rahasia**).

```bash
python detector.py
```

Buka **http://localhost:8000** di laptop.

## 2. HP A dan HP B: Termux

Di kedua HP: pasang Termux + Termux:API dari F-Droid, salin repo ini, install dependensi, dan samakan `PROJECT_ID` dengan laptop. Panduan lengkap: [docs/ANDROID.md](docs/ANDROID.md).

**HP A (meja, layar menghadap ke atas):**
```bash
python hp_meja.py
```

**HP B (pribadi, ditelungkupkan):**
```bash
python hp_pribadi.py
```

### HP B memakai iPhone (tanpa Termux)

iPhone tidak bisa memakai Termux, jadi HP B dijalankan lewat Safari:

**https://uoeye670-web.github.io/focusdesk-iot/web/hp-pribadi.html**

Halaman ini membaca **accelerometer + gyroscope** (proximity tidak tersedia di browser), mengolahnya dengan rumus yang sama, lalu mengirim telemetry `edge2` lewat MQTT over WebSocket. Saat ada alert, layar berubah merah dan berbunyi (iPhone tidak bisa digetarkan dari browser). Isi PROJECT_ID, kalibrasi dengan HP terlentang, tekan **Mulai**, lalu telungkupkan HP. Atur **Auto-Lock: Never** supaya layar tidak terkunci.

HP A tetap harus Android karena butuh sensor cahaya.

## 3. Coba sistemnya

1. Telungkupkan HP B. Setelah 3 detik pomodoro mulai sendiri (tombol **START** juga bisa dipakai).
2. Menulislah di kertas atau mengetik. Status harus `FOKUS`.
3. Angkat HP B sebentar. Status berubah menjadi `TERDISTRAKSI` dan HP B menegur.
4. Bawa HP B pergi lebih lama dari `AWAY_SECONDS`. Status menjadi `DITINGGAL` dan timer berhenti. Telungkupkan lagi untuk melanjutkan.
5. Matikan lampu. Setelah 30 detik status menjadi `CAHAYA_KURANG` dan HP A bersuara.
6. Tunggu pomodoro selesai. HP A mengumumkan skornya dan lama istirahat yang sudah disesuaikan.
7. Tekan **STOP**. HP A membacakan ringkasan sesi.

Untuk video demo, perpendek timer di `.env` (misalnya `FOCUS_MINUTES=3`, `BREAK_MINUTES=1`).

## Latihan tanpa HP

```bash
python -m scripts.offline_demo        # algoritma saja, tanpa broker
python -m unittest discover -s tests  # unit test
python hp_meja.py --source simulator --scenario gelap
python hp_pribadi.py --source simulator --scenario diangkat
```

Simulator hanya untuk latihan dan debugging, **tidak dihitung sebagai edge fisik**.

## Kalibrasi sensor

Setiap HP berbeda. Sebelum demo, cek angka sensor di HP masing-masing:

```bash
python -m scripts.check_sensors --role meja      # HP A
python -m scripts.check_sensors --role pribadi   # HP B
```

Sesuaikan `LUX_LOW`, `LUX_HIGH`, `DESK_ACTIVE_RMS`, dan `IDLE_SECONDS` di `.env` sesuai hasilnya.

Untuk `DESK_ACTIVE_RMS`, jalankan kalibrasi otomatis di HP A (HP terlentang di meja). Script ini mengukur meja saat diam dan saat menulis, lalu menyarankan nilainya:

```bash
python -m scripts.kalibrasi_meja
```

## Struktur kode

- `detector.py`: NODE 3 (laptop + dashboard localhost)
- `hp_meja.py`: NODE 1 (HP A, light + accelerometer)
- `hp_pribadi.py`: NODE 2 (HP B, proximity + accelerometer)
- `shared/sensors.py`: membaca sensor lewat Termux:API (atau simulator)
- `shared/processing.py`: 4 data processing di edge
- `shared/messages.py`: format JSON telemetry dan alert
- `nodes/detector_service/rules.py`: algoritma skor fokus + Pomodoro
- `shared/alarm.py`: suara (HP A) dan getar/notifikasi (HP B)
- `dashboard/index.html`: dashboard web lewat MQTT over WebSocket
- `web/hp-pribadi.html`: HP B versi browser (iPhone), di-host lewat GitHub Pages

Dokumentasi: [Arsitektur & algoritma](docs/ARCHITECTURE.md) · [Android/Termux](docs/ANDROID.md) · [Pengujian](docs/PENGUJIAN.md).

## Kredit

Kerangka kode (koneksi MQTT, edge runner, dashboard server) diadaptasi dari contoh proyek [myudak/contoh-project-iot1](https://github.com/myudak/contoh-project-iot1) (lisensi MIT). Ide, sensor, data processing, algoritma, dan dashboard FocusDesk dibuat ulang untuk proyek ini.
