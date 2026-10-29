"""NODE 3 — Laptop: MQTT detector + browser dashboard.

Run: python detector.py
Open the printed http://localhost:8000 link on this laptop.
"""

from nodes.detector_service.main import main
from shared.dashboard_server import start_dashboard_server
from shared.mqtt_connection import project_id


def run():
    try:
        server, thread, url = start_dashboard_server()
    except OSError as exc:
        raise SystemExit(
            f"[DASHBOARD] Gagal membuka localhost:8000: {exc}. "
            "Tutup aplikasi lain di port ini atau set DASHBOARD_PORT di .env."
        ) from exc

    print("\nFocusDesk — NODE 3 / Laptop", flush=True)
    print(f"[DASHBOARD] Buka di laptop: {url}", flush=True)
    print(f"[CONFIG] PROJECT_ID: {project_id()}", flush=True)
    print("[DETECTOR] Menunggu HP meja (edge1) dan HP pribadi (edge2) dari MQTT Cloud...\n", flush=True)
    try:
        main()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


if __name__ == "__main__":
    run()
