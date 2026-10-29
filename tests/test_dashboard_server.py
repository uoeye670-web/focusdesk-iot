"""Local dashboard should not need a cloud broker to start."""

import json
import os
from unittest import TestCase
from unittest.mock import patch
from urllib.request import urlopen

from shared.dashboard_server import public_browser_config, start_dashboard_server


class DashboardServerTests(TestCase):
    def test_local_http_server_and_no_credentials(self):
        with patch.dict(os.environ, {
            "PROJECT_ID": "kelas_test",
            "MQTT_HOST": "broker.hivemq.com",
            "MQTT_PASSWORD": "DO_NOT_LEAK",
            "MQTT_USERNAME": "",
        }):
            server, thread, url = start_dashboard_server(port=0)
            try:
                with urlopen(url + "/") as result:
                    self.assertEqual(result.status, 200)
                    self.assertIn(b"FocusDesk Dashboard", result.read())
                with urlopen(url + "/config.json") as result:
                    self.assertEqual(result.status, 200)
                    config = json.loads(result.read())
                self.assertEqual(config["project_id"], "kelas_test")
                self.assertEqual(config["websocket_url"], "wss://broker.hivemq.com:8884/mqtt")
                self.assertTrue(config["automatic_connection"])
                self.assertNotIn("DO_NOT_LEAK", json.dumps(config))
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_private_broker_does_not_expose_password(self):
        with patch.dict(os.environ, {
            "PROJECT_ID": "private_test",
            "MQTT_HOST": "private.example.com",
            "MQTT_WS_URL": "wss://private.example.com/mqtt",
            "MQTT_USERNAME": "secret-user",
            "MQTT_PASSWORD": "secret-pass",
        }):
            config = public_browser_config()
            self.assertFalse(config["automatic_connection"])
            self.assertNotIn("secret", json.dumps(config))
