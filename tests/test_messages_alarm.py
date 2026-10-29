import json
import unittest
from unittest import mock

from shared import alarm
from shared.messages import alert_json


class AlertMessageTests(unittest.TestCase):
    def test_alert_payload_fields(self):
        body = json.loads(alert_json("BREAK", "Istirahat", now_ms=123))
        self.assertEqual(body, {"event": "BREAK", "message": "Istirahat", "at_ms": 123})


class AlarmTests(unittest.TestCase):
    def test_laptop_only_prints(self):
        with mock.patch("shared.alarm.shutil.which", return_value=None), \
             mock.patch("shared.alarm.subprocess.run") as run:
            alarm.speak({"event": "IDLE", "message": "test"})
            alarm.vibrate({"event": "DISTRACTED", "message": "test"})
        run.assert_not_called()

    def test_desk_phone_speaks(self):
        with mock.patch("shared.alarm.shutil.which", return_value="/bin/x"), \
             mock.patch("shared.alarm.subprocess.run") as run:
            alarm.speak({"event": "CAHAYA_KURANG", "message": "Nyalakan lampu meja."})
        self.assertEqual(run.call_args.args[0][0], "termux-tts-speak")
        self.assertEqual(run.call_args.args[0][-1], "Nyalakan lampu meja.")

    def test_personal_phone_vibrates_and_notifies(self):
        with mock.patch("shared.alarm.shutil.which", return_value="/bin/x"), \
             mock.patch("shared.alarm.subprocess.run") as run:
            alarm.vibrate({"event": "DISTRACTED", "message": "test"})
        commands = [call.args[0][0] for call in run.call_args_list]
        self.assertEqual(commands, ["termux-vibrate", "termux-notification"])


if __name__ == "__main__":
    unittest.main()
