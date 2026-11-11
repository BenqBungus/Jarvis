from __future__ import annotations

import queue
import threading

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import QApplication, QMessageBox

from ..user_settings import JarvisSettings
from ..trusted_actions import trusted_local_action

# router.py's exact self.safety.confirm(action_name, ...) call sites, mapped
# to the safety keys already used in data/settings.json. Kept here (not
# imported from router.py, which only has these as inline literals) so a
# rename on either side just makes one mapping entry stop matching -- which
# falls back to "always confirm" (see confirm() below), never "never confirm".
_ACTION_TO_SAFETY_KEY = {
    "Restart laptop": "confirm_restart",
    "Shutdown laptop": "confirm_shutdown",
    "Put laptop to sleep": "confirm_sleep",
    "Enable internet adapters": "confirm_network_changes",
    "Disable internet adapters": "confirm_network_changes",
    "Enable Bluetooth devices": "confirm_bluetooth_changes",
    "Disable Bluetooth devices": "confirm_bluetooth_changes",
    "Clean temp files": "confirm_temp_cleanup",
    "Gaming mode": "confirm_gaming_mode",
    "Undo last reversible action": "confirm_undo",
}


class GuiSafetyPolicy(QObject):
    """Same synchronous confirm(action_name, reason) -> bool contract as
    jarvis.safety.SafetyPolicy, so it drops into CommandRouter(..., safety=
    this) with no changes to router.py or safety.py. Shows a QMessageBox
    instead of blocking on a terminal input() prompt.

    confirm() is meant to be called from CommandExecutor's worker thread (or
    any thread that is not the GUI thread): it emits a signal requesting the
    GUI thread show a dialog, then blocks on a reply queue until the user
    answers. The GUI thread's event loop stays responsive throughout; only
    the calling worker thread blocks.
    """

    _confirmation_requested = Signal(str, str, object)  # action_name, reason, reply queue

    def __init__(self, settings: JarvisSettings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings
        self._window = None
        self._pending_lock = threading.Lock()
        self._closed = False
        self._pending_replies: set[queue.Queue] = set()
        self._dialogs: dict[queue.Queue, QMessageBox] = {}
        self._confirmation_requested.connect(self._show_dialog)

    def set_window(self, window) -> None:
        """Called once the main window exists, so a confirmation dialog can
        un-hide/raise it (the app may be tray-only/hidden when this fires)."""
        self._window = window

    def confirm(self, action_name: str, reason: str) -> bool:
        app = QApplication.instance()
        if app is not None and QThread.currentThread() is app.thread():
            raise RuntimeError(
                "GuiSafetyPolicy.confirm() called from the GUI thread -- this "
                "would deadlock waiting on its own dialog. Route command "
                "execution through CommandExecutor's worker thread instead."
            )

        reply: "queue.Queue[bool]" = queue.Queue(maxsize=1)
        with self._pending_lock:
            if self._closed:
                return False
            if trusted_local_action(self._settings, action_name):
                return True
            key = _ACTION_TO_SAFETY_KEY.get(action_name)
            if key is not None and not self._settings.safety_enabled(key):
                return True  # user explicitly disabled confirmation for this category
            self._pending_replies.add(reply)
        self._confirmation_requested.emit(action_name, reason, reply)
        return reply.get()

    def _resolve(self, reply, approved: bool) -> None:
        with self._pending_lock:
            if reply not in self._pending_replies:
                return
            self._pending_replies.remove(reply)
            reply.put_nowait(approved)

    @Slot()
    def cancel_pending(self) -> None:
        # Runs on the GUI thread. Cancellation is always No, never approval.
        with self._pending_lock:
            replies = tuple(self._pending_replies)
        for reply in replies:
            self._resolve(reply, False)
        for dialog in tuple(self._dialogs.values()):
            dialog.reject()

    @Slot()
    def shutdown(self) -> None:
        with self._pending_lock:
            self._closed = True
        self.cancel_pending()

    @Slot(str, str, object)
    def _show_dialog(self, action_name: str, reason: str, reply) -> None:
        with self._pending_lock:
            if reply not in self._pending_replies:
                return
        if self._window is not None:
            self._window.show()
            self._window.raise_()
            self._window.activateWindow()
        from .aurora import badge_pixmap

        dialog = QMessageBox(self._window)
        dialog.setObjectName("confirmDialog")  # styled by MainWindow's HUD_STYLE (Claude)
        dialog.setWindowTitle(f"Confirm: {action_name}")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(action_name)
        dialog.setInformativeText(reason)
        dialog.setIconPixmap(badge_pixmap("shield", 44, dialog.style()))
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        dialog.button(QMessageBox.StandardButton.Yes).setText("Allow")
        dialog.button(QMessageBox.StandardButton.No).setText("Cancel")
        dialog.setDefaultButton(QMessageBox.StandardButton.No)
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._dialogs[reply] = dialog

        def finished(_result) -> None:
            approved = dialog.clickedButton() == dialog.button(QMessageBox.StandardButton.Yes)
            self._resolve(reply, approved)
            self._dialogs.pop(reply, None)
            dialog.deleteLater()

        dialog.finished.connect(finished)
        dialog.open()
