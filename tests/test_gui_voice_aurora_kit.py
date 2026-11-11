"""The Aurora kit for secondary windows (gui/aurora.py), the HUD level meters
and the restyled confirmation dialog."""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, Mock

import pytest
from PySide6.QtWidgets import QMessageBox

from jarvis.audit import AuditLogger
from jarvis.gui.activity_center import ActivityCenter
from jarvis.gui.aurora import DialogHeader, badge_pixmap, style_dialog
from jarvis.gui.gmail_settings import GmailSettingsDialog
from jarvis.gui.gui_safety import GuiSafetyPolicy
from jarvis.gui.main_window import MainWindow, _meter_level
from jarvis.gui.panel_voice import PanelVoiceControls
from jarvis.gui.screen_chat import ScreenChatDialog
from jarvis.gui.voice_core import AURORA
from jarvis.rollback import RollbackManager
from jarvis.user_settings import JarvisSettings


@pytest.mark.parametrize(("kind", "text", "level"), [
    ("cpu", "42%", (0.42, AURORA["accent"])),
    ("cpu", "95%", (0.95, AURORA["danger"])),
    ("memory", "80% (12.8/16.0 GB)", (0.80, AURORA["warning"])),
    ("disk", "61% free (302/496 GB)", (0.39, AURORA["accent"])),
    ("battery", "80% (charging)", (0.80, AURORA["accent"])),
    ("battery", "15% (on battery)", (0.15, AURORA["danger"])),
    ("cpu_temperature", "91C", (0.91, AURORA["danger"])),
    ("internet", "connected", None),
    ("cpu", "unavailable", None),
])
def test_meter_levels(kind, text, level):
    result = _meter_level(kind, text)
    if level is None:
        assert result is None
    else:
        assert result[0] == pytest.approx(level[0]) and result[1] == level[1]


def test_status_rows_carry_meters(qapp):
    window = MainWindow()
    assert set(window._meters) == {"cpu", "cpu_temperature", "memory", "gpu", "disk", "battery"}
    window.update_dashboard("cpu", "42%")
    assert window._meters["cpu"]._fraction == pytest.approx(0.42)
    window.update_dashboard("cpu", "unavailable")
    assert window._meters["cpu"]._fraction is None
    assert window._dashboard_labels["cpu"].text() == "unavailable"
    window.deleteLater()


def test_kit_pieces(qapp):
    from PySide6.QtWidgets import QDialog

    dialog = QDialog()
    style_dialog(dialog, "kitProbe")
    assert dialog.objectName() == "kitProbe"
    assert "#kitProbe QTabBar::tab" in dialog.styleSheet()
    header = DialogHeader("mail", "Gmail", "Read-only")
    assert header.title_label.text() == "Gmail" and header.subtitle_label.text() == "Read-only"
    pixmap = badge_pixmap("shield", 44, dialog.style())
    assert not pixmap.isNull() and pixmap.devicePixelRatio() == 2.0 and pixmap.width() == 88


def test_secondary_windows_use_the_kit(qapp, tmp_path):
    center = ActivityCenter(AuditLogger(tmp_path / "audit.jsonl"), RollbackManager(tmp_path / "rollback.json"))
    gmail = GmailSettingsDialog(Mock())
    screen = ScreenChatDialog(ai=MagicMock())
    assert center.objectName() == "activityCenter" and gmail.objectName() == "gmailSettings"
    assert gmail.connect_button.property("variant") == "primary"
    for window in (center, gmail, screen):
        assert window.findChildren(DialogHeader)
    assert screen.send.property("role") == "send"
    for widget in (center, gmail, screen):
        widget.deleteLater()


def test_the_panel_call_button_turns_into_hang_up(qapp):
    controls = PanelVoiceControls(commands=True)
    assert controls.call.property("role") == "call" and controls.call.property("active") == "false"
    controls.set_active(True)
    assert controls.call.property("active") == "true" and controls.mute.isEnabled()
    controls.set_active(False)
    assert controls.call.property("active") == "false"


def test_confirmations_read_clearly_and_default_to_cancel(qapp, pump_events, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "open", lambda self: shown.append(self))
    policy = GuiSafetyPolicy(JarvisSettings())
    result = {}
    thread = threading.Thread(target=lambda: result.setdefault("value", policy.confirm("Restart laptop", "Why")),
                              daemon=True)
    thread.start()
    try:
        assert pump_events(lambda: bool(shown))
        dialog = shown[0]
        assert dialog.objectName() == "confirmDialog"
        assert dialog.text() == "Restart laptop" and dialog.informativeText() == "Why"
        assert dialog.button(QMessageBox.StandardButton.Yes).text() == "Allow"
        assert dialog.defaultButton() is dialog.button(QMessageBox.StandardButton.No)
        assert not dialog.iconPixmap().isNull()
    finally:
        policy.cancel_pending()
        thread.join(2)
    assert result.get("value") is False


def test_share_button_follows_the_polled_state(qapp):
    window = MainWindow()
    window.set_screen_sharing_active(False)  # app.py polls twice a second; repeats change nothing
    assert not window._screen_share_button.isChecked() and not window._screen_share_dot.isVisibleTo(window)
    window.set_screen_sharing_active(True)
    window.set_screen_sharing_active(True)
    assert window._screen_share_button.isChecked() and window._screen_share_dot.isVisibleTo(window)
    assert window._screen_share_button.toolTip() == "Stop screen sharing"
    window.set_screen_sharing_active(False)
    assert not window._screen_share_dot.isVisibleTo(window)
    assert window._screen_share_button.toolTip() == "Start screen sharing"
    window.deleteLater()
