"""NODE 3: FocusDesk algorithm (pure Python, no MQTT dependency).

Sensor fusion of two edges into a focus score + Pomodoro state machine.
Make changes here when experimenting with thresholds or a new AI model.
Time always comes in as `now_ms`, so tests can replay a whole session instantly.
"""

from collections import deque
from dataclasses import dataclass
import os

from shared.messages import DeskTelemetry, PhoneTelemetry, Telemetry

WEIGHT_PHONE = 0.45
WEIGHT_DESK = 0.35
WEIGHT_LIGHT = 0.20


@dataclass(frozen=True)
class FocusConfig:
    focus_minutes: float = 25
    break_minutes: float = 5
    # Classic Pomodoro: every 4th focus session is followed by a long break.
    long_break_minutes: float = 15
    pomodoros_per_set: int = 4
    lux_low: float = 300
    lux_high: float = 1500
    desk_active_rms: float = 0.08
    idle_seconds: float = 180
    # A cheap accelerometer is noisy, so the average vibration of writing is close
    # to a still desk. Writing does produce short spikes above the noise, so the
    # desk counts as active while one spike happened within the last few seconds.
    desk_recent_seconds: float = 15
    bad_light_seconds: float = 30
    edge_timeout_seconds: float = 15
    score_window_seconds: float = 60
    distraction_alert_every_s: float = 15
    reminder_every_s: float = 60

    @staticmethod
    def from_env() -> "FocusConfig":
        """Thresholds can be calibrated in .env without touching the code."""
        names = {
            "focus_minutes": "FOCUS_MINUTES", "break_minutes": "BREAK_MINUTES",
            "long_break_minutes": "LONG_BREAK_MINUTES", "pomodoros_per_set": "POMODOROS_PER_SET",
            "lux_low": "LUX_LOW", "lux_high": "LUX_HIGH",
            "desk_active_rms": "DESK_ACTIVE_RMS", "idle_seconds": "IDLE_SECONDS",
        }
        values = {}
        for field, env_name in names.items():
            raw = os.getenv(env_name, "").strip()
            if raw:
                values[field] = int(raw) if field == "pomodoros_per_set" else float(raw)
                if values[field] <= 0:
                    raise ValueError(f"{env_name} must be positive")
        return FocusConfig(**values)


@dataclass(frozen=True)
class Alert:
    target: str  # "edge1" (HP meja, bersuara) or "edge2" (HP pribadi, bergetar)
    event: str
    message: str


@dataclass(frozen=True)
class Acceptance:
    accepted: bool
    reason: str


def light_level(lux: float, config: FocusConfig) -> str:
    if lux < config.lux_low:
        return "kurang"
    if lux > config.lux_high:
        return "silau"
    return "ideal"


def focus_score(held_ratio: float, desk_active: bool, lux: float, config: FocusConfig) -> float:
    """0-100: HP tidak dipegang (45%) + meja aktif (35%) + cahaya ideal (20%)."""
    light = 1.0 if light_level(lux, config) == "ideal" else 0.5
    return 100 * (WEIGHT_PHONE * (1 - held_ratio) + WEIGHT_DESK * float(desk_active) + WEIGHT_LIGHT * light)


def clock(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


class FocusDetector:
    def __init__(self, config: FocusConfig | None = None):
        self.config = config or FocusConfig()
        self.desk: DeskTelemetry | None = None
        self.phone: PhoneTelemetry | None = None
        self.seen_ms: dict[str, int] = {}
        self.last_seq: dict[tuple[str, str], int] = {}
        self.phase = "IDLE"  # IDLE, FOCUS, BREAK, PAUSED
        self.paused_from = "FOCUS"
        self.phase_left_s = 0.0
        self.cycle = 0  # focus session number within the whole study session
        self.completed_pomodoros = 0
        self.long_break = False
        self.status = "IDLE"
        self.reason = "Tekan START untuk memulai sesi belajar"
        self.last_tick_ms: int | None = None
        self._reset_session(0)

    def _reset_session(self, now_ms: int):
        self.pickups = 0
        self.held_seconds = 0.0
        self.focus_seconds = 0.0
        self.score_sum = 0.0
        self.score_count = 0
        self.scores: deque[tuple[int, float]] = deque()
        self.last_desk_active_ms = now_ms
        self.bad_light_since_ms: int | None = None
        self.last_alert_ms: dict[str, int] = {}

    # ---------- input: telemetry ----------

    def accept(self, reading: Telemetry, now_ms: int) -> Acceptance:
        if abs(now_ms - reading.sent_at_ms) > 30_000:
            return Acceptance(False, "REJECTED_STALE: timestamp outside the allowed 30-second window")
        key = (reading.device_id, reading.boot_id)
        if reading.sequence <= self.last_seq.get(key, -1):
            return Acceptance(False, "REJECTED_REPLAY: repeated/out-of-order sequence for this boot ID")
        self.last_seq[key] = reading.sequence
        self.seen_ms[reading.device_id] = now_ms

        if isinstance(reading, PhoneTelemetry):
            was_face_down = self.phone is not None and self.phone.face_down
            lifted = not reading.face_down or reading.held_ratio > 0
            if self.phase == "FOCUS" and was_face_down and lifted:
                self.pickups += 1
            self.phone = reading
        else:
            if reading.desk_rms >= self.config.desk_active_rms:
                self.last_desk_active_ms = now_ms
            self.desk = reading
        return Acceptance(True, "ok")

    # ---------- input: dashboard control ----------

    def control(self, command: str, now_ms: int) -> list[Alert]:
        command = command.strip().upper()
        if command not in ("START", "PAUSE", "STOP"):
            raise ValueError(f"Unknown control command: {command[:40]}")
        alerts = []
        if command == "START" and self.phase == "IDLE":
            self._reset_session(now_ms)
            self.phase, self.cycle = "FOCUS", 1
            self.completed_pomodoros, self.long_break = 0, False
            self.phase_left_s = self.config.focus_minutes * 60
            alerts.append(Alert("edge1", "SESSION_START",
                                f"Sesi fokus dimulai, {self.config.focus_minutes:g} menit. Telungkupkan HP kamu."))
        elif command == "START" and self.phase == "PAUSED":
            self.phase = self.paused_from
            alerts.append(Alert("edge1", "SESSION_RESUME", "Sesi dilanjutkan."))
        elif command == "PAUSE" and self.phase in ("FOCUS", "BREAK"):
            self.paused_from, self.phase = self.phase, "PAUSED"
        elif command == "STOP" and self.phase != "IDLE":
            self.phase = "IDLE"
            summary = self.summary()
            alerts.append(Alert("edge1", "SESSION_SUMMARY",
                                f"Sesi selesai. {summary['pomodoros']} pomodoro, fokus {summary['focus_minutes']:g} menit, "
                                f"{summary['pickups']} kali mengambil HP."))
        self.last_tick_ms = now_ms
        self._evaluate(now_ms, 0.0, alerts)
        return alerts

    # ---------- clock: called every second by main.py ----------

    def tick(self, now_ms: int) -> list[Alert]:
        dt = 0.0 if self.last_tick_ms is None else (now_ms - self.last_tick_ms) / 1000
        dt = min(max(dt, 0.0), 5.0)
        self.last_tick_ms = now_ms
        alerts: list[Alert] = []

        if self.phase in ("FOCUS", "BREAK"):
            self.phase_left_s -= dt
            if self.phase_left_s <= 0 and self.phase == "FOCUS":
                self.completed_pomodoros += 1
                self.long_break = self.completed_pomodoros % self.config.pomodoros_per_set == 0
                self.phase = "BREAK"
                if self.long_break:
                    self.phase_left_s = self.config.long_break_minutes * 60
                    message = (f"{self.config.pomodoros_per_set} pomodoro selesai. "
                               f"Istirahat panjang {self.config.long_break_minutes:g} menit.")
                else:
                    self.phase_left_s = self.config.break_minutes * 60
                    message = f"Pomodoro {self.pomodoro_in_set()} selesai. Istirahat {self.config.break_minutes:g} menit."
                alerts += [Alert("edge1", "BREAK", message), Alert("edge2", "BREAK", message)]
            elif self.phase_left_s <= 0:
                self.phase, self.cycle = "FOCUS", self.cycle + 1
                self.long_break = False
                self.phase_left_s = self.config.focus_minutes * 60
                self.last_desk_active_ms = now_ms
                alerts.append(Alert("edge1", "FOCUS",
                                    f"Istirahat selesai. Ayo mulai pomodoro {self.pomodoro_in_set()}."))

        self._evaluate(now_ms, dt, alerts)
        return alerts

    def pomodoro_in_set(self) -> int:
        """Position 1..pomodoros_per_set of the current (or just finished) focus session."""
        return (max(self.cycle, 1) - 1) % self.config.pomodoros_per_set + 1

    def _online(self, device_id: str, now_ms: int) -> bool:
        seen = self.seen_ms.get(device_id)
        return seen is not None and now_ms - seen <= self.config.edge_timeout_seconds * 1000

    def _desk_recently_active(self, now_ms: int) -> bool:
        return now_ms - self.last_desk_active_ms <= self.config.desk_recent_seconds * 1000

    def _alert_once_every(self, key: str, every_s: float, now_ms: int, alerts: list[Alert], alert: Alert):
        last = self.last_alert_ms.get(key)
        if last is None or now_ms - last >= every_s * 1000:
            self.last_alert_ms[key] = now_ms
            alerts.append(alert)

    def _set(self, status: str, reason: str):
        self.status, self.reason = status, reason

    def _evaluate(self, now_ms: int, dt: float, alerts: list[Alert]):
        if self.phase == "IDLE":
            return self._set("IDLE", "Tekan START untuk memulai sesi belajar")
        if self.phase == "PAUSED":
            return self._set("JEDA", "Sesi dijeda. Tekan START untuk melanjutkan")
        if self.phase == "BREAK":
            kind = "Istirahat panjang" if self.long_break else "Istirahat singkat"
            return self._set("ISTIRAHAT", f"{kind}, sisa {clock(self.phase_left_s)}")

        missing = [name for device, name in (("edge1", "HP meja"), ("edge2", "HP pribadi"))
                   if not self._online(device, now_ms)]
        if missing:
            return self._set("MENUNGGU", f"Menunggu data dari {' dan '.join(missing)}")

        desk, phone, config = self.desk, self.phone, self.config
        held_ratio = 1.0 if not phone.face_down else phone.held_ratio
        self.held_seconds += dt * held_ratio

        score = focus_score(held_ratio, self._desk_recently_active(now_ms), desk.lux_avg, config)
        self.scores.append((now_ms, score))
        while self.scores and now_ms - self.scores[0][0] > config.score_window_seconds * 1000:
            self.scores.popleft()
        self.score_sum += score
        self.score_count += 1

        light = light_level(desk.lux_avg, config)
        if light == "ideal":
            self.bad_light_since_ms = None
        elif self.bad_light_since_ms is None:
            self.bad_light_since_ms = now_ms
        bad_light = (self.bad_light_since_ms is not None
                     and now_ms - self.bad_light_since_ms >= config.bad_light_seconds * 1000)
        idle = now_ms - self.last_desk_active_ms >= config.idle_seconds * 1000
        left = clock(self.phase_left_s)

        if held_ratio >= 0.5:
            self._set("TERDISTRAKSI", "HP pribadi sedang dipegang saat sesi fokus")
            self._alert_once_every("distraction", config.distraction_alert_every_s, now_ms, alerts,
                                   Alert("edge2", "DISTRACTED", f"Sisa {left}. Taruh HP-nya dan lanjut belajar!"))
        elif bad_light:
            status = "CAHAYA_KURANG" if light == "kurang" else "CAHAYA_SILAU"
            self._set(status, f"Cahaya meja {desk.lux_avg:.0f} lux ({light})")
            message = "Nyalakan lampu meja." if light == "kurang" else "Cahaya terlalu silau, geser lampunya."
            self._alert_once_every("light", config.reminder_every_s, now_ms, alerts,
                                   Alert("edge1", status, message))
        elif idle:
            self._set("MELAMUN", f"Meja tidak ada aktivitas selama {config.idle_seconds:g} detik")
            self._alert_once_every("idle", config.reminder_every_s, now_ms, alerts,
                                   Alert("edge1", "IDLE", f"Ayo lanjut belajar, sisa {left}."))
        else:
            self._set("FOKUS", "HP tertelungkup, meja aktif, cahaya cukup")
            self.focus_seconds += dt

    # ---------- output: dashboard ----------

    def current_score(self) -> float | None:
        if not self.scores:
            return None
        return round(sum(score for _, score in self.scores) / len(self.scores), 1)

    def summary(self) -> dict:
        return {
            "pickups": self.pickups,
            "held_seconds": round(self.held_seconds),
            "focus_minutes": round(self.focus_seconds / 60, 1),
            "avg_score": round(self.score_sum / self.score_count, 1) if self.score_count else None,
            "pomodoros": self.completed_pomodoros,
        }

    def snapshot(self, now_ms: int) -> dict:
        desk, phone = self.desk, self.phone
        return {
            "status": self.status,
            "reason": self.reason,
            "phase": self.phase,
            "cycle": self.cycle,
            "pomodoro": {
                "in_set": self.pomodoro_in_set() if self.cycle else 0,
                "per_set": self.config.pomodoros_per_set,
                "completed": self.completed_pomodoros,
                "long_break": self.long_break,
            },
            "phase_left_s": max(0, round(self.phase_left_s)),
            "focus_score": self.current_score() if self.phase == "FOCUS" else None,
            "session": self.summary(),
            "desk": None if desk is None else {
                "online": self._online("edge1", now_ms),
                "lux_avg": desk.lux_avg,
                "light_level": light_level(desk.lux_avg, self.config),
                "desk_rms": desk.desk_rms,
                "active": self._desk_recently_active(now_ms),
            },
            "phone": None if phone is None else {
                "online": self._online("edge2", now_ms),
                "face_down": phone.face_down,
                "held_ratio": phone.held_ratio,
                "motion_rms": phone.motion_rms,
            },
            "config": {
                "focus_minutes": self.config.focus_minutes,
                "break_minutes": self.config.break_minutes,
                "long_break_minutes": self.config.long_break_minutes,
                "pomodoros_per_set": self.config.pomodoros_per_set,
                "lux_low": self.config.lux_low,
                "lux_high": self.config.lux_high,
                "desk_active_rms": self.config.desk_active_rms,
            },
            "at_ms": now_ms,
        }
