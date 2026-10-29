"""NODE 2: HP pribadi (edge2), ditelungkupkan di meja selama sesi fokus.

Di HP (Termux):  python hp_pribadi.py
Di laptop:       python hp_pribadi.py --source simulator --scenario diangkat   (simulasi HP diambil)
"""

from shared.alarm import vibrate
from shared.edge_runner import run_edge

if __name__ == "__main__":
    run_edge("edge2", on_alert=vibrate)
