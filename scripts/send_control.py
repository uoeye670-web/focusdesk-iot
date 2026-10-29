"""Send START, PAUSE or STOP without the dashboard. Configure the broker in .env."""

import argparse
from shared.mqtt_connection import create_client, topic


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["START", "PAUSE", "STOP"])
    args = parser.parse_args()
    client = create_client("owner-control")
    client.loop_start()
    info = client.publish(topic("control"), args.command, qos=1, retain=False)
    info.wait_for_publish(timeout=10)
    print(f"[CONTROL] Sent {args.command}")
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
