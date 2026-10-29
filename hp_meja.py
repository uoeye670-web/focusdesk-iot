"""NODE 1: HP meja (edge1), stasiun di meja belajar, layar menghadap ke atas.

Di HP (Termux):  python hp_meja.py
Di laptop:       python hp_meja.py --source simulator --scenario gelap   (simulasi lampu mati)
"""

from shared.alarm import speak
from shared.edge_runner import run_edge

if __name__ == "__main__":
    run_edge("edge1", on_alert=speak)
