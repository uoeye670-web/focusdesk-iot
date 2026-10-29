"""DATA PROCESSING on the edge devices.

HP A (edge1, stasiun meja):
  Processing A1: rata-rata cahaya (lux) per window.
  Processing A2: RMS getaran meja, tanda sedang menulis/mengetik.

HP B (edge2, HP pribadi):
  Processing B1: posisi tertelungkup = proximity dekat + sumbu z accelerometer
                 negatif; menghasilkan rasio waktu HP dipegang.
  Processing B2: RMS gerakan HP, seberapa aktif HP sedang dipakai.

Only these features are sent to MQTT, never the raw samples.
"""

from dataclasses import dataclass
from math import sqrt

# Layar menghadap meja: gravitasi terbaca di sumbu z negatif (≈ -9,8 m/s²).
FACE_DOWN_Z = -7.0
# Kebanyakan HP melaporkan proximity 0 cm (dekat) atau 5–8 cm (jauh).
PROXIMITY_NEAR_CM = 3.0


@dataclass(frozen=True)
class DeskSample:
    seconds: float
    lux: float
    acceleration: tuple[float, float, float]


@dataclass(frozen=True)
class PhoneSample:
    seconds: float
    proximity_cm: float
    acceleration: tuple[float, float, float]


@dataclass(frozen=True)
class DeskFeatures:
    lux_avg: float
    desk_rms: float


@dataclass(frozen=True)
class PhoneFeatures:
    face_down: bool
    held_ratio: float
    motion_rms: float


def _vibration_rms(accelerations: list[tuple[float, float, float]]) -> float:
    """RMS of each axis around its own window mean, combined over x, y and z.

    Writing shakes the desk mostly sideways (x, y). Those small sideways jolts
    barely change the total magnitude, which gravity dominates, so every axis
    is measured on its own. Subtracting the window mean (instead of 9.81)
    removes each phone's calibration offset and its tilt on the desk.
    """
    count = len(accelerations)
    total = 0.0
    for axis in range(3):
        values = [a[axis] for a in accelerations]
        mean = sum(values) / count
        total += sum((v - mean) ** 2 for v in values) / count
    return sqrt(total)


def is_face_down(sample: PhoneSample, near_cm: float = PROXIMITY_NEAR_CM) -> bool:
    return sample.proximity_cm < near_cm and sample.acceleration[2] <= FACE_DOWN_Z


def extract_desk_features(samples: list[DeskSample]) -> DeskFeatures:
    if len(samples) < 2:
        raise ValueError("At least 2 sensor samples are required")

    lux_avg = sum(sample.lux for sample in samples) / len(samples)
    desk_rms = _vibration_rms([sample.acceleration for sample in samples])
    return DeskFeatures(lux_avg=round(lux_avg, 1), desk_rms=round(desk_rms, 4))


def extract_phone_features(samples: list[PhoneSample], near_cm: float = PROXIMITY_NEAR_CM) -> PhoneFeatures:
    if len(samples) < 2:
        raise ValueError("At least 2 sensor samples are required")

    held = [not is_face_down(sample, near_cm) for sample in samples]
    held_ratio = sum(held) / len(held)
    motion_rms = _vibration_rms([sample.acceleration for sample in samples])
    return PhoneFeatures(
        face_down=not held[-1],
        held_ratio=round(held_ratio, 3),
        motion_rms=round(motion_rms, 4),
    )
