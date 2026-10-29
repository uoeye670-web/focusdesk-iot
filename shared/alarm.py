"""OUTPUT / ACTUATOR: how each phone reacts to an alert from the detector.

HP meja (edge1) speaks the message with text-to-speech.
HP pribadi (edge2) vibrates and shows a notification.
On a laptop the same code only prints to the terminal, so it runs anywhere.
"""

import shutil
import subprocess


def _run_quietly(command: list[str]):
    try:
        subprocess.run(command, capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"[ALARM] Could not run {command[0]}: {exc}")


def speak(alert: dict):
    message = str(alert.get("message", ""))[:200]
    print(f"\n[EDGE1 | SUARA] {alert.get('event', '?')}: {message}\n")
    if message and shutil.which("termux-tts-speak"):
        _run_quietly(["termux-tts-speak", "-l", "id", message])


def vibrate(alert: dict):
    event = str(alert.get("event", "?"))
    message = str(alert.get("message", ""))[:200]
    print(f"\n[EDGE2 | GETAR] {event}: {message}\n")

    if shutil.which("termux-vibrate"):
        _run_quietly(["termux-vibrate", "-d", "800" if event == "BREAK" else "1500"])
    if shutil.which("termux-notification"):
        _run_quietly([
            "termux-notification",
            "--id", "focusdesk",
            "--title", "FocusDesk: waktunya istirahat" if event == "BREAK" else "FocusDesk: kamu terdistraksi!",
            "--content", message,
            "--priority", "high",
        ])
