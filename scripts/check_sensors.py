"""Sensor-only diagnostic. Does NOT require an MQTT broker or .env.

Run this on Android Termux:
    python -m scripts.check_sensors --role meja      (HP A: light + accelerometer)
    python -m scripts.check_sensors --role pribadi   (HP B: proximity + accelerometer)

While values print: cover/uncover the light sensor, tap the desk, flip the phone.
Use the printed numbers to calibrate LUX_LOW and DESK_ACTIVE_RMS in .env.
"""

import argparse
import time

from shared.processing import extract_desk_features, extract_phone_features, is_face_down
from shared.sensors import AndroidDesk, AndroidPhone


def main():
    parser = argparse.ArgumentParser(description="Check FocusDesk Android sensors")
    parser.add_argument("--role", choices=["meja", "pribadi"], required=True)
    parser.add_argument("--readings", type=int, default=12)
    args = parser.parse_args()
    if args.readings < 2:
        parser.error("--readings must be >= 2")

    print("[CHECK] Starting Termux:API sensor test; NO MQTT required.", flush=True)
    source = AndroidDesk() if args.role == "meja" else AndroidPhone()
    samples = []
    for number in range(args.readings):
        reading = source.read()
        samples.append(reading)
        accel = tuple(round(v, 3) for v in reading.acceleration)
        if args.role == "meja":
            print(f"[CHECK] {number + 1}/{args.readings} lux={reading.lux:.1f} accel={accel}", flush=True)
        else:
            print(
                f"[CHECK] {number + 1}/{args.readings} proximity={reading.proximity_cm:.1f} cm "
                f"accel={accel} telungkup={is_face_down(reading)}",
                flush=True,
            )
        if number < args.readings - 1:
            time.sleep(0.1)

    if args.role == "meja":
        features = extract_desk_features(samples)
        print(f"[PROCESSING] lux_avg={features.lux_avg:.1f} desk_rms={features.desk_rms:.4f} m/s²")
    else:
        features = extract_phone_features(samples)
        print(
            f"[PROCESSING] face_down={features.face_down} held_ratio={features.held_ratio:.2f} "
            f"motion_rms={features.motion_rms:.4f} m/s²"
        )
    print("[CHECK] If values reacted to light/motion/flipping, the Android sensor path works.")


if __name__ == "__main__":
    main()
