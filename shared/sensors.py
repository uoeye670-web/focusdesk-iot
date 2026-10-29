"""Where raw physical sensor values come from.

'--source android'   calls the real Termux:API sensors on Android.
'--source simulator' runs on any laptop (for practice only, NOT a physical edge).

HP A (desk)  reads: light + accelerometer  -> DeskSample
HP B (phone) reads: proximity + accelerometer -> PhoneSample
The processing logic never needs to know which source generated the readings.
"""

import json
import random
import re
import shutil
import subprocess
import time
from typing import Protocol

from shared.processing import DeskSample, PhoneSample

BURST_SIZE = 10
BURST_DELAY_MS = 20

SIM_ACTIVE_FROM_S = 3
SIM_ACTIVE_UNTIL_S = 12


class SensorSource(Protocol):
    def read(self) -> DeskSample | PhoneSample: ...


# ---------- simulator (laptop) ----------

class DeskSimulator:
    """Scenarios: belajar (writing, good light), gelap (lights go off), melamun (desk still)."""

    def __init__(self, scenario: str = "belajar", seed: int = 42):
        self.scenario = scenario
        self.started = time.monotonic()
        self.random = random.Random(seed)

    def read(self) -> DeskSample:
        elapsed = time.monotonic() - self.started
        dark = self.scenario == "gelap" and elapsed >= SIM_ACTIVE_FROM_S
        lux = (60 if dark else 450) + self.random.gauss(0, 8)
        vibration = 0.0 if self.scenario == "melamun" else 0.25
        acceleration = (
            self.random.gauss(0, 0.02),
            self.random.gauss(0, 0.02),
            9.81 + self.random.gauss(0, vibration) + self.random.gauss(0, 0.01),
        )
        return DeskSample(time.monotonic(), max(0.0, lux), acceleration)


class PhoneSimulator:
    """Scenarios: telungkup (always face down), diangkat (picked up between 3-12 s)."""

    def __init__(self, scenario: str = "telungkup", seed: int = 7):
        self.scenario = scenario
        self.started = time.monotonic()
        self.random = random.Random(seed)

    def read(self) -> PhoneSample:
        elapsed = time.monotonic() - self.started
        held = self.scenario == "diangkat" and SIM_ACTIVE_FROM_S <= elapsed <= SIM_ACTIVE_UNTIL_S
        noise = lambda scale: self.random.gauss(0, scale)
        if held:
            return PhoneSample(time.monotonic(), 5.0, (noise(0.4), 6.5 + noise(0.4), 7.0 + noise(0.4)))
        return PhoneSample(time.monotonic(), 0.0, (noise(0.03), noise(0.03), -9.81 + noise(0.03)))


# ---------- Android (Termux:API) ----------

TERMUX_API_HELP = (
    "termux-sensor -l tidak mengembalikan data, jadi aplikasi Termux:API belum bisa dipakai. Cek:\n"
    "  1. Aplikasi Termux:API terpasang dari sumber yang SAMA dengan Termux (keduanya dari F-Droid).\n"
    "  2. Buka aplikasi Termux:API sekali, lalu kembali ke Termux.\n"
    "  3. Izinkan Autostart / jalankan di latar belakang untuk Termux:API dan matikan penghemat baterainya\n"
    "     (Xiaomi, Oppo, Vivo, Realme sering memblokir ini).\n"
    "  4. Uji dengan: termux-battery-status  (harus keluar JSON), lalu: termux-sensor -l"
)


def _list_sensors() -> list[str]:
    if not shutil.which("termux-sensor"):
        raise RuntimeError("termux-sensor is missing. Install Termux:API and run: pkg install termux-api")
    # The first Termux:API call after boot can come back empty, so try twice.
    output = ""
    for attempt in range(2):
        try:
            output = subprocess.run(
                ["termux-sensor", "-l"], capture_output=True, text=True, timeout=15, check=False
            ).stdout.strip()
        except subprocess.TimeoutExpired:
            output = ""
        if output:
            break
        time.sleep(2)
    if not output:
        raise RuntimeError(TERMUX_API_HELP)
    try:
        names = json.loads(output)
    except ValueError as exc:
        raise RuntimeError(f"Output termux-sensor -l bukan JSON: {output[:300]}") from exc
    if isinstance(names, dict):
        names = names.get("sensors", [])
    if not isinstance(names, list):
        raise RuntimeError("Unexpected sensor listing. Run termux-sensor -l and inspect the result")
    return names


# Sensor names differ per phone: some report "BMI160 Accelerometer", others only
# the chip name plus a short suffix, e.g. "mxc4005xc_acc", "stk3335x_als", "stk3335x_ps".
# Each kind: (phrases searched in the whole name, short tokens matched as whole words).
SENSOR_KINDS = {
    "accelerometer": (("accelerometer", "acceleration sensor"), {"acc", "accel"}),
    "light": (("light", "lux"), {"als"}),
    "proximity": (("proximity",), {"prox", "ps"}),
}
# Derived or raw variants of a sensor that must never be picked.
EXCLUDED_TOKENS = {"uncalibrated", "uncali", "uncal", "linear", "raw"}


def _tokens(name: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", name.lower()) if token]


def find_sensor(names: list[str], kind: str) -> str | None:
    phrases, short_tokens = SENSOR_KINDS[kind]
    candidates = [name for name in names if not EXCLUDED_TOKENS & set(_tokens(name))]
    for name in candidates:
        if any(phrase in name.lower() for phrase in phrases):
            return name
    for name in candidates:
        if short_tokens & set(_tokens(name)):
            return name
    return None


def parse_json_objects(output: str) -> list[dict]:
    """termux-sensor may print one JSON object or several back to back."""
    decoder = json.JSONDecoder()
    objects, index = [], 0
    while True:
        while index < len(output) and output[index].isspace():
            index += 1
        if index >= len(output):
            return objects
        value, index = decoder.raw_decode(output, index)
        if isinstance(value, dict):
            objects.append(value)


class _TermuxPair:
    """Reads two sensors in one termux-sensor call: one scalar + the accelerometer."""

    def __init__(self, scalar_label: str):
        names = _list_sensors()
        self.scalar_name = find_sensor(names, scalar_label)
        self.accel_name = find_sensor(names, "accelerometer")
        if not self.scalar_name or not self.accel_name:
            raise RuntimeError(
                f"Sensor {scalar_label} + accelerometer belum terdeteksi. Daftar: {names}. "
                "Pastikan kedua sensor ada di HP dan Termux:API terpasang."
            )
        print(f"[SENSOR] {scalar_label.capitalize()}: {self.scalar_name}")
        print(f"[SENSOR] Accelerometer: {self.accel_name}")
        # Last known value of each sensor. Light and proximity sensors only report
        # when their value changes, so a single termux-sensor call often returns
        # just one of the two sensors.
        self.last_scalar: float | None = None
        self.last_accel: tuple[float, float, float] | None = None
        # One termux-sensor call costs hundreds of milliseconds, so readings are
        # fetched in bursts and handed out one by one from this buffer.
        self.buffer: list[tuple[float, tuple[float, float, float]]] = []

    def _run_termux_sensor(self) -> str:
        # A burst of BURST_SIZE readings, BURST_DELAY_MS apart: dense enough to
        # catch the short taps of a pen that one reading per call would miss.
        try:
            return subprocess.run(
                [
                    "termux-sensor", "-s", f"{self.scalar_name},{self.accel_name}",
                    "-d", str(BURST_DELAY_MS), "-n", str(BURST_SIZE),
                ],
                capture_output=True, text=True, timeout=15, check=True,
            ).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                "Termux:API gagal membaca sensor. Uji: termux-sensor -l "
                "dan termux-sensor -a -d 100 -n 1; cek instalasi/izin Termux:API."
            ) from exc

    def _readings_from(self, output: str) -> list[tuple[float, tuple[float, float, float]]]:
        """One reading per accelerometer value; a missing sensor keeps its last value."""
        readings = []
        for data in parse_json_objects(output):
            if self.scalar_name in data:
                self.last_scalar = float(data[self.scalar_name]["values"][0])
            if self.accel_name in data:
                accel = tuple(float(v) for v in data[self.accel_name]["values"][:3])
                if len(accel) != 3:
                    raise ValueError("Accelerometer must provide three axes")
                self.last_accel = accel
                if self.last_scalar is not None:
                    readings.append((self.last_scalar, accel))
        if not readings and self.last_scalar is not None and self.last_accel is not None:
            readings.append((self.last_scalar, self.last_accel))
        return readings

    def _read_pair(self) -> tuple[float, tuple[float, float, float]]:
        output = ""
        for attempt in range(5):
            if self.buffer:
                return self.buffer.pop(0)
            output = self._run_termux_sensor()
            try:
                self.buffer = self._readings_from(output)
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                raise RuntimeError(f"Cannot read Termux sensor output: {output[:300]}") from exc
        if self.buffer:
            return self.buffer.pop(0)
        missing = self.scalar_name if self.last_scalar is None else self.accel_name
        raise RuntimeError(f"Sensor {missing} belum mengirim data. Output terakhir: {output[:300]}")


class AndroidDesk(_TermuxPair):
    def __init__(self):
        super().__init__("light")

    def read(self) -> DeskSample:
        lux, accel = self._read_pair()
        return DeskSample(time.monotonic(), lux, accel)


class AndroidPhone(_TermuxPair):
    def __init__(self):
        super().__init__("proximity")

    def read(self) -> PhoneSample:
        proximity, accel = self._read_pair()
        return PhoneSample(time.monotonic(), proximity, accel)


DESK_SCENARIOS = ("belajar", "gelap", "melamun")
PHONE_SCENARIOS = ("telungkup", "diangkat")


def select_source(role: str, name: str, scenario: str | None) -> SensorSource:
    if role not in ("desk", "phone"):
        raise ValueError(f"Unknown role: {role}")
    if name == "android":
        return AndroidDesk() if role == "desk" else AndroidPhone()
    if name == "simulator":
        if role == "desk":
            return DeskSimulator(scenario or "belajar")
        return PhoneSimulator(scenario or "telungkup")
    raise ValueError(f"Unknown sensor source: {name}")
