"""NODE 3: detector service subscribes to MQTT, applies rules, publishes alerts.

Topics (see docs/ARCHITECTURE.md):
  subscribe  edge/+/telemetry   telemetry from both edges
  subscribe  control            START / PAUSE / STOP from the dashboard
  publish    alerts/edge1       spoken reminders on HP meja
  publish    alerts/edge2       vibration + notification on HP pribadi
  publish    status (retained)  every second, for the dashboard

This service CAN run on a laptop connected to a cloud broker.
For a fully cloud-deployed architecture, run the same service on a cloud VM.
"""

import json
import threading
import time

from nodes.detector_service.rules import Alert, FocusConfig, FocusDetector
from shared.messages import alert_json, parse_telemetry
from shared.mqtt_connection import create_client, topic


def now_ms() -> int:
    return int(time.time() * 1000)


def main():
    detector = FocusDetector(FocusConfig.from_env())
    lock = threading.Lock()  # MQTT callbacks and the 1-second clock share the detector
    status_topic = topic("status")
    offline = json.dumps({"status": "OFFLINE", "reason": "Detector disconnected"})
    client = create_client("detector", will=(status_topic, offline))
    telemetry_topic = topic("edge/+/telemetry")
    control_topic = topic("control")

    def send_alerts(alerts: list[Alert]):
        for alert in alerts:
            print(f"[DETECTOR] -> {alert.target}: {alert.event} — {alert.message}")
            client.publish(topic(f"alerts/{alert.target}"), alert_json(alert.event, alert.message),
                           qos=1, retain=False)

    def publish_status():
        with lock:
            payload = json.dumps(detector.snapshot(now_ms()))
        client.publish(status_topic, payload, qos=1, retain=True)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"[DETECTOR] MQTT connection rejected: {reason_code}")
            return
        client.subscribe([(telemetry_topic, 1), (control_topic, 1)])
        print(f"[DETECTOR] Subscribed: {telemetry_topic} and {control_topic}")

    def handle_control(payload: bytes):
        command = payload.decode(errors="replace").strip().upper()
        try:
            with lock:
                alerts = detector.control(command, now_ms())
        except ValueError as exc:
            print(f"[DETECTOR] Ignored: {exc}")
            return
        print(f"[DETECTOR] Dashboard command: {command} -> phase {detector.phase}")
        send_alerts(alerts)
        publish_status()

    def on_message(client, userdata, message):
        if message.topic == control_topic:
            handle_control(message.payload)
            return

        try:
            reading = parse_telemetry(message.payload)
            if message.topic != topic(f"edge/{reading.device_id}/telemetry"):
                print("[DETECTOR] REJECTED: topic and device ID disagree")
                return
            with lock:
                result = detector.accept(reading, now_ms())
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            print(f"[DETECTOR] REJECTED malformed payload: {exc}")
            return
        if not result.accepted:
            print(f"[DETECTOR] {reading.device_id} #{reading.sequence}: {result.reason}")

    client.on_connect = on_connect
    client.on_message = on_message
    client.loop_start()
    print("[DETECTOR] Starting. Ctrl+C to stop")
    last_status = None
    try:
        while True:
            with lock:
                alerts = detector.tick(now_ms())
                status = (detector.status, detector.reason)
            if status != last_status:
                print(f"[DETECTOR] {status[0]} — {status[1]}")
                last_status = status
            send_alerts(alerts)
            publish_status()
            time.sleep(1)
    except KeyboardInterrupt:
        print("[DETECTOR] Stopped")
    finally:
        try:
            info = client.publish(status_topic, json.dumps({"status": "OFFLINE", "reason": "Detector stopped"}),
                                  qos=1, retain=True)
            info.wait_for_publish(timeout=3)
        except (RuntimeError, ValueError):
            pass
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
