"""No devices, broker, or accounts needed. Study the algorithm first!

Replays one short Pomodoro session (3 min focus, 1 min break) through the
detector, second by second, and prints every status change and alert.

IMPORTANT: Offline mode demonstrates the data processing and algorithm,
not the coursework's required cloud MQTT communication.
"""

from nodes.detector_service.rules import FocusConfig, FocusDetector
from shared.messages import DeskTelemetry, PhoneTelemetry
from shared.processing import DeskSample, PhoneSample, extract_desk_features, extract_phone_features

START_MS = 1_790_000_000_000

# (from second, until second, description, lux, desk vibration, phone held?)
TIMELINE = [
    (0, 30, "Belajar normal", 450, 0.25, False),
    (30, 45, "HP diambil untuk scroll", 450, 0.25, True),
    (45, 90, "Lampu dimatikan", 60, 0.25, False),
    (90, 180, "Lampu menyala, tapi melamun", 450, 0.0, False),
    (180, 260, "Istirahat, lalu sesi 2", 450, 0.25, False),
]


def desk_window(lux: float, vibration: float) -> list[DeskSample]:
    return [DeskSample(i * 0.2, lux, (0, 0, 9.81 + (vibration if i % 2 else -vibration))) for i in range(6)]


def phone_window(held: bool) -> list[PhoneSample]:
    sample = PhoneSample(0, 5.0, (0, 6.5, 7.0)) if held else PhoneSample(0, 0.0, (0, 0, -9.81))
    return [sample] * 6


def main():
    detector = FocusDetector(FocusConfig(focus_minutes=3, break_minutes=1, idle_seconds=60))
    for alert in detector.control("START", START_MS):
        print(f"   [{alert.target}] {alert.message}")
    last_status = None
    for second in range(0, 260):
        now = START_MS + second * 1000
        phase = next(item for item in TIMELINE if item[0] <= second < item[1])
        if second % 2 == 0:
            desk = extract_desk_features(desk_window(phase[3], phase[4]))
            phone = extract_phone_features(phone_window(phase[5]))
            detector.accept(DeskTelemetry("edge1", "demo", second, now, desk.lux_avg, desk.desk_rms), now)
            detector.accept(PhoneTelemetry("edge2", "demo", second, now, phone.face_down,
                                           phone.held_ratio, phone.motion_rms), now)
        alerts = detector.tick(now)
        if detector.status != last_status:
            score = detector.current_score()
            score_text = f", skor {score}" if score is not None and detector.phase == "FOCUS" else ""
            print(f"t={second:3d}s  {phase[2]:<28} -> {detector.status}{score_text}")
            last_status = detector.status
        for alert in alerts:
            print(f"        [{alert.target}] {alert.message}")
    print(f"\nRingkasan sesi: {detector.summary()}")
    print("Offline demo done. Next: run the nodes with the MQTT broker (see README.md).")


if __name__ == "__main__":
    main()
