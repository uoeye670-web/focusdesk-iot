import random
import tempfile
import unittest
from pathlib import Path

from nodes.detector_service.learner import DurationLearner, SessionRecord, session_quality, session_reward
from nodes.detector_service.rules import FocusConfig, FocusDetector
from shared.messages import DeskTelemetry, PhoneTelemetry

T0 = 1_790_000_000_000
OPTIONS = (15, 25, 35, 45)


def teach(learner, difficulty, minutes, rating, sensor=80, times=1):
    for _ in range(times):
        learner.add(SessionRecord(difficulty, float(minutes), float(sensor), rating, T0))


class RewardTests(unittest.TestCase):
    def test_quality_mixes_rating_and_sensor(self):
        self.assertAlmostEqual(session_quality(100, 5), 1.0)
        self.assertAlmostEqual(session_quality(0, 1), 0.0)
        self.assertAlmostEqual(session_quality(100, 1), 0.5)

    def test_quality_uses_whatever_is_available(self):
        self.assertAlmostEqual(session_quality(80, None), 0.8)
        self.assertAlmostEqual(session_quality(None, 5), 1.0)
        self.assertIsNone(session_quality(None, None))

    def test_same_quality_prefers_the_longer_session(self):
        short = SessionRecord("sedang", 15.0, 80.0, 4, T0)
        long = SessionRecord("sedang", 45.0, 80.0, 4, T0)
        self.assertGreater(session_reward(long, 45), session_reward(short, 45))

    def test_long_session_with_poor_quality_loses(self):
        short = SessionRecord("sedang", 15.0, 90.0, 5, T0)
        long = SessionRecord("sedang", 45.0, 30.0, 2, T0)
        self.assertGreater(session_reward(short, 45), session_reward(long, 45))


class ChooseTests(unittest.TestCase):
    def learner(self, seed=1):
        return DurationLearner(OPTIONS, rng=random.Random(seed))

    def test_tries_every_duration_before_anything_else(self):
        learner = self.learner()
        seen = set()
        for _ in OPTIONS:
            minutes = learner.choose("sedang")
            seen.add(minutes)
            teach(learner, "sedang", minutes, 3)
        self.assertEqual(seen, set(float(option) for option in OPTIONS))

    def test_learns_the_best_duration(self):
        learner = self.learner()
        teach(learner, "sedang", 15, 2, sensor=50, times=8)
        teach(learner, "sedang", 25, 5, sensor=95, times=8)
        teach(learner, "sedang", 35, 2, sensor=50, times=8)
        teach(learner, "sedang", 45, 1, sensor=30, times=8)
        picks = [learner.choose("sedang") for _ in range(200)]
        self.assertGreater(picks.count(25.0), 170)
        self.assertEqual(learner.report("sedang")["best_minutes"], 25.0)

    def test_still_explores_when_uncertain(self):
        learner = self.learner()
        for minutes in OPTIONS:
            teach(learner, "sedang", minutes, 3)
        self.assertGreater(len({learner.choose("sedang") for _ in range(200)}), 1)

    def test_each_difficulty_learns_its_own_duration(self):
        learner = self.learner()
        for difficulty, good in (("mudah", 45), ("sulit", 15)):
            for minutes in OPTIONS:
                rating, sensor = (5, 95) if minutes == good else (1, 30)
                teach(learner, difficulty, minutes, rating, sensor=sensor, times=8)
        self.assertEqual(learner.report("mudah")["best_minutes"], 45.0)
        self.assertEqual(learner.report("sulit")["best_minutes"], 15.0)

    def test_new_difficulty_starts_from_general_knowledge(self):
        learner = self.learner()
        teach(learner, "sedang", 15, 1, sensor=20, times=8)
        teach(learner, "sedang", 25, 5, sensor=95, times=8)
        teach(learner, "sedang", 35, 1, sensor=20, times=8)
        teach(learner, "sedang", 45, 1, sensor=20, times=8)
        picks = [learner.choose("sulit") for _ in range(200)]
        self.assertEqual(max(set(picks), key=picks.count), 25.0)

    def test_confidence_grows_with_sessions(self):
        learner = self.learner()
        self.assertEqual(learner.report("sedang")["confidence"], "rendah")
        teach(learner, "sedang", 25, 4, times=3)
        self.assertEqual(learner.report("sedang")["confidence"], "sedang")
        teach(learner, "sedang", 25, 4, times=5)
        self.assertEqual(learner.report("sedang")["confidence"], "tinggi")

    def test_unknown_difficulty_rejected(self):
        with self.assertRaises(ValueError):
            self.learner().choose("mustahil")


class StorageTests(unittest.TestCase):
    def test_sessions_survive_restart_and_bad_lines_are_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "data" / "user.jsonl"
            teach(DurationLearner(OPTIONS, path), "sulit", 25, 4)
            with path.open("a", encoding="utf-8") as file:
                file.write("bukan json\n")
            learner = DurationLearner(OPTIONS, path)
            self.assertEqual(len(learner.records), 1)
            self.assertEqual(learner.records[0].rating, 4)

    def test_sessions_of_other_durations_are_ignored(self):
        learner = DurationLearner(OPTIONS)
        teach(learner, "sedang", 3, 5, times=5)
        self.assertEqual(learner.report("sedang")["sessions"], 0)


class DetectorIntegrationTests(unittest.TestCase):
    """The whole loop: model picks a duration, session runs, user rates, model learns."""

    def setUp(self):
        config = FocusConfig(focus_minutes=1, break_minutes=0.5, away_seconds=20, idle_seconds=300)
        self.learner = DurationLearner((1, 2), rng=random.Random(3))
        self.detector = FocusDetector(config, self.learner)
        self.second = 0
        self.seq = 0

    def now(self):
        return T0 + self.second * 1000

    def run_for(self, seconds, face_down=True):
        for _ in range(seconds):
            if self.second % 2 == 0:
                now = self.now()
                self.detector.accept(DeskTelemetry("edge1", "b", self.seq, now, 450.0, 0.2), now)
                self.detector.accept(PhoneTelemetry("edge2", "b", self.seq, now, face_down,
                                                    0.0 if face_down else 1.0, 0.1), now)
                self.seq += 1
            self.second += 1
            self.detector.tick(self.now())

    def finish_focus(self):
        self.run_for(int(self.detector.phase_left_s) + 2)
        self.assertEqual(self.detector.phase, "BREAK")

    def test_duration_comes_from_model(self):
        self.detector.control("START", self.now())
        self.assertIn(self.detector.current_focus_minutes, (1.0, 2.0))
        self.assertEqual(self.detector.phase_left_s, self.detector.current_focus_minutes * 60)

    def test_rating_teaches_the_model(self):
        self.detector.control("DIFFICULTY SULIT", self.now())
        self.detector.control("START", self.now())
        minutes = self.detector.current_focus_minutes
        self.finish_focus()
        self.assertIsNotNone(self.detector.snapshot(self.now())["learning"]["pending"])
        self.detector.control("RATE 4", self.now())
        record = self.learner.records[-1]
        self.assertEqual((record.difficulty, record.minutes, record.rating), ("sulit", minutes, 4))
        self.assertIsNone(self.detector.snapshot(self.now())["learning"]["pending"])
        self.assertEqual(self.detector.history[-1]["rating"], 4)

    def test_rating_twice_counts_once(self):
        self.detector.control("START", self.now())
        self.finish_focus()
        self.detector.control("RATE 4", self.now())
        self.detector.control("RATE 1", self.now())
        self.assertEqual(len(self.learner.records), 1)

    def test_unanswered_question_keeps_sensor_score_only(self):
        self.detector.control("START", self.now())
        self.finish_focus()
        self.run_for(int(self.detector.phase_left_s) + 2)
        self.assertEqual(self.detector.phase, "FOCUS")
        self.assertIsNone(self.learner.records[-1].rating)
        self.assertIsNotNone(self.learner.records[-1].sensor_score)

    def test_stop_before_the_end_teaches_nothing(self):
        self.detector.control("START", self.now())
        self.run_for(10)
        self.detector.control("STOP", self.now())
        self.assertEqual(self.learner.records, [])

    def test_session_paused_too_long_teaches_nothing(self):
        self.detector.control("START", self.now())
        minutes = self.detector.current_focus_minutes
        self.detector.control("PAUSE", self.now())
        self.run_for(int(minutes * 60 * 0.5))
        self.detector.control("START", self.now())
        self.finish_focus()
        self.detector.control("RATE 5", self.now())
        self.assertEqual(self.learner.records, [])
        self.assertFalse(self.detector.history[-1]["counted"])

    def test_short_break_follows_focus_length(self):
        self.detector.control("START", self.now())
        minutes = self.detector.current_focus_minutes
        self.finish_focus()
        self.assertAlmostEqual(self.detector.history[-1]["break_minutes"], 0.5 * minutes)

    def test_bad_commands_rejected(self):
        for command in ("RATE 9", "RATE X", "DIFFICULTY MUSTAHIL"):
            with self.assertRaises(ValueError):
                self.detector.control(command, self.now())


if __name__ == "__main__":
    unittest.main()
