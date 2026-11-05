"""NODE 3: machine learning that learns the best focus duration per user.

Contextual multi-armed bandit with Thompson Sampling:
  arm     = a focus duration, e.g. 15, 25, 35 or 45 minutes
  context = how difficult the material is (mudah, sedang, sulit)
  reward  = how good a finished session was (user rating + sensor focus score)

Every session teaches the model one thing. Durations that are still uncertain get
tried now and then, durations that keep scoring well get picked more often.
Pure Python with no MQTT dependency, so tests can replay many sessions instantly.
"""

from dataclasses import asdict, dataclass
import json
import math
import os
from pathlib import Path
import random
import re

DIFFICULTIES = ("mudah", "sedang", "sulit")
DEFAULT_DIFFICULTY = "sedang"
DEFAULT_OPTIONS = (15.0, 25.0, 35.0, 45.0)

WEIGHT_RATING = 0.5        # half user rating, half sensor score; sensor only when not rated
REWARD_SIGMA = 0.2         # expected session-to-session noise of the reward
PRIOR_STRENGTH = 1.0       # how many sessions the prior counts as
NEUTRAL_REWARD = 0.5       # belief about a duration nobody has tried in any difficulty
RECENCY_DECAY = 0.97       # a session one newer weighs 3% more, because habits change
CONFIDENCE_MEDIUM = 3
CONFIDENCE_HIGH = 8

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


@dataclass(frozen=True)
class SessionRecord:
    difficulty: str
    minutes: float
    sensor_score: float | None
    rating: int | None  # 1..5, None when the user skipped the question
    at_ms: int


def session_quality(sensor_score: float | None, rating: int | None) -> float | None:
    """0..1: how good the session felt (rating) and looked (sensors)."""
    sensor = None if sensor_score is None else sensor_score / 100
    felt = None if rating is None else (rating - 1) / 4
    if sensor is None and felt is None:
        return None
    if sensor is None:
        return felt
    if felt is None:
        return sensor
    return WEIGHT_RATING * felt + (1 - WEIGHT_RATING) * sensor


def session_reward(record: SessionRecord, longest_minutes: float) -> float | None:
    """Quality, adjusted so that short sessions do not win just by being short.

    People concentrate more easily for 15 minutes than for 45, so judging by
    quality alone would always pick the shortest option. Longer sessions earn a
    bonus with diminishing returns (square root), so a long session must keep its
    quality reasonably high to beat a shorter one.
    """
    quality = session_quality(record.sensor_score, record.rating)
    if quality is None:
        return None
    return quality * math.sqrt(record.minutes / longest_minutes)


class DurationLearner:
    def __init__(self, options=DEFAULT_OPTIONS, path: Path | None = None, rng: random.Random | None = None):
        self.options = tuple(sorted(float(option) for option in options))
        if not self.options or self.options[0] <= 0:
            raise ValueError("Focus duration options must be positive")
        self.path = path
        self.rng = rng or random.Random()
        self.records: list[SessionRecord] = self._load() if path else []

    # ---------- storage ----------

    def _load(self) -> list[SessionRecord]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
                records.append(SessionRecord(str(value["difficulty"]), float(value["minutes"]),
                                             value["sensor_score"], value["rating"], int(value["at_ms"])))
            except (ValueError, KeyError, TypeError):
                print(f"[LEARNER] Skipped malformed line: {line[:80]}")
        return records

    def add(self, record: SessionRecord):
        if record.difficulty not in DIFFICULTIES:
            raise ValueError(f"Unknown difficulty: {record.difficulty}")
        self.records.append(record)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(asdict(record)) + "\n")

    # ---------- beliefs ----------

    def _rewards(self, minutes: float, difficulty: str | None) -> list[tuple[float, float]]:
        """(reward, recency weight) of past sessions, newest weighing the most."""
        usable = [record for record in self.records if record.minutes in self.options]
        rewards = []
        for age, record in enumerate(reversed(usable)):
            if record.minutes != minutes or (difficulty and record.difficulty != difficulty):
                continue
            reward = session_reward(record, self.options[-1])
            if reward is not None:
                rewards.append((reward, RECENCY_DECAY ** age))
        return rewards

    def _belief(self, minutes: float, difficulty: str) -> tuple[float, float, int]:
        """Posterior (mean, standard deviation, sessions) of one duration in one difficulty.

        The prior comes from the same duration across all difficulties. A difficulty
        with few sessions therefore starts from what is known about the user in
        general, and its own sessions gradually take over.
        """
        pooled = self._rewards(minutes, None)
        pooled_weight = sum(weight for _, weight in pooled)
        prior = (sum(reward * weight for reward, weight in pooled) / pooled_weight) if pooled else NEUTRAL_REWARD
        own = self._rewards(minutes, difficulty)
        weight = PRIOR_STRENGTH + sum(item_weight for _, item_weight in own)
        mean = (prior * PRIOR_STRENGTH + sum(reward * item_weight for reward, item_weight in own)) / weight
        return mean, REWARD_SIGMA / math.sqrt(weight), len(own)

    # ---------- decisions ----------

    def choose(self, difficulty: str) -> float:
        """Thompson Sampling: draw a plausible reward for each duration, take the highest."""
        if difficulty not in DIFFICULTIES:
            raise ValueError(f"Unknown difficulty: {difficulty}")
        untried = [minutes for minutes in self.options if not self._rewards(minutes, None)]
        if untried:
            return self.rng.choice(untried)  # first try every duration once
        beliefs = {minutes: self._belief(minutes, difficulty) for minutes in self.options}
        return max(self.options, key=lambda minutes: self.rng.gauss(beliefs[minutes][0], beliefs[minutes][1]))

    def report(self, difficulty: str) -> dict:
        """What the model currently believes, for the dashboard."""
        durations = []
        for minutes in self.options:
            mean, _, sessions = self._belief(minutes, difficulty)
            ratings = [record.rating for record in self.records
                       if record.minutes == minutes and record.difficulty == difficulty and record.rating is not None]
            durations.append({
                "minutes": minutes,
                "reward": round(mean, 3),
                "sessions": sessions,
                "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else None,
            })
        sessions_here = sum(item["sessions"] for item in durations)
        tried = [item for item in durations if item["sessions"]]
        best = max(tried, key=lambda item: item["reward"]) if tried else None
        if sessions_here >= CONFIDENCE_HIGH and best and best["sessions"] >= CONFIDENCE_MEDIUM:
            confidence = "tinggi"
        elif sessions_here >= CONFIDENCE_MEDIUM:
            confidence = "sedang"
        else:
            confidence = "rendah"
        return {
            "difficulty": difficulty,
            "best_minutes": best["minutes"] if best else None,
            "confidence": confidence,
            "sessions": sessions_here,
            "total_sessions": len(self.records),
            "durations": durations,
        }


def learner_from_env() -> DurationLearner | None:
    """LEARN_DURATION=false turns the model off; the timer then uses FOCUS_MINUTES."""
    if os.getenv("LEARN_DURATION", "true").strip().lower() == "false":
        return None
    raw = os.getenv("FOCUS_OPTIONS", "").strip()
    options = tuple(float(item) for item in raw.split(",") if item.strip()) if raw else DEFAULT_OPTIONS
    profile = os.getenv("USER_PROFILE", "default").strip() or "default"
    if not re.fullmatch(r"[A-Za-z0-9_-]+", profile):
        raise ValueError("USER_PROFILE may only contain letters, numbers, - and _")
    return DurationLearner(options, DATA_DIR / f"{profile}.jsonl")
