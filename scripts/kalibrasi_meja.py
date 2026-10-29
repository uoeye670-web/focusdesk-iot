"""Measure the desk on HP A and suggest DESK_ACTIVE_RMS for the laptop .env.

Run on HP A (Termux), with the phone lying flat on the desk, screen up:
    python -m scripts.kalibrasi_meja

Phase 1: do not touch the desk. Phase 2: write or type as usual.
The suggested threshold sits just above the still desk's highest value, so a
still desk never counts as active while the spikes of writing do.
Does NOT require MQTT or .env.
"""

import argparse
import statistics
import time

from shared.processing import extract_desk_features
from shared.sensors import BURST_SIZE, AndroidDesk


def measure(source: AndroidDesk, seconds: float, label: str) -> tuple[list[float], list[float]]:
    rms_values, lux_values = [], []
    end = time.monotonic() + seconds
    first = True
    while time.monotonic() < end:
        features = extract_desk_features([source.read() for _ in range(BURST_SIZE)])
        left = max(0, round(end - time.monotonic()))
        if first:
            # The hand is often still moving away right after the countdown.
            first = False
            print(f"  [{label}] desk_rms={features.desk_rms:.4f}  (window pertama diabaikan)", flush=True)
            continue
        rms_values.append(features.desk_rms)
        lux_values.append(features.lux_avg)
        print(f"  [{label}] desk_rms={features.desk_rms:.4f}  lux={features.lux_avg:.0f}  (sisa {left} dtk)", flush=True)
    return rms_values, lux_values


def countdown(message: str, seconds: int = 3):
    print(f"\n{message}", flush=True)
    for number in range(seconds, 0, -1):
        print(f"  {number}...", flush=True)
        time.sleep(1)


def main():
    parser = argparse.ArgumentParser(description="Kalibrasi getaran meja untuk HP A")
    parser.add_argument("--detik", type=float, default=15, help="Lama tiap tahap (detik)")
    args = parser.parse_args()

    print("[KALIBRASI] HP A harus terlentang dan rata di meja. Lepaskan tangan dari HP.")
    source = AndroidDesk()

    countdown("TAHAP 1: JANGAN SENTUH MEJA sampai tahap ini selesai.")
    still, lux_values = measure(source, args.detik, "DIAM")

    countdown("TAHAP 2: MULAI MENULIS atau MENGETIK seperti biasa sampai tahap ini selesai.")
    writing, more_lux = measure(source, args.detik, "MENULIS")
    lux_values += more_lux

    # The accelerometer's own noise means writing and a still desk have similar
    # averages, but writing produces spikes the still desk never reaches. So the
    # threshold sits just above the highest still value, and the detector treats
    # the desk as active while one spike happened in the last few seconds.
    threshold = round(max(still) * 1.05, 4)
    hits = sum(value >= threshold for value in writing)
    hit_rate = hits / len(writing)
    windows_per_second = len(writing) / args.detik
    print("\n[HASIL]")
    print(f"  Meja diam    : median {statistics.median(still):.4f}, tertinggi {max(still):.4f}")
    print(f"  Saat menulis : median {statistics.median(writing):.4f}, tertinggi {max(writing):.4f}")
    print(f"  Lonjakan saat menulis di atas {threshold}: {hits} dari {len(writing)} window ({hit_rate:.0%})")
    print(f"  Cahaya rata-rata: {statistics.mean(lux_values):.0f} lux")

    if hits == 0 or hit_rate * windows_per_second * 15 < 1:
        print("\n[PERINGATAN] Saat menulis hampir tidak ada lonjakan di atas getaran meja diam.")
        print("  Coba letakkan HP lebih dekat ke tangan yang menulis, di meja yang tidak terlalu tebal,")
        print("  lalu ulangi kalibrasi. Bisa juga menulis sedikit lebih kuat.")
        return

    print(f"\n  Rata-rata {hit_rate * windows_per_second * 15:.0f} lonjakan per 15 detik saat menulis: cukup untuk")
    print("  dianggap meja aktif, sedangkan meja diam tidak pernah melewati ambang ini.")
    print("\nTulis baris ini di file .env LAPTOP (bukan di HP), lalu jalankan ulang detector:")
    print(f"\n    DESK_ACTIVE_RMS={threshold}\n")


if __name__ == "__main__":
    main()
