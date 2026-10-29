"""Tiny dashboard HTTP server bound to laptop localhost (not a public website).

Only public browser configuration is served. MQTT credentials remain in .env
and are never sent to /config.json.
"""

import json
import os
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from shared.mqtt_connection import DEFAULT_HOST, project_id

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
DEFAULT_WS_URL = "wss://broker.hivemq.com:8884/mqtt"


def public_browser_config() -> dict:
    host = os.getenv("MQTT_HOST") or DEFAULT_HOST
    username = os.getenv("MQTT_USERNAME", "").strip()
    websocket_url = os.getenv("MQTT_WS_URL", "").strip()
    if not websocket_url and host == DEFAULT_HOST:
        websocket_url = DEFAULT_WS_URL

    return {
        "project_id": project_id(),
        "websocket_url": websocket_url,
        "automatic_connection": bool(websocket_url and not username),
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DASHBOARD_DIR), **kwargs)

    def do_GET(self):
        if self.path.split("?", 1)[0] == "/config.json":
            payload = json.dumps(public_browser_config()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def log_message(self, format, *args):
        return


def start_dashboard_server(port: int | None = None):
    """Return server, background thread, and local URL.

    The caller owns shutdown/server_close. Only binds to 127.0.0.1, so phone
    browsers cannot use this URL as a secure-origin sensor page.
    """
    requested_port = port if port is not None else int(os.getenv("DASHBOARD_PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", requested_port), DashboardHandler)
    thread = Thread(target=server.serve_forever, name="focusdesk-dashboard", daemon=True)
    thread.start()
    return server, thread, f"http://localhost:{server.server_port}"
