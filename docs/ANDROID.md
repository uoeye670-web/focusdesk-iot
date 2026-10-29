# Menjalankan edge di Android (Termux)

Jalankan NODE 1 dan NODE 2 pada **dua HP Android terpisah**, bukan dua terminal di laptop.

## Instalasi di kedua HP

1. Install **F-Droid** dari https://f-droid.org/, lalu dari F-Droid install **Termux** dan **Termux:API**. Keduanya harus dari sumber yang sama.
2. Buka Termux:

```bash
pkg update
pkg install python git termux-api
git clone <link-repo-github-kelompok>
cd focusdesk-iot
python -m pip install -r requirements.txt
cp .env.example .env
termux-sensor -l
```

3. Pastikan `termux-sensor -l` menampilkan:
   - **HP A:** sensor **light** dan **accelerometer**
   - **HP B:** sensor **proximity** dan **accelerometer**
4. Edit `PROJECT_ID` di `.env` (misalnya dengan `nano .env`) agar **sama persis** dengan laptop.

## Cek sensor sebelum MQTT

```bash
python -m scripts.check_sensors --role meja      # di HP A
python -m scripts.check_sensors --role pribadi   # di HP B
```

- **HP A:** tutup sensor cahaya dengan tangan, nilai `lux` harus turun. Ketuk-ketuk meja, nilai `desk_rms` harus naik.
- **HP B:** telungkupkan HP, nilai `telungkup=True` harus muncul. Balik HP, nilainya harus `False`.

Catat angkanya untuk kalibrasi `.env` di laptop (`LUX_LOW`, `DESK_ACTIVE_RMS`).

## Jalankan

**HP A (meja, layar menghadap ke atas, jangan tertutup buku):**
```bash
python hp_meja.py
```

**HP B (pribadi, ditelungkupkan di meja):**
```bash
python hp_pribadi.py
```

**Laptop:**
```bash
python detector.py
```

Lalu buka **http://localhost:8000** dan tekan **START**.

Untuk melihat data mentah saat MQTT berjalan, tambahkan `--debug-sensors`.

## Masalah umum

- **Output sensor kosong:** pastikan *aplikasi* Termux:API (bukan hanya paket `termux-api`) terpasang, lalu cek izinnya di pengaturan Android.
- **HP B tidak pernah `telungkup=True`:** sebagian HP melaporkan proximity dengan angka lain. Lihat nilai `proximity` di `check_sensors` saat HP tertelungkup, lalu ubah `PROXIMITY_NEAR_CM` di `shared/processing.py` kalau perlu.
- **Pembacaan berhenti saat layar mati:** matikan battery saver untuk Termux, atau jalankan `termux-wake-lock`.
- **Suara tidak keluar di HP A:** cek bahwa mesin text-to-speech Android terpasang dan volume media tidak nol. Coba `termux-tts-speak "halo"`.
- **Status `MENUNGGU`:** salah satu HP belum mengirim data. Cek `PROJECT_ID` dan koneksi internet di kedua HP.
