"""Controlled cybersecurity lab: publish an old message twice on YOUR topic.

Run only against a broker/project namespace you control. Requires MQTT ACL.
"""

import time
from shared.messages import DeskTelemetry
from shared.mqtt_connection import create_client, topic


def main():
    client = create_client("replay-lab")
    client.loop_start()
    message = DeskTelemetry.make("replay-lab", 100, 450.0, 0.2).to_json()
    target = topic("edge/edge1/telemetry")
    for attempt in (1, 2):
        result = client.publish(target, message, qos=1, retain=False)
        result.wait_for_publish(timeout=10)
        print(f"[LAB] Sent exact same message, attempt {attempt}")
        time.sleep(1)
    print("[LAB] Detector should log REJECTED_REPLAY for the second message.")
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
