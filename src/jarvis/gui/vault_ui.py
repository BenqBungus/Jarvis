"""The Passwords window, the reveal card and the vault's voice/text tools.

Built by Claude on the user's request of 2026-09-28 (see vault.py). The AI
only ever receives names: revealing shows the password in a local window and,
when asked, spells it with the local Windows voice (in a Live call with the
call's microphone muted meanwhile). Tool results carry private_content, so
audit and memory omit them.
"""
from __future__ import annotations

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QStyle, QVBoxLayout, QWidget)

from ..models import CommandResult
from ..permissions import CONFIRM
from ..tool_registry import ToolParameter, ToolSpec
from ..vault import PasswordVault, VaultEntry, VaultError, speak_locally, spelled
from .aurora import DialogHeader, card, set_glyph, set_role, style_dialog

CLIPBOARD_SECONDS = 30
REVEAL_SECONDS = 45
_PRIVATE = {"private_content": True}


def _copy_for_a_while(secret: str, owner: QObject) -> None:
    """Copy, then clear the clipboard after 30 s if it still holds the secret."""
    clipboard = QGuiApplication.clipboard()
    clipboard.setText(secret)
    timer = QTimer(owner)
    timer.setSingleShot(True)
    timer.timeout.connect(lambda: clipboard.text() == secret and clipboard.clear())
    timer.start(CLIPBOARD_SECONDS * 1000)


class RevealDialog(QDialog):
    """One password, hidden until Show; closes itself after 45 seconds."""

    def __init__(self, entry: VaultEntry, secret: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        style_dialog(self, "vaultReveal")
        self.setWindowTitle(f"Password · {entry.name}")
        self._secret = secret
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(DialogHeader("lock", entry.name, entry.username or "Saved password"))
        self.field = QLineEdit(secret)
        self.field.setReadOnly(True)
        self.field.setEchoMode(QLineEdit.EchoMode.Password)
        self.field.setAccessibleName(f"Password for {entry.name}")
        row = QHBoxLayout()
        row.addWidget(self.field, 1)
        self.show_button = QPushButton("Show")
        self.show_button.setCheckable(True)
        self.show_button.toggled.connect(self._toggle)
        row.addWidget(self.show_button)
        self.copy_button = QPushButton("Copy")
        set_role(self.copy_button, "", variant="primary")
        self.copy_button.clicked.connect(self._copy)
        row.addWidget(self.copy_button)
        layout.addLayout(row)
        self.note = QLabel(f"Closes by itself in {REVEAL_SECONDS} s. Copying clears the clipboard after "
                           f"{CLIPBOARD_SECONDS} s.")
        set_role(self.note, "note")
        layout.addWidget(self.note)
        self._close_timer = QTimer(self)
        self._close_timer.setSingleShot(True)
        self._close_timer.timeout.connect(self.close)
        self._close_timer.start(REVEAL_SECONDS * 1000)
        self.resize(460, self.sizeHint().height())

    def _toggle(self, shown: bool) -> None:
        self.field.setEchoMode(QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)
        self.show_button.setText("Hide" if shown else "Show")

    def _copy(self) -> None:
        _copy_for_a_while(self._secret, self.parent() or self)
        self.note.setText(f"Copied. The clipboard clears in {CLIPBOARD_SECONDS} s.")

    def closeEvent(self, event) -> None:
        self.field.clear()
        self._secret = ""
        super().closeEvent(event)


class PasswordsDialog(QDialog):
    """This profile's saved passwords: add, show, copy and delete."""

    def __init__(self, vault: PasswordVault, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        style_dialog(self, "vaultDialog")
        self.vault = vault
        self.setWindowTitle("Jarvis | Passwords")
        self.resize(560, 600)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        layout.addWidget(DialogHeader("lock", "Passwords",
                                      "Kept by Windows Credential Manager for this profile. Never sent to OpenAI."))
        self.list = QListWidget()
        self.list.setAccessibleName("Saved passwords")
        self.list.itemDoubleClicked.connect(lambda _item: self.show_selected())
        layout.addWidget(self.list, 1)
        actions = QHBoxLayout()
        self.show_button = QPushButton("Show")
        set_glyph(self.show_button, "lock", QStyle.StandardPixmap.SP_FileDialogInfoView)
        self.show_button.clicked.connect(self.show_selected)
        self.copy_button = QPushButton("Copy")
        self.copy_button.clicked.connect(self.copy_selected)
        self.delete_button = QPushButton("Delete")
        set_role(self.delete_button, "", variant="danger")
        self.delete_button.clicked.connect(self.delete_selected)
        for button in (self.show_button, self.copy_button):
            actions.addWidget(button)
        actions.addStretch()
        actions.addWidget(self.delete_button)
        layout.addLayout(actions)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Name, e.g. Wi-Fi at home")
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username or email (optional)")
        self.secret_input = QLineEdit()
        self.secret_input.setPlaceholderText("Password")
        self.secret_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.secret_input.returnPressed.connect(self.save_new)
        self.save_button = QPushButton("Save password")
        set_role(self.save_button, "", variant="primary")
        self.save_button.clicked.connect(self.save_new)
        overline = QLabel("ADD OR UPDATE")
        set_role(overline, "overline")
        layout.addWidget(card(overline, self.name_input, self.username_input, self.secret_input, self.save_button,
                              spacing=8))
        self.status = QLabel("Tip: type passwords here. A password said aloud passes through the voice service.")
        set_role(self.status, "note")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        try:
            entries = self.vault.entries()
        except VaultError as error:
            self.status.setText(str(error))
            entries = []
        for entry in entries:
            item = QListWidgetItem(f"{entry.name}   ·   {entry.username}" if entry.username else entry.name)
            item.setData(Qt.ItemDataRole.UserRole, entry.name)
            self.list.addItem(item)
        if not entries:
            item = QListWidgetItem("No saved passwords yet.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(item)
        has = bool(entries)
        for button in (self.show_button, self.copy_button, self.delete_button):
            button.setEnabled(has)

    def _selected(self) -> str:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole) or "") if item else ""

    def show_selected(self) -> None:
        name = self._selected()
        found = self.vault.reveal(name) if name else None
        if found:
            RevealDialog(*found, self).show()

    def copy_selected(self) -> None:
        name = self._selected()
        found = self.vault.reveal(name) if name else None
        if found:
            _copy_for_a_while(found[1], self)
            self.status.setText(f"Copied {found[0].name}. The clipboard clears in {CLIPBOARD_SECONDS} s.")

    def delete_selected(self) -> None:
        name = self._selected()
        if not name:
            return
        answer = QMessageBox.question(self, "Delete password?", f"Delete the saved password for {name}?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self.vault.delete(name)
            self.status.setText(f"Deleted {name}.")
            self.refresh()

    def save_new(self) -> None:
        try:
            entry = self.vault.save(self.name_input.text(), self.secret_input.text(), self.username_input.text())
        except VaultError as error:
            self.status.setText(str(error))
            return
        self.secret_input.clear()
        self.name_input.clear()
        self.username_input.clear()
        self.status.setText(f"Saved {entry.name}.")
        self.refresh()


class VaultController(QObject):
    """The vault's tools (text, classic voice and Live calls) and windows.

    Speaking a password uses the local Windows voice only. Outside a Live call
    the wake-word listener pauses meanwhile. In a Live call (`live_audio`, the
    RealtimeVoiceWorker) the call's microphone is muted first, Jarvis's short
    reply is allowed to finish, then the password is spelled and the
    microphone restored, so the voice service never hears it."""

    POLL_MS = 150  # how often a Live call is checked while waiting to speak
    QUIET_MS = 450  # silence that counts as "Jarvis finished its reply"
    REPLY_WAIT_MS = 3000  # speak anyway if no reply starts by then
    MAX_WAIT_MS = 20000

    _reveal_requested = Signal(str, bool)  # name, speak: from the tool's thread to the GUI thread
    _speech_finished = Signal()
    _vault_changed = Signal()

    def __init__(self, vault: PasswordVault, window, router, *, live_call_active: Callable[[], bool] = lambda: False,
                 pause_listening: Callable[[], None] | None = None,
                 resume_listening: Callable[[], None] | None = None, live_audio=None) -> None:
        super().__init__(window)
        self.vault, self.window = vault, window
        self._live_call_active = live_call_active
        self._pause_listening, self._resume_listening = pause_listening, resume_listening
        self._live_audio = live_audio
        self._manager: PasswordsDialog | None = None
        self._speech_busy = False
        self._after_speech: Callable[[], None] | None = None
        self._reveal_requested.connect(self._reveal)
        self._speech_finished.connect(self._on_speech_finished)
        self._vault_changed.connect(lambda: self._manager is not None and self._manager.refresh())
        window.passwords_requested.connect(self.open_manager)
        tools = router.tools
        for spec, handler in (
            (ToolSpec("vault_list", "List the names of the user's saved passwords (never the passwords).",
                      category="vault"), self._list_tool),
            (ToolSpec("vault_save", "Save a password the user gives, in Windows Credential Manager for this profile. "
                      "Suggest typing passwords in the Passwords window instead of saying them.", category="vault",
                      parameters=(ToolParameter("name", "string", "What the password is for, e.g. Wi-Fi."),
                                  ToolParameter("password", "string", "The password."),
                                  ToolParameter("username", "string", "Username or email, if any.", required=False))),
             self._save_tool),
            (ToolSpec("vault_reveal", "Show a saved password to the user on this computer's screen and, if they ask, "
                      "read it with the local Windows voice. The password is never returned to you.",
                      category="vault", parameters=(
                          ToolParameter("name", "string", "The saved password's name."),
                          ToolParameter("speak", "boolean", "Also read it aloud locally.", required=False))),
             self._reveal_tool),
            (ToolSpec("vault_delete", "Delete a saved password after the user confirms.", permission=CONFIRM,
                      requires_confirmation=True, category="vault",
                      parameters=(ToolParameter("name", "string", "The saved password's name."),)),
             self._delete_tool),
        ):
            if tools.get(spec.name) is None:
                tools.register(spec, handler)

    def set_profile(self, profile_id: str) -> None:
        """Another person's vault: close what the previous one had open."""
        self.vault.profile_id = profile_id
        if self._manager is not None:
            self._manager.hide()
            self._manager.refresh()

    def open_manager(self) -> None:
        if self._manager is None:
            self._manager = PasswordsDialog(self.vault, self.window)
        self._manager.refresh()
        self._manager.show()
        self._manager.raise_()
        self._manager.activateWindow()

    # ------------------------------------------------------------ tools

    @staticmethod
    def _result(ok: bool, message: str, **metadata) -> CommandResult:
        return CommandResult(ok, message, metadata={**_PRIVATE, **metadata})

    def _list_tool(self) -> CommandResult:
        names = [entry.name for entry in self.vault.entries()]
        return self._result(True, ("Saved passwords: " + ", ".join(names)) if names else "No saved passwords yet.",
                            vault_names=names)

    def _save_tool(self, name: str, password: str, username: str = "") -> CommandResult:
        try:
            entry = self.vault.save(name, password, username)
        except VaultError as error:
            return self._result(False, str(error))
        self._vault_changed.emit()
        return self._result(True, f"Saved the password for {entry.name}. Next time, type passwords in the "
                                  "Passwords window: said aloud, they pass through the voice service.")

    def _reveal_tool(self, name: str, speak: bool = False) -> CommandResult:
        entry = self.vault.find(name)
        if entry is None:
            return self._result(False, f"There is no saved password called {name}.")
        live = self._live_call_active()
        can_speak = not live or self._live_audio is not None
        self._reveal_requested.emit(entry.name, bool(speak) and can_speak)
        if speak and not can_speak:
            message = ("Shown on the screen. During this Live call it cannot be read aloud: the microphone would "
                       "send it back to the voice service.")
        elif speak and live:
            message = ("Shown on the screen. Right after your reply the local Windows voice reads it aloud while the "
                       "call's microphone is paused, so the voice service never hears it. Reply in a few words only "
                       "and never repeat or guess the password.")
        elif speak:
            message = "Shown on the screen and read aloud with the local Windows voice."
        else:
            message = "Shown on the screen."
        return self._result(True, message, vault_name=entry.name)

    def _delete_tool(self, name: str) -> CommandResult:
        entry = self.vault.delete(name)
        if entry is None:
            return self._result(False, f"There is no saved password called {name}.")
        self._vault_changed.emit()
        return self._result(True, f"Deleted the password for {entry.name}.")

    # ---------------------------------------------------------- GUI side

    def _reveal(self, name: str, speak: bool) -> None:
        found = self.vault.reveal(name)
        if not found:
            return
        entry, secret = found
        dialog = RevealDialog(entry, secret, self.window)
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.show()
        dialog.raise_()
        if not speak or self._speech_busy:
            return
        self._speech_busy = True
        text = f"The password for {entry.name} is: {spelled(secret)}."
        live = self._live_audio
        if live is not None and self._live_call_active():
            self._speak_in_call(text, live)
            return
        if self._pause_listening:
            self._pause_listening()  # the wake-word microphone must not hear it
        self._speak(text, self._resume_listening)

    def _speak_in_call(self, text: str, live) -> None:
        """Mute the call's microphone, let Jarvis finish its short reply, then speak."""
        was_muted = bool(live.input_muted())
        live.set_input_muted(True)
        state = {"waited": 0, "started": False, "quiet": 0}
        timer = QTimer(self)
        timer.setInterval(self.POLL_MS)

        def tick() -> None:
            state["waited"] += self.POLL_MS
            if live.is_speaking():
                state["started"], state["quiet"] = True, 0
            else:
                state["quiet"] += self.POLL_MS
            finished = state["started"] and state["quiet"] >= self.QUIET_MS
            no_reply = not state["started"] and state["waited"] >= self.REPLY_WAIT_MS
            if finished or no_reply or state["waited"] >= self.MAX_WAIT_MS:
                timer.stop()
                timer.deleteLater()
                self._speak(text, lambda: live.set_input_muted(was_muted))

        timer.timeout.connect(tick)
        timer.start()

    def _speak(self, text: str, after: Callable[[], None] | None) -> None:
        self._after_speech = after

        def run() -> None:
            try:
                speak_locally(text)
            except Exception:  # no SAPI voice: the window is still showing it
                pass
            finally:
                self._speech_finished.emit()

        threading.Thread(target=run, daemon=True, name="jarvis-vault-voice").start()

    def _on_speech_finished(self) -> None:
        after, self._after_speech = self._after_speech, None
        self._speech_busy = False
        if after is not None:
            after()
