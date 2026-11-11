"""Gmail account setup, separate from Claude-owned general settings widgets."""
from __future__ import annotations

from queue import Empty, Queue
import threading

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QStyle, QVBoxLayout

from ..audit import AuditLogger
from ..models import CommandResult
from .aurora import DialogHeader, card, set_glyph, set_role, style_dialog


class GmailSettingsDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._busy = False
        self._closed = False
        self._cancelled = threading.Event()
        self._results = Queue()
        self.setWindowTitle("Gmail")
        style_dialog(self, "gmailSettings")  # the Aurora look (gui/aurora.py)
        self.resize(560, 320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(14)
        layout.addWidget(DialogHeader("mail", "Gmail", "Read-only · Jarvis never sends, replies or deletes."))
        self.status_label = QLabel("Not checked")
        self.status_label.setWordWrap(True)
        set_role(self.status_label, "body")
        layout.addWidget(card(set_role(QLabel("CONNECTION"), "overline"), self.status_label))
        privacy = QLabel("Selected email content may be shared with OpenAI during voice conversations or summaries, after confirmation. No sending or deleting.")
        privacy.setWordWrap(True)
        set_role(privacy, "note")
        layout.addWidget(privacy)
        layout.addStretch()
        row = QHBoxLayout()
        self.disconnect_button = QPushButton("Disconnect locally")
        set_role(self.disconnect_button, "", variant="danger")
        set_glyph(self.disconnect_button, "close", QStyle.StandardPixmap.SP_DialogCancelButton,
                  color="#F28B82")
        self.disconnect_button.clicked.connect(self.disconnect)
        row.addWidget(self.disconnect_button)
        row.addStretch()
        self.connect_button = QPushButton("Connect Google account")
        set_role(self.connect_button, "", variant="primary")
        set_glyph(self.connect_button, "link", QStyle.StandardPixmap.SP_DialogOpenButton, color="#04131A")
        self.connect_button.clicked.connect(self.choose_client)
        row.addWidget(self.connect_button)
        layout.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._poll)

    def open_settings(self):
        if self._closed:
            return
        if not self._busy:
            self.status_label.setText(self.service.status().message)
        self.show()
        self.raise_()
        self.activateWindow()

    def choose_client(self):
        if self._busy or self._closed:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Choose Google Desktop OAuth client JSON", "", "JSON (*.json)")
        if not path:
            return
        self._begin("gmail_connect", lambda: self.service.connect(path, cancelled=self._cancelled.is_set))

    def disconnect(self):
        if self._busy or self._closed:
            return
        answer = QMessageBox.question(self, "Disconnect Gmail", "Remove Jarvis's saved Gmail authorization? Google's grant must be revoked separately in your Google Account.")
        if answer == QMessageBox.StandardButton.Yes:
            self._begin("gmail_disconnect", self.service.disconnect)

    def _begin(self, action, operation):
        if self._busy or self._closed:
            return
        self._busy = True
        self._cancelled.clear()
        self.connect_button.setEnabled(False)
        self.disconnect_button.setEnabled(False)
        self.status_label.setText("Waiting for Google sign-in (up to two minutes)..." if action == "gmail_connect" else "Disconnecting...")
        results = self._results

        def run():
            try:
                result = operation()
            except Exception:
                result = CommandResult(False, "Gmail setup failed. Check the optional dependencies and Google client configuration.")
            result = result.with_metadata(action=action, metadata={**result.metadata, "private_content": True})
            # Keep Qt access on the UI thread, including after the dialog closes.
            results.put(result)

        threading.Thread(target=run, daemon=True, name="jarvis-gmail-setup").start()
        self._timer.start()

    def _poll(self):
        try:
            result = self._results.get_nowait()
        except Empty:
            return
        self._timer.stop()
        self._busy = False
        self.status_label.setText(result.message)
        self.connect_button.setEnabled(True)
        self.disconnect_button.setEnabled(True)
        AuditLogger().log(result.action, result, self.service.dry_run, source="gmail_settings")

    def reject(self):
        self._cancelled.set()
        super().reject()

    def shutdown(self):
        self._closed = True
        self._cancelled.set()
        self._timer.stop()
        self.hide()
