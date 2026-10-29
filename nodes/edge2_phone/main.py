"""NODE 2: personal phone, face down during focus. Proximity + accelerometer -> MQTT; vibrates on alerts."""

from shared.alarm import vibrate
from shared.edge_runner import run_edge

if __name__ == "__main__":
    run_edge("edge2", on_alert=vibrate)
