from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QSystemTrayIcon

from jarvis.gui.tray import TrayIcon


class _FakeWindow:
    def __init__(self) -> None:
        self.shown = False
        self.raised = False
        self.activated = False

    def show(self) -> None:
        self.shown = True

    def raise_(self) -> None:
        self.raised = True

    def activateWindow(self) -> None:
        self.activated = True


def test_starts_idle(qapp):
    tray = TrayIcon(_FakeWindow())
    assert tray.current_state() == "idle"


def test_set_voice_state_changes_current_state(qapp):
    tray = TrayIcon(_FakeWindow())
    tray.set_voice_state("listening")
    assert tray.current_state() == "listening"
    tray.set_voice_state("processing")
    assert tray.current_state() == "processing"
    tray.set_voice_state("idle")
    assert tray.current_state() == "idle"


def test_set_voice_state_rejects_unknown_state(qapp):
    tray = TrayIcon(_FakeWindow())
    with pytest.raises(ValueError):
        tray.set_voice_state("warning")  # warning is not a voice state


def test_warning_overrides_voice_state(qapp):
    tray = TrayIcon(_FakeWindow())
    tray.set_voice_state("listening")
    tray.raise_warning(timeout_ms=60_000)
    assert tray.current_state() == "warning"


def test_clear_warning_reverts_to_current_voice_state(qapp):
    tray = TrayIcon(_FakeWindow())
    tray.set_voice_state("processing")
    tray.raise_warning(timeout_ms=60_000)
    tray.clear_warning()
    assert tray.current_state() == "processing"


def test_warning_auto_reverts_after_timeout(qapp, pump_events):
    tray = TrayIcon(_FakeWindow())
    tray.raise_warning(timeout_ms=30)
    assert tray.current_state() == "warning"
    assert pump_events(lambda: tray.current_state() == "idle", timeout=2)


def test_voice_state_change_while_warning_active_does_not_override_warning(qapp):
    tray = TrayIcon(_FakeWindow())
    tray.raise_warning(timeout_ms=60_000)
    tray.set_voice_state("listening")
    assert tray.current_state() == "warning"
    tray.clear_warning()
    assert tray.current_state() == "listening"


def test_show_window_action_shows_raises_and_activates(qapp):
    window = _FakeWindow()
    tray = TrayIcon(window)
    tray._show_window()
    assert window.shown and window.raised and window.activated


def test_notify_calls_show_message(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(
        QSystemTrayIcon, "showMessage", lambda self, title, msg, icon, timeout: calls.append((title, msg, icon, timeout))
    )
    tray = TrayIcon(_FakeWindow())
    tray.notify("Low battery", "15% remaining.", category="warning")
    assert len(calls) == 1
    title, msg, icon, timeout = calls[0]
    assert title == "Low battery"
    assert msg == "15% remaining."
    assert icon == QSystemTrayIcon.MessageIcon.Warning


def test_notify_defaults_to_information_icon(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(
        QSystemTrayIcon, "showMessage", lambda self, title, msg, icon, timeout: calls.append(icon)
    )
    tray = TrayIcon(_FakeWindow())
    tray.notify("Update available", "3 updates pending.")
    assert calls == [QSystemTrayIcon.MessageIcon.Information]


def test_unclear_is_a_valid_voice_state(qapp):
    tray = TrayIcon(_FakeWindow())
    tray.set_voice_state("unclear")
    assert tray.current_state() == "unclear"


def test_unclear_reverts_naturally_on_next_listening_state(qapp):
    # Unlike "warning" (needs a timer), "unclear" is just another voice
    # state -- the next state_changed("listening") from the loop clears it.
    tray = TrayIcon(_FakeWindow())
    tray.set_voice_state("unclear")
    tray.set_voice_state("listening")
    assert tray.current_state() == "listening"


def test_run_wizard_menu_action_emits_run_wizard_requested(qapp):
    from PySide6.QtGui import QAction

    tray = TrayIcon(_FakeWindow())
    received = []
    tray.run_wizard_requested.connect(lambda: received.append(True))

    wizard_action = next(a for a in tray._menu.actions() if a.text() == "Run Setup Wizard...")
    wizard_action.trigger()

    assert received == [True]
