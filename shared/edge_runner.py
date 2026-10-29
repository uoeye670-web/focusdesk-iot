"""Common edge pipeline, used by both phones.

Real sensor -> two feature extractions -> MQTT Cloud, and alerts back.
  edge1 = HP meja:    light + accelerometer     -> lux_avg, desk_rms
  edge2 = HP pribadi: proximity + accelerometer -> face_down, held_ratio, motion_rms
Simulator is opt-in and MUST NOT be described as a real IoT physical-edge demonstration.
"""

import argparse
import json
import time
import uuid
from collections.abc import Callable

from shared.messages import DeskTelemetry, PhoneTelemetry
from shared.mqtt_connection import create_client, topic
from shared.processing import extract_desk_features, extract_phone_features
from shared.sensors import BURST_SIZE, DESK_SCENARIOS, PHONE_SCENARIOS, select_source

AlertHandler = Callable[[dict], None]
ROLES = {"edge1": "desk", "edge2": "phone"}


def _parse_args(device_id: str) -> argparse.Namespace:
    scenarios = DESK_SCENARIOS if ROLES[device_id] == "desk" else PHONE_SCENARIOS
    parser = argparse.ArgumentParser(description=f"FocusDesk {device_id}")
    parser.add_argument(
        "--source", choices=["android", "simulator"], default="android",
        help="Default: real Android sensors. Use simulator only for testing.",
    )
    parser.add_argument(
        "--scenario", choices=scenarios, default=scenarios[0],
        help="Only used with --source simulator",
    )
    parser.add_argument("--interval", type=float, default=None)
    parser.add_argument("--samples", type=int, default=BURST_SIZE)
    parser.add_argument(
        "--debug-sensors", action="store_true",
        help="Print raw sensor values before processing.",
    )
    args = parser.parse_args()
    if args.interval is None:
        # Android readings already arrive in timed bursts (shared/sensors.py).
        args.interval = 0.01 if args.source == "android" else 0.3
    if args.interval <= 0 or args.samples < 2:
        parser.error("--interval must be positive and --samples >= 2")
    return args


def _make_telemetry(device_id: str, samples: list, boot_id: str, sequence: int):
    if ROLES[device_id] == "desk":
        features = extract_desk_features(samples)
        telemetry = DeskTelemetry.make(boot_id, sequence, features.lux_avg, features.desk_rms)
        summary = f"lux={features.lux_avg:.0f} meja_rms={features.desk_rms:.3f}"
    else:
        features = extract_phone_features(samples)
        telemetry = PhoneTelemetry.make(boot_id, sequence, features.face_down,
                                        features.held_ratio, features.motion_rms)
        summary = (f"telungkup={features.face_down} dipegang={features.held_ratio:.0%} "
                   f"gerak_rms={features.motion_rms:.3f}")
    return telemetry, summary


def run_edge(device_id: str, on_alert: AlertHandler):
    args = _parse_args(device_id)
    label = device_id.upper()
    source = select_source(ROLES[device_id], args.source, args.scenario)
    client = create_client(device_id)
    alert_topic = topic(f"alerts/{device_id}")

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            print(f"[{label}] MQTT connection rejected: {reason_code}")
            return
        client.subscribe(alert_topic, qos=1)
        print(f"[{label}] Subscribed to {alert_topic}")

    def on_message(client, userdata, message):
        try:
            alert = json.loads(message.payload)
            if not isinstance(alert, dict):
                raise ValueError("Alert must be a JSON object")
        except ValueError:
            print(f"[{label}] Ignored malformed alert")
            return
        on_alert(alert)

    client.on_connect = on_connect
    client.on_message = on_message
    client.loop_start()
    boot_id = uuid.uuid4().hex
    sequence = 0
    telemetry_topic = topic(f"edge/{device_id}/telemetry")
    print(f"[{label}] Source: {args.source}")
    print(f"[{label}] Publishes to: {telemetry_topic}")

    try:
        while True:
            samples = []
            for sample_index in range(args.samples):
                sample = source.read()
                samples.append(sample)
                if args.debug_sensors:
                    print(f"[{label} | RAW] {sample}", flush=True)
                if sample_index < args.samples - 1:
                    time.sleep(args.interval)
            telemetry, summary = _make_telemetry(device_id, samples, boot_id, sequence)
            info = client.publish(telemetry_topic, telemetry.to_json(), qos=1)
            info.wait_for_publish(timeout=10)
            print(f"[{label}] #{sequence} {summary}")
            sequence += 1
    except KeyboardInterrupt:
        print(f"[{label}] Stopped")
    finally:
        client.loop_stop()
        client.disconnect()
