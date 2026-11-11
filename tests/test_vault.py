"""The password vault (vault.py, gui/vault_ui.py): per-profile storage, tools
that never hand a password to the AI, the reveal window and local speech."""
from __future__ import annotations

import json
import time

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLineEdit, QMessageBox

from jarvis.audit import AuditLogger
from jarvis.gui import vault_ui
from jarvis.gui.main_window import MainWindow
from jarvis.gui.vault_ui import PasswordsDialog, RevealDialog, VaultController
from jarvis.models import CommandResult
from jarvis.permission_levels import tool_allowed
from jarvis.privacy import redact_sensitive_data
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.tool_registry import ToolCall
from jarvis.user_settings import JarvisSettings
from jarvis.vault import MemoryCredentials, PasswordVault, VaultError, spelled
from jarvis.windows_actions import WindowsActions

SECRET = "Tr0ub4dor&3"


@pytest.fixture
def vault():
    return PasswordVault(MemoryCredentials(), profile_id="berk")


def test_save_find_reveal_and_delete(vault):
    vault.save("Wi-Fi at home", SECRET, "berk")
    vault.save("Bank", "1234")
    assert [entry.name for entry in vault.entries()] == ["Bank", "Wi-Fi at home"]
    assert vault.find("wi-fi AT home").name == "Wi-Fi at home"
    assert vault.find("wifi") is None and vault.find("home").name == "Wi-Fi at home"
    entry, secret = vault.reveal("wi-fi at home")
    assert secret == SECRET and entry.username == "berk"
    vault.save("wi-fi at home", "new-password")  # same name: updated, not duplicated
    assert len(vault.entries()) == 2 and vault.reveal("Wi-Fi at home")[1] == "new-password"
    assert vault.delete("bank").name == "Bank" and vault.find("bank") is None


def test_each_profile_has_its_own_vault():
    store = MemoryCredentials()
    berk, ani = PasswordVault(store, "berk"), PasswordVault(store, "ani")
    berk.save("Steam", SECRET)
    assert ani.entries() == [] and ani.reveal("Steam") is None


def test_bad_input_is_refused(vault):
    with pytest.raises(VaultError):
        vault.save("", SECRET)
    with pytest.raises(VaultError):
        vault.save("x" * 61, SECRET)
    with pytest.raises(VaultError):
        vault.save("Wi-Fi", "")
    with pytest.raises(VaultError):
        vault.save("Wi-Fi", "x" * 513)


def test_spelling_for_the_local_voice():
    assert spelled("Pa$1") == "capital P, a, dollar, 1"
    assert spelled("a b") == "a, space, b"


@pytest.fixture
def controller(qapp, vault):
    window = MainWindow()
    router = CommandRouter(WindowsActions(dry_run=True), SafetyPolicy(), settings=JarvisSettings())
    live = {"on": False}
    events = []
    controller = VaultController(vault, window, router, live_call_active=lambda: live["on"],
                                 pause_listening=lambda: events.append("pause"),
                                 resume_listening=lambda: events.append("resume"))
    controller.live, controller.events, controller.router = live, events, router
    yield controller
    window.deleteLater()


def _run(controller, tool, **arguments):
    return controller.router.tools.execute(ToolCall(tool, arguments))


def test_tools_never_return_the_password(controller):
    saved = _run(controller, "vault_save", name="Wi-Fi", password=SECRET)
    listed = _run(controller, "vault_list")
    shown = _run(controller, "vault_reveal", name="wi-fi")
    for result in (saved, listed, shown):
        assert result.ok and SECRET not in result.message and SECRET not in json.dumps(result.metadata)
        assert result.metadata["private_content"] is True
    assert listed.metadata["vault_names"] == ["Wi-Fi"]
    assert not _run(controller, "vault_reveal", name="Bank").ok


def test_secret_named_values_are_redacted_whatever_they_look_like():
    redacted = redact_sensitive_data({"password": "1234", "Token": "Bearer abcdefghijklmnopqrstuvwxyz",
                                      "name": "Wi-Fi", "pin": True, "args": [{"secret": "x"}]})
    assert redacted == {"password": "[REDACTED_SECRET]", "Token": "Bearer [REDACTED_SECRET]", "name": "Wi-Fi",
                        "pin": True, "args": [{"secret": "[REDACTED_SECRET]"}]}


def test_the_audit_log_omits_vault_calls(controller, tmp_path):
    result = _run(controller, "vault_save", name="Wi-Fi", password=SECRET)
    audit = AuditLogger(tmp_path / "audit.jsonl")
    audit.log(json.dumps({"tool": "vault_save", "arguments": {"name": "Wi-Fi", "password": SECRET}}), result, False)
    assert SECRET not in (tmp_path / "audit.jsonl").read_text(encoding="utf-8")


def test_reveal_opens_a_masked_window_on_the_gui_thread(controller, qapp):
    _run(controller, "vault_save", name="Wi-Fi", password=SECRET)
    _run(controller, "vault_reveal", name="Wi-Fi")
    qapp.processEvents()
    [dialog] = [widget for widget in controller.window.findChildren(RevealDialog)]
    assert dialog.field.text() == SECRET and dialog.field.echoMode() == QLineEdit.EchoMode.Password
    dialog.show_button.click()
    assert dialog.field.echoMode() == QLineEdit.EchoMode.Normal
    dialog.close()
    assert dialog.field.text() == ""


def _pump(qapp, until, seconds=3.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end and not until():
        qapp.processEvents()
        time.sleep(0.005)


def test_speaking_outside_a_call_pauses_the_wake_word(controller, qapp, monkeypatch):
    spoken = []
    monkeypatch.setattr(vault_ui, "speak_locally", spoken.append)
    _run(controller, "vault_save", name="Wi-Fi", password="Ab1")
    result = _run(controller, "vault_reveal", name="Wi-Fi", speak=True)
    assert "local Windows voice" in result.message
    _pump(qapp, lambda: "resume" in controller.events)
    assert spoken == ["The password for Wi-Fi is: capital A, b, 1."]
    assert controller.events == ["pause", "resume"]


def test_without_the_call_audio_a_live_call_only_shows_it(controller, qapp, monkeypatch):
    spoken = []
    monkeypatch.setattr(vault_ui, "speak_locally", spoken.append)
    _run(controller, "vault_save", name="Wi-Fi", password="Ab1")
    controller.live["on"] = True
    result = _run(controller, "vault_reveal", name="Wi-Fi", speak=True)
    assert "cannot be read aloud" in result.message
    _pump(qapp, lambda: False, 0.2)
    assert spoken == [] and controller.events == []


class FakeLiveCall:
    """RealtimeVoiceWorker's mute and speaking state, scripted per poll."""

    def __init__(self, speaking, muted=False):
        self.speaking, self.muted, self.log = list(speaking), muted, []

    def input_muted(self):
        return self.muted

    def set_input_muted(self, muted):
        self.muted = muted
        self.log.append("mute" if muted else "unmute")

    def is_speaking(self):
        return self.speaking.pop(0) if self.speaking else False


@pytest.mark.parametrize("already_muted", [False, True])
def test_in_a_live_call_the_mic_is_muted_until_the_password_is_spoken(qapp, vault, monkeypatch, already_muted):
    monkeypatch.setattr(VaultController, "POLL_MS", 10)
    monkeypatch.setattr(VaultController, "QUIET_MS", 30)
    call = FakeLiveCall([False, False, True, True, True, False], muted=already_muted)
    spoken = []
    monkeypatch.setattr(vault_ui, "speak_locally", lambda text: (call.log.append("speak"), spoken.append(text)))
    window = MainWindow()
    router = CommandRouter(WindowsActions(dry_run=True), SafetyPolicy(), settings=JarvisSettings())
    VaultController(vault, window, router, live_call_active=lambda: True, live_audio=call)
    vault.save("Wi-Fi", "Ab1")
    result = router.tools.execute(ToolCall("vault_reveal", {"name": "Wi-Fi", "speak": True}))
    assert "microphone is paused" in result.message and "Ab1" not in result.message
    _pump(qapp, lambda: len(call.log) == 3)
    # Muted first, spoken only after Jarvis's own reply ended, then restored.
    assert call.log == ["mute", "speak", "mute" if already_muted else "unmute"]
    assert call.speaking == [] and spoken == ["The password for Wi-Fi is: capital A, b, 1."]
    window.deleteLater()


def test_kids_and_guests_cannot_use_the_vault(controller):
    for name in ("vault_list", "vault_save", "vault_reveal", "vault_delete"):
        spec = controller.router.tools.get(name).spec
        assert tool_allowed("adult", spec)[0]
        assert not tool_allowed("kid", spec)[0] and not tool_allowed("guest", spec)[0]
    window = controller.window
    window.set_permission_level("kid")
    assert not window._passwords_button.isEnabled()


def test_the_passwords_window(qapp, vault, monkeypatch):
    dialog = PasswordsDialog(vault)
    assert not dialog.show_button.isEnabled()  # empty vault
    dialog.name_input.setText("Wi-Fi")
    dialog.secret_input.setText(SECRET)
    dialog.save_new()
    assert dialog.secret_input.text() == "" and vault.find("Wi-Fi") is not None
    dialog.list.setCurrentRow(0)
    dialog.copy_selected()
    assert QGuiApplication.clipboard().text() == SECRET
    QGuiApplication.clipboard().clear()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)
    dialog.delete_selected()
    assert vault.entries() == []
    dialog.deleteLater()


def test_delete_needs_confirmation(controller):
    spec = controller.router.tools.get("vault_delete").spec
    assert spec.requires_confirmation
    assert isinstance(_run(controller, "vault_delete", name="nothing"), CommandResult)
