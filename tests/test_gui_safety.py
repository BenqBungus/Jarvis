from __future__ import annotations

import threading

import pytest
from PySide6.QtWidgets import QMessageBox

from jarvis.gui.gui_safety import GuiSafetyPolicy
from jarvis.user_settings import JarvisSettings


def _confirm_on_thread(policy, action_name, reason, result_box):
    def worker():
        result_box["value"] = policy.confirm(action_name, reason)

    thread = threading.Thread(target=worker)
    thread.start()
    return thread


def test_confirm_from_the_gui_thread_raises_instead_of_deadlocking(qapp):
    policy = GuiSafetyPolicy(JarvisSettings())
    with pytest.raises(RuntimeError):
        policy.confirm("Restart laptop", "reason")


def test_confirm_shows_dialog_and_returns_true_on_yes(qapp, pump_events, monkeypatch):
    monkeypatch.setattr(QMessageBox, "open", lambda self: self.button(QMessageBox.StandardButton.Yes).click())
    policy = GuiSafetyPolicy(JarvisSettings())

    result_box: dict = {}
    thread = _confirm_on_thread(policy, "Restart laptop", "This will restart.", result_box)
    assert pump_events(lambda: "value" in result_box)
    thread.join()

    assert result_box["value"] is True


def test_confirm_shows_dialog_and_returns_false_on_no(qapp, pump_events, monkeypatch):
    monkeypatch.setattr(QMessageBox, "open", lambda self: self.button(QMessageBox.StandardButton.No).click())
    policy = GuiSafetyPolicy(JarvisSettings())

    result_box: dict = {}
    thread = _confirm_on_thread(policy, "Restart laptop", "reason", result_box)
    assert pump_events(lambda: "value" in result_box)
    thread.join()

    assert result_box["value"] is False


def test_confirm_skips_the_dialog_when_settings_disable_it(qapp, monkeypatch):
    calls = {"n": 0}

    def fake_question(self):
        calls["n"] += 1
        self.button(QMessageBox.StandardButton.No).click()

    monkeypatch.setattr(QMessageBox, "open", fake_question)
    policy = GuiSafetyPolicy(JarvisSettings(safety={"confirm_restart": False}))

    result_box: dict = {}
    thread = _confirm_on_thread(policy, "Restart laptop", "reason", result_box)
    thread.join(timeout=2)  # no dialog involved, so no event pumping needed

    assert result_box.get("value") is True
    assert calls["n"] == 0


def test_confirm_still_asks_for_unmapped_actions(qapp, pump_events, monkeypatch):
    # Fail-safe: an action_name not in the mapping table must never be
    # silently auto-approved.
    monkeypatch.setattr(QMessageBox, "open", lambda self: self.button(QMessageBox.StandardButton.Yes).click())
    policy = GuiSafetyPolicy(JarvisSettings())

    result_box: dict = {}
    thread = _confirm_on_thread(policy, "Some Future Action", "reason", result_box)
    assert pump_events(lambda: "value" in result_box)
    thread.join()

    assert result_box["value"] is True  # dialog WAS shown (mocked Yes), not bypassed


def test_confirm_defaults_to_asking_when_key_known_but_unset_in_settings(qapp, pump_events, monkeypatch):
    monkeypatch.setattr(QMessageBox, "open", lambda self: self.button(QMessageBox.StandardButton.No).click())
    policy = GuiSafetyPolicy(JarvisSettings(safety={}))  # confirm_gaming_mode absent, not False

    result_box: dict = {}
    thread = _confirm_on_thread(policy, "Gaming mode", "reason", result_box)
    assert pump_events(lambda: "value" in result_box)
    thread.join()

    assert result_box["value"] is False  # dialog was shown and answered No


@pytest.mark.parametrize(
    "action_name,expected_key",
    [
        ("Restart laptop", "confirm_restart"),
        ("Shutdown laptop", "confirm_shutdown"),
        ("Put laptop to sleep", "confirm_sleep"),
        ("Enable internet adapters", "confirm_network_changes"),
        ("Disable internet adapters", "confirm_network_changes"),
        ("Enable Bluetooth devices", "confirm_bluetooth_changes"),
        ("Disable Bluetooth devices", "confirm_bluetooth_changes"),
        ("Clean temp files", "confirm_temp_cleanup"),
        ("Gaming mode", "confirm_gaming_mode"),
        ("Undo last reversible action", "confirm_undo"),
    ],
)
def test_every_router_confirmation_site_maps_to_the_matching_settings_key(
    qapp, monkeypatch, action_name, expected_key
):
    # Matches the exact action_name strings passed to safety.confirm(...) in
    # router.py, and the exact key names already in data/settings.json.
    calls = {"n": 0}
    monkeypatch.setattr(QMessageBox, "open", lambda self: self.button(QMessageBox.StandardButton.No).click())
    policy = GuiSafetyPolicy(JarvisSettings(safety={expected_key: False}))

    result_box: dict = {}
    thread = _confirm_on_thread(policy, action_name, "reason", result_box)
    thread.join(timeout=2)

    assert result_box.get("value") is True  # disabling the mapped key skipped the dialog


def test_cancel_rejects_visible_confirmation_and_unblocks_worker(qapp, pump_events):
    policy = GuiSafetyPolicy(JarvisSettings())
    result = {}
    thread = _confirm_on_thread(policy, "Restart laptop", "Restart?", result)
    try:
        assert pump_events(lambda: bool(policy._dialogs))
        dialog = next(iter(policy._dialogs.values()))
        assert dialog.defaultButton() is dialog.button(QMessageBox.StandardButton.No)
        policy.cancel_pending()
        assert pump_events(lambda: "value" in result)
        assert result["value"] is False
        assert not policy._dialogs
    finally:
        policy.cancel_pending()
        thread.join(2)


def test_cancel_before_dialog_delivery_does_not_show_stale_prompt(qapp, pump_events, monkeypatch):
    import time

    shown = []
    monkeypatch.setattr(QMessageBox, "open", lambda self: shown.append(True))
    policy = GuiSafetyPolicy(JarvisSettings())
    result = {}
    thread = _confirm_on_thread(policy, "Restart laptop", "Restart?", result)
    try:
        deadline = time.monotonic() + 2
        while not policy._pending_replies and time.monotonic() < deadline:
            time.sleep(.005)
        assert policy._pending_replies
        policy.cancel_pending()
        assert pump_events(lambda: "value" in result)
        qapp.processEvents()
        assert result["value"] is False
        assert not shown
    finally:
        policy.cancel_pending()
        thread.join(2)


@pytest.mark.parametrize("confirmation_enabled", [False, True])
def test_shutdown_rejects_future_actions_without_waiting_for_gui(qapp, confirmation_enabled):
    policy = GuiSafetyPolicy(JarvisSettings(safety={"confirm_restart": confirmation_enabled}))
    policy.shutdown()
    result = {}
    thread = _confirm_on_thread(policy, "Restart laptop", "Restart?", result)
    thread.join(2)
    assert not thread.is_alive()
    assert result["value"] is False
    assert not policy._pending_replies
