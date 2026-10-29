"""NODE 1: desk station phone. Light + accelerometer -> processing -> MQTT; speaks alerts."""

from shared.alarm import speak
from shared.edge_runner import run_edge

if __name__ == "__main__":
    run_edge("edge1", on_alert=speak)
