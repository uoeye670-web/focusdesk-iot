"""OPTIONAL NODE: simple console dashboard. No sensors; not counted as edge."""

from shared.mqtt_connection import create_client, topic


def main():
    client = create_client("monitor")

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"[MONITOR] Connection rejected: {reason_code}")
            return
        client.subscribe(topic("alerts/+"), qos=1)
        print(f"[MONITOR] Listening to: {topic('alerts/+')}")

    def on_message(client, userdata, message):
        print(f"[MONITOR] {message.topic}: {message.payload.decode(errors='replace')}")

    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("[MONITOR] Stopped")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()
