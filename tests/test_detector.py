import json
import unittest

from nodes.detector_service.rules import FocusConfig, FocusDetector, focus_score, light_level
from shared.messages import DeskTelemetry, PhoneTelemetry, parse_telemetry

T0 = 1_790_000_000_000
CONFIG = FocusConfig(focus_minutes=2, break_minutes=1, idle_seconds=30, bad_light_seconds=10)


class Session:
    """Feeds both edges every 2 seconds and ticks the detector every second."""

    def __init__(self, config=CONFIG):
        self.detector = FocusDetector(config)
        self.second = 0
        self.seq = 0
        self.alerts = []

    def now(self):
        return T0 + self.second * 1000

    def start(self):
        self.alerts += self.detector.control("START", self.now())

    def run(self, seconds, lux=450.0, desk_rms=0.2, face_down=True, held_ratio=0.0):
        for _ in range(seconds):
            if self.second % 2 == 0:
                now = self.now()
                self.detector.accept(DeskTelemetry("edge1", "b", self.seq, now, lux, desk_rms), now)
                self.detector.accept(PhoneTelemetry("edge2", "b", self.seq, now, face_down, held_ratio, 0.1), now)
                self.seq += 1
            self.second += 1
            self.alerts += self.detector.tick(self.now())
        return self.detector.status


class ScoreTests(unittest.TestCase):
    def test_perfect_and_worst_score(self):
        self.assertAlmostEqual(focus_score(0.0, True, 450, CONFIG), 100)
        self.assertAlmostEqual(focus_score(1.0, False, 50, CONFIG), 10)

    def test_light_levels(self):
        self.assertEqual(light_level(100, CONFIG), "kurang")
        self.assertEqual(light_level(500, CONFIG), "ideal")
        self.assertEqual(light_level(5000, CONFIG), "silau")


class FocusDetectorTests(unittest.TestCase):
    def test_idle_until_start(self):
        session = Session()
        self.assertEqual(session.run(5), "IDLE")

    def test_waiting_for_edges(self):
        session = Session()
        session.start()
        self.assertEqual(session.detector.tick(session.now() + 1000), [])
        self.assertEqual(session.detector.status, "MENUNGGU")

    def test_focused_session(self):
        session = Session()
        session.start()
        self.assertEqual(session.run(20), "FOKUS")
        self.assertGreaterEqual(session.detector.current_score(), 95)

    def test_pickup_is_distraction_and_vibrates_phone(self):
        session = Session()
        session.start()
        session.run(10)
        self.assertEqual(session.run(4, face_down=False, held_ratio=1.0), "TERDISTRAKSI")
        self.assertEqual(session.detector.pickups, 1)
        self.assertIn(("edge2", "DISTRACTED"), [(a.target, a.event) for a in session.alerts])
        self.assertEqual(session.run(4), "FOKUS")

    def test_dark_desk_after_grace_period(self):
        session = Session()
        session.start()
        self.assertEqual(session.run(6, lux=50), "FOKUS")
        self.assertEqual(session.run(10, lux=50), "CAHAYA_KURANG")
        self.assertIn("CAHAYA_KURANG", [a.event for a in session.alerts])

    def test_one_spike_keeps_desk_active_for_a_while(self):
        session = Session()
        session.start()
        session.run(20, desk_rms=0.0)
        session.run(2, desk_rms=0.2)
        session.run(10, desk_rms=0.0)
        self.assertTrue(session.detector.snapshot(session.now())["desk"]["active"])
        session.run(10, desk_rms=0.0)
        self.assertFalse(session.detector.snapshot(session.now())["desk"]["active"])

    def test_still_desk_means_daydreaming(self):
        session = Session()
        session.start()
        self.assertEqual(session.run(35, desk_rms=0.0), "MELAMUN")

    def test_pomodoro_cycle(self):
        session = Session()
        session.start()
        self.assertEqual(session.run(121), "ISTIRAHAT")
        self.assertIn("BREAK", [a.event for a in session.alerts])
        self.assertEqual(session.run(61), "FOKUS")
        self.assertEqual(session.detector.cycle, 2)

    def test_long_break_after_four_pomodoros(self):
        config = FocusConfig(focus_minutes=1, break_minutes=0.5, long_break_minutes=2, idle_seconds=300)
        session = Session(config)
        session.start()
        for number in range(1, 4):
            self.assertEqual(session.detector.pomodoro_in_set(), number)
            self.assertEqual(session.run(61), "ISTIRAHAT")
            self.assertFalse(session.detector.long_break)
            self.assertEqual(session.run(31), "FOKUS")
        self.assertEqual(session.detector.pomodoro_in_set(), 4)
        self.assertEqual(session.run(61), "ISTIRAHAT")
        self.assertTrue(session.detector.long_break)
        self.assertGreater(session.detector.phase_left_s, 100)
        self.assertIn("Istirahat panjang", session.detector.reason)
        self.assertEqual(session.run(121), "FOKUS")
        self.assertEqual(session.detector.pomodoro_in_set(), 1)
        self.assertEqual(session.detector.summary()["pomodoros"], 4)

    def test_pause_freezes_timer(self):
        session = Session()
        session.start()
        session.run(10)
        left = session.detector.phase_left_s
        session.detector.control("PAUSE", session.now())
        self.assertEqual(session.run(30), "JEDA")
        self.assertEqual(session.detector.phase_left_s, left)
        session.detector.control("START", session.now())
        self.assertEqual(session.run(2), "FOKUS")

    def test_stop_speaks_summary(self):
        session = Session()
        session.start()
        session.run(30)
        alerts = session.detector.control("STOP", session.now())
        self.assertEqual(session.detector.status, "IDLE")
        self.assertEqual(alerts[0].event, "SESSION_SUMMARY")

    def test_replay_rejected(self):
        detector = FocusDetector(CONFIG)
        reading = DeskTelemetry("edge1", "b", 3, T0, 450, 0.2)
        self.assertTrue(detector.accept(reading, T0).accepted)
        self.assertFalse(detector.accept(reading, T0).accepted)

    def test_stale_timestamp_rejected(self):
        detector = FocusDetector(CONFIG)
        result = detector.accept(DeskTelemetry("edge1", "b", 0, T0 - 31_000, 450, 0.2), T0)
        self.assertFalse(result.accepted)

    def test_unknown_control_rejected(self):
        with self.assertRaises(ValueError):
            FocusDetector(CONFIG).control("ARM", T0)

    def test_snapshot_is_json(self):
        session = Session()
        session.start()
        session.run(5)
        body = json.loads(json.dumps(session.detector.snapshot(session.now())))
        self.assertEqual(body["status"], "FOKUS")
        self.assertTrue(body["desk"]["online"])


class TelemetryParsingTests(unittest.TestCase):
    def test_round_trip(self):
        desk = DeskTelemetry("edge1", "b", 1, T0, 450.0, 0.2)
        phone = PhoneTelemetry("edge2", "b", 1, T0, True, 0.0, 0.01)
        self.assertEqual(parse_telemetry(desk.to_json()), desk)
        self.assertEqual(parse_telemetry(phone.to_json()), phone)

    def test_wrong_data_type_rejected(self):
        body = json.dumps({"device_id": "edge1", "boot_id": "abc", "sequence": 2, "sent_at_ms": T0,
                           "lux_avg": "terang", "desk_rms": 0.1})
        with self.assertRaises(ValueError):
            parse_telemetry(body)

    def test_held_ratio_out_of_range_rejected(self):
        body = json.dumps({"device_id": "edge2", "boot_id": "abc", "sequence": 2, "sent_at_ms": T0,
                           "face_down": True, "held_ratio": 1.5, "motion_rms": 0.1})
        with self.assertRaises(ValueError):
            parse_telemetry(body)


if __name__ == "__main__":
    unittest.main()
