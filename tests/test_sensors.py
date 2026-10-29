import unittest
from unittest import mock

from shared.sensors import AndroidDesk, find_sensor, parse_json_objects

# Real `termux-sensor -l` output from the group's HP A (chip names only).
CHIP_NAMES = [
    "mxc4005xc_acc", "af6133e", "orientation", "virtual_gyro", "stk3335x_als", "stk3335x_ps",
    "gravity", "linear_acc", "rot_vec", "uncali_mag", "game_rotvec", "significant", "step_detect",
    "step_count", "geo_rotvec", "tilt", "wake", "uncali_acc", "hinge", "step_detect_wakeup",
]

# Typical listing from phones that report descriptive names.
DESCRIPTIVE_NAMES = [
    "BMI160 Accelerometer Uncalibrated", "BMI160 Accelerometer", "Linear Acceleration Sensor",
    "TMD4910 Light", "TMD4910 Proximity Sensor", "Ambient Temperature", "GPS Status",
]


class FindSensorTests(unittest.TestCase):
    def test_chip_style_names(self):
        self.assertEqual(find_sensor(CHIP_NAMES, "accelerometer"), "mxc4005xc_acc")
        self.assertEqual(find_sensor(CHIP_NAMES, "light"), "stk3335x_als")
        self.assertEqual(find_sensor(CHIP_NAMES, "proximity"), "stk3335x_ps")

    def test_descriptive_names(self):
        self.assertEqual(find_sensor(DESCRIPTIVE_NAMES, "accelerometer"), "BMI160 Accelerometer")
        self.assertEqual(find_sensor(DESCRIPTIVE_NAMES, "light"), "TMD4910 Light")
        self.assertEqual(find_sensor(DESCRIPTIVE_NAMES, "proximity"), "TMD4910 Proximity Sensor")

    def test_missing_sensor(self):
        self.assertIsNone(find_sensor(["gravity", "tilt"], "light"))


BOTH = '{"stk3335x_als": {"values": [21]}, "mxc4005xc_acc": {"values": [0.1, 0.2, 9.8]}}'
LIGHT_ONLY = '{\n  "stk3335x_als": {\n    "values": [\n      25\n    ]\n  }\n}'
ACCEL_ONLY = '{"mxc4005xc_acc": {"values": [0.3, 0.1, 9.7]}}'


class PartialOutputTests(unittest.TestCase):
    """termux-sensor sometimes returns only one of the two requested sensors."""

    def make_desk(self, outputs):
        with mock.patch("shared.sensors._list_sensors", return_value=CHIP_NAMES):
            desk = AndroidDesk()
        desk._run_termux_sensor = mock.Mock(side_effect=outputs)
        return desk

    def test_light_only_reuses_last_accelerometer(self):
        desk = self.make_desk([BOTH, LIGHT_ONLY])
        desk.read()
        sample = desk.read()
        self.assertEqual(sample.lux, 25)
        self.assertEqual(sample.acceleration, (0.1, 0.2, 9.8))

    def test_first_read_waits_until_both_sensors_seen(self):
        desk = self.make_desk([LIGHT_ONLY, "", ACCEL_ONLY])
        sample = desk.read()
        self.assertEqual(sample.lux, 25)
        self.assertEqual(sample.acceleration, (0.3, 0.1, 9.7))

    def test_gives_up_when_a_sensor_never_reports(self):
        desk = self.make_desk([LIGHT_ONLY] * 5)
        with self.assertRaises(RuntimeError):
            desk.read()

    def test_several_objects_in_one_output(self):
        self.assertEqual(len(parse_json_objects(LIGHT_ONLY + "\n" + ACCEL_ONLY)), 2)


if __name__ == "__main__":
    unittest.main()
