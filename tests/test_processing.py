import unittest

from shared.processing import (
    DeskSample, PhoneSample, extract_desk_features, extract_phone_features, is_face_down,
)


def desk(lux=450.0, vibration=0.0, count=6):
    return [DeskSample(i * 0.2, lux, (0, 0, 9.81 + (vibration if i % 2 else -vibration))) for i in range(count)]


FACE_DOWN = PhoneSample(0, 0.0, (0, 0, -9.81))
IN_HAND = PhoneSample(0, 5.0, (0, 6.5, 7.0))


class DeskProcessingTests(unittest.TestCase):
    def test_still_desk_has_no_vibration(self):
        result = extract_desk_features(desk(lux=420))
        self.assertAlmostEqual(result.lux_avg, 420, places=1)
        self.assertAlmostEqual(result.desk_rms, 0, places=3)

    def test_writing_increases_desk_rms(self):
        self.assertGreater(extract_desk_features(desk(vibration=0.2)).desk_rms, 0.15)

    def test_sideways_tap_is_detected(self):
        # A pen tap shakes the desk sideways; the total magnitude hardly changes.
        samples = [DeskSample(i, 450, (0.04 if i % 2 else -0.04, 2.3, 9.4)) for i in range(10)]
        self.assertGreater(extract_desk_features(samples).desk_rms, 0.03)

    def test_calibration_offset_is_ignored(self):
        # A phone that reads 10.3 m/s2 at rest must still count as a still desk.
        samples = [DeskSample(i, 450, (0, 0, 10.3)) for i in range(5)]
        self.assertAlmostEqual(extract_desk_features(samples).desk_rms, 0, places=3)

    def test_need_multiple_samples(self):
        with self.assertRaises(ValueError):
            extract_desk_features(desk(count=1))


class PhoneProcessingTests(unittest.TestCase):
    def test_face_down_needs_proximity_and_orientation(self):
        self.assertTrue(is_face_down(FACE_DOWN))
        self.assertFalse(is_face_down(IN_HAND))
        # Screen up with a hand over the sensor is not face down.
        self.assertFalse(is_face_down(PhoneSample(0, 0.0, (0, 0, 9.81))))

    def test_phone_left_alone(self):
        result = extract_phone_features([FACE_DOWN] * 5)
        self.assertTrue(result.face_down)
        self.assertEqual(result.held_ratio, 0)

    def test_short_pickup_inside_window(self):
        result = extract_phone_features([FACE_DOWN, IN_HAND, IN_HAND, FACE_DOWN])
        self.assertTrue(result.face_down)
        self.assertEqual(result.held_ratio, 0.5)
        self.assertGreater(result.motion_rms, 0)


if __name__ == "__main__":
    unittest.main()
