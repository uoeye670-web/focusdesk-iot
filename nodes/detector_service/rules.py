"""NODE 3: FocusDesk algorithm (pure Python, no MQTT dependency).

Adaptive Pomodoro driven by sensor fusion of two edges:
  - flipping HP B face down starts (or resumes) a focus session by itself,
  - taking HP B away for longer than AWAY_SECONDS pauses the timer by itself,
  - the focus score of each finished pomodoro sets how long the next break is.
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

# Adaptive break: (minimum focus score of the finished pomodoro, break multiplier).
# A distracted pomodoro is a sign of fatigue, so the following break is longer.
ADAPTIVE_BREAK = ((80, 1.0), (60, 1.4), (0, 1.8))
HISTORY_LENGTH = 12


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
    # HP B face down this long starts or resumes a session automatically.
    auto_start_seconds: float = 3
    # HP B taken away (not face down) this long pauses the focus timer automatically.
    away_seconds: float = 60
    adaptive_break: bool = True

    @staticmethod
    def from_env() -> "FocusConfig":
        """Thresholds can be calibrated in .env without touching the code."""
        names = {
            "focus_minutes": "FOCUS_MINUTES", "break_minutes": "BREAK_MINUTES",
            "long_break_minutes": "LONG_BREAK_MINUTES", "pomodoros_per_set": "POMODOROS_PER_SET",
            "lux_low": "LUX_LOW", "lux_high": "LUX_HIGH",
            "desk_active_rms": "DESK_ACTIVE_RMS", "idle_seconds": "IDLE_SECONDS",
            "away_seconds": "AWAY_SECONDS",
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


def break_multiplier(pomodoro_score: float | None) -> float:
    """How much longer the break gets after a pomodoro with this average focus score."""
    if pomodoro_score is None:
        return 1.0
    return next(factor for minimum, factor in ADAPTIVE_BREAK if pomodoro_score >= minimum)


def focus_score(held_ratio: float, desk_active: bool, lux: float, config: FocusConfig) -> float:
    """0-100: HP tidak dipegang (45%) + meja aktif (35%) + cahaya ideal (20%)."""
    light = 1.0 if light_level(lux, config) == "ideal" else 0.5
    return 100 * (WEIGHT_PHONE * (1 - held_ratio) + WEIGHT_DESK * float(desk_active) + WEIGHT_LIGHT * light)


def duration_text(minutes: float) -> str:
    """7 -> "7 menit", 1.4 -> "1 menit 24 detik" (spoken by HP A)."""
    whole = int(minutes)
    seconds = round((minutes - whole) * 60)
    if seconds == 0:
        return f"{whole} menit"
    return f"{whole} menit {seconds} detik" if whole else f"{seconds} detik"


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
        self.phase_total_s = 0.0
        self.auto_paused = False
        # After STOP the phone usually still lies face down; it must be lifted once
        # before flipping it starts a new session, or STOP would undo itself.
        self.auto_start_armed = True
        self.phone_down_since_ms: int | None = None
        self.phone_up_since_ms: int | None = None
        self.status = "IDLE"
        self.reason = "Telungkupkan HP B untuk memulai, atau tekan START"
        self.last_tick_ms: int | None = None
        self._reset_session(0)

    def _reset_session(self, now_ms: int):
        self.history: list[dict] = []
        self.pickups = 0
        self.held_seconds = 0.0
        self.focus_seconds = 0.0
        self.score_sum = 0.0
        self.score_count = 0
        self.scores: deque[tuple[int, float]] = deque()
        self.last_desk_active_ms = now_ms
        self.bad_light_since_ms: int | None = None
        self.last_alert_ms: dict[str, int] = {}
        self._reset_pomodoro()

    def _reset_pomodoro(self):
        self.pomodoro_score_sum = 0.0
        self.pomodoro_score_count = 0
        self.pomodoro_start_pickups = self.pickups

    def _phone_down(self) -> bool:
        return self.phone is not None and self.phone.face_down and self.phone.held_ratio < 0.5

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
            if self._phone_down():
                self.phone_up_since_ms = None
                if self.phone_down_since_ms is None:
                    self.phone_down_since_ms = now_ms
            else:
                self.phone_down_since_ms = None
                self.auto_start_armed = True
                if self.phone_up_since_ms is None:
                    self.phone_up_since_ms = now_ms
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
            alerts.append(self._start_session(now_ms, automatic=False))
        elif command == "START" and self.phase == "PAUSED":
            alerts.append(self._resume("Sesi dilanjutkan."))
        elif command == "PAUSE" and self.phase in ("FOCUS", "BREAK"):
            self.paused_from, self.phase = self.phase, "PAUSED"
            self.auto_paused = False
        elif command == "STOP" and self.phase != "IDLE":
            self.phase = "IDLE"
            self.auto_paused = False
            self.auto_start_armed = False
            summary = self.summary()
            alerts.append(Alert("edge1", "SESSION_SUMMARY",
                                f"Sesi selesai. {summary['pomodoros']} pomodoro, fokus {summary['focus_minutes']:g} menit, "
                                f"{summary['pickups']} kali mengambil HP."))
        self.last_tick_ms = now_ms
        self._evaluate(now_ms, 0.0, alerts)
        return alerts

    def _start_session(self, now_ms: int, automatic: bool) -> Alert:
        self._reset_session(now_ms)
        self.phase, self.cycle = "FOCUS", 1
        self.completed_pomodoros, self.long_break, self.auto_paused = 0, False, False
        self._set_phase_length(self.config.focus_minutes * 60)
        how = "HP sudah ditelungkupkan. " if automatic else ""
        return Alert("edge1", "SESSION_START", f"{how}Pomodoro 1 dimulai, {self.config.focus_minutes:g} menit.")

    def _resume(self, message: str) -> Alert:
        self.phase, self.auto_paused = self.paused_from, False
        return Alert("edge1", "SESSION_RESUME", message)

    def _set_phase_length(self, seconds: float):
        self.phase_left_s = self.phase_total_s = seconds

    # ---------- clock: called every second by main.py ----------

    def tick(self, now_ms: int) -> list[Alert]:
        dt = 0.0 if self.last_tick_ms is None else (now_ms - self.last_tick_ms) / 1000
        dt = min(max(dt, 0.0), 5.0)
        self.last_tick_ms = now_ms
        alerts: list[Alert] = []

        self._automatic_start_pause(now_ms, alerts)
        if self.phase in ("FOCUS", "BREAK"):
            self.phase_left_s -= dt
            if self.phase_left_s <= 0 and self.phase == "FOCUS":
                alerts += self._finish_pomodoro()
            elif self.phase_left_s <= 0:
                self.phase, self.cycle = "FOCUS", self.cycle + 1
                self.long_break = False
                self._set_phase_length(self.config.focus_minutes * 60)
                self.last_desk_active_ms = now_ms
                self._reset_pomodoro()
                alerts.append(Alert("edge1", "FOCUS",
                                    f"Istirahat selesai. Ayo mulai pomodoro {self.pomodoro_in_set()}."))

        self._evaluate(now_ms, dt, alerts)
        return alerts

    def _automatic_start_pause(self, now_ms: int, alerts: list[Alert]):
        """The phone itself is the Pomodoro switch: face down = study, taken away = pause."""
        config = self.config
        down_for = 0 if self.phone_down_since_ms is None else (now_ms - self.phone_down_since_ms) / 1000
        up_for = 0 if self.phone_up_since_ms is None else (now_ms - self.phone_up_since_ms) / 1000
        both_online = self._online("edge1", now_ms) and self._online("edge2", now_ms)

        if self.phase == "IDLE" and self.auto_start_armed and both_online and down_for >= config.auto_start_seconds:
            alerts.append(self._start_session(now_ms, automatic=True))
        elif self.phase == "PAUSED" and self.auto_paused and down_for >= config.auto_start_seconds:
            alerts.append(self._resume("Selamat datang kembali. Pomodoro dilanjutkan."))
        elif self.phase == "FOCUS" and self._online("edge2", now_ms) and up_for >= config.away_seconds:
            self.paused_from, self.phase, self.auto_paused = "FOCUS", "PAUSED", True
            alerts.append(Alert("edge1", "AWAY",
                                "HP dibawa pergi, timer dijeda. Telungkupkan lagi HP-nya untuk melanjutkan."))

    def _finish_pomodoro(self) -> list[Alert]:
        """End of a focus session: record its score and size the break to match it."""
        self.completed_pomodoros += 1
        self.long_break = self.completed_pomodoros % self.config.pomodoros_per_set == 0
        score = (round(self.pomodoro_score_sum / self.pomodoro_score_count, 1)
                 if self.pomodoro_score_count else None)
        factor = break_multiplier(score) if self.config.adaptive_break else 1.0
        base = self.config.long_break_minutes if self.long_break else self.config.break_minutes
        break_minutes = round(base * factor, 2)
        self.history.append({
            "number": self.cycle,
            "score": score,
            "pickups": self.pickups - self.pomodoro_start_pickups,
            "break_minutes": break_minutes,
            "long_break": self.long_break,
        })
        del self.history[:-HISTORY_LENGTH]
        self.phase = "BREAK"
        self._set_phase_length(break_minutes * 60)

        score_text = f", skor {score:.0f}" if score is not None else ""
        kind = "Istirahat panjang" if self.long_break else "Istirahat"
        extra = " Istirahat diperpanjang karena banyak distraksi." if factor > 1 else ""
        message = f"Pomodoro {self.pomodoro_in_set()} selesai{score_text}. {kind} {duration_text(break_minutes)}.{extra}"
        return [Alert("edge1", "BREAK", message), Alert("edge2", "BREAK", message)]

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
            if not self.auto_start_armed:
                return self._set("IDLE", "Angkat lalu telungkupkan HP B untuk sesi baru, atau tekan START")
            return self._set("IDLE", "Telungkupkan HP B untuk memulai, atau tekan START")
        if self.phase == "PAUSED" and self.auto_paused:
            return self._set("DITINGGAL", "HP B dibawa pergi. Telungkupkan lagi untuk melanjutkan")
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
        self.pomodoro_score_sum += score
        self.pomodoro_score_count += 1

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
            up_for = 0 if self.phone_up_since_ms is None else (now_ms - self.phone_up_since_ms) / 1000
            pause_in = max(0, round(config.away_seconds - up_for))
            self._set("TERDISTRAKSI", f"HP pribadi dipegang. Timer dijeda otomatis dalam {pause_in} detik")
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
            "phase_total_s": round(self.phase_total_s),
            "auto": {
                "paused": self.auto_paused,
                "start_armed": self.auto_start_armed,
                "away_seconds": self.config.away_seconds,
                "adaptive_break": self.config.adaptive_break,
            },
            "history": self.history,
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
