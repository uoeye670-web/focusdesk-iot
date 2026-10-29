"""MQTT message schema: the contract between the two edge nodes and detector.

edge1 (HP meja)    -> DeskTelemetry  {lux_avg, desk_rms}
edge2 (HP pribadi) -> PhoneTelemetry {face_down, held_ratio, motion_rms}
"""

from dataclasses import asdict, dataclass
import json
import math
import time


@dataclass(frozen=True)
class DeskTelemetry:
    device_id: str
    boot_id: str
    sequence: int
    sent_at_ms: int
    lux_avg: float
    desk_rms: float

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def make(boot_id: str, sequence: int, lux_avg: float, desk_rms: float) -> "DeskTelemetry":
        return DeskTelemetry("edge1", boot_id, sequence, int(time.time() * 1000), lux_avg, desk_rms)


@dataclass(frozen=True)
class PhoneTelemetry:
    device_id: str
    boot_id: str
    sequence: int
    sent_at_ms: int
    face_down: bool
    held_ratio: float
    motion_rms: float

    def to_json(self) -> str:
        return json.dumps(asdict(self))

    @staticmethod
    def make(boot_id: str, sequence: int, face_down: bool, held_ratio: float,
             motion_rms: float) -> "PhoneTelemetry":
        return PhoneTelemetry("edge2", boot_id, sequence, int(time.time() * 1000),
                              face_down, held_ratio, motion_rms)


Telemetry = DeskTelemetry | PhoneTelemetry


def _number(value: dict, key: str, maximum: float = math.inf) -> float:
    number = value.get(key)
    if type(number) not in (float, int) or not math.isfinite(number) or not 0 <= number <= maximum:
        raise ValueError(f"Invalid {key}")
    return float(number)


def parse_telemetry(payload: str | bytes) -> Telemetry:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Telemetry must be a JSON object")
    for key in ("device_id", "boot_id"):
        if not isinstance(value.get(key), str) or not value[key]:
            raise ValueError(f"Invalid {key}")
    sequence = value.get("sequence")
    timestamp = value.get("sent_at_ms")
    if type(sequence) is not int or sequence < 0:
        raise ValueError("Invalid sequence")
    if type(timestamp) is not int or timestamp < 0:
        raise ValueError("Invalid timestamp")

    header = (value["device_id"], value["boot_id"], sequence, timestamp)
    if value["device_id"] == "edge1":
        return DeskTelemetry(*header, _number(value, "lux_avg"), _number(value, "desk_rms"))
    if value["device_id"] == "edge2":
        if type(value.get("face_down")) is not bool:
            raise ValueError("Invalid face_down")
        return PhoneTelemetry(*header, value["face_down"], _number(value, "held_ratio", maximum=1.0),
                              _number(value, "motion_rms"))
    raise ValueError("Unknown edge device")


def alert_json(event: str, message: str, now_ms: int | None = None) -> str:
    """Short command for one phone: vibrate/notify (edge2) or speak (edge1)."""
    return json.dumps({
        "event": event,
        "message": message,
        "at_ms": now_ms if now_ms is not None else int(time.time() * 1000),
    })
