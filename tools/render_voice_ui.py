"""Render the native voice surface with fixture readings, no mic or network."""
from __future__ import annotations

import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from jarvis.gui.main_window import MainWindow


app = QApplication([])
for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "segmdl2.ttf"):
    QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
window = MainWindow()
window.set_realtime_status(True, "Ready to connect")
window.set_voice_mode_profile("cedar", "gpt-realtime-2.1")
window.set_setup_checks({
    "openai_key": (True, "Key present; verified on connect"),
    "realtime_deps": (True, "Ready to connect"),
    "classic_mic": (True, "Available"), "tts": (True, "OpenAI / Cedar"),
})
for key, text in {
    "cpu": "12%", "memory": "34% (5.4 / 16 GB)", "gpu": "8% / 42 C",
    "disk": "61% free / 302 GB", "battery": "100% / Plugged in",
    "internet": "Connected", "nvidia_driver": "GeForce RTX / 591.44",
    "windows_update": "No pending updates",
}.items():
    window.update_dashboard(key, text)

target = Path(__file__).resolve().parents[1] / "data" / "diagnostics"
target.mkdir(parents=True, exist_ok=True)
for width, height in [(1360, 850), (960, 720), (1920, 1080)]:
    window.resize(width, height)
    window.show()
    for _ in range(8):
        app.processEvents()
    QTest.qWait(100)
    assert window.size().width() == width and window.size().height() == height
    rendered = window.grab().toImage()
    center = window._core.mapTo(window, window._core.rect().center())
    assert rendered.pixelColor(center).green() > 30, "Core disappeared after resize"
    rendered.save(str(target / f"voice-hud-{width}.png"))
    print(f"Rendered {width}x{height}")
window.resize(1360, 850)
window.set_realtime_active(True, "speaking")
window.set_keyword_interrupt_status(True)
window.set_audio_level(.8)
for _ in range(4):
    window._core._animate()
    app.processEvents()
window.grab().save(str(target / "voice-hud-speaking.png"))
window.set_realtime_detail("Cannot open the selected audio device. Check the output device in Settings.")
window.set_realtime_active(False, "error")
app.processEvents()
window.grab().save(str(target / "voice-hud-error.png"))
window.hide()
