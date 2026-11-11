"""On-demand gaming discussion with opt-in voice, independent of action execution."""
from html import escape
from queue import Empty, Queue
import threading
from urllib.parse import urlsplit

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCursor, QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFormLayout,
                               QLabel, QLineEdit, QMessageBox, QStyle, QTextBrowser, QToolButton, QVBoxLayout)

from ..config import ensure_openai_api_key_visible
from ..models import CommandResult
from .panel_voice import PanelVoiceControls
from .discussion_style import DISCUSSION_STYLE, discussion_icon
from .aurora import DialogHeader, composer, set_role


class GameChatDialog(QDialog):
    def __init__(self, ai, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.ai = ai
        self.voice_controller = None
        self.history = []
        self._game_context = None
        self._generation = 0
        self._busy = False
        self._closed = False
        self._queue = Queue(maxsize=1)
        self._thread = None
        self.setWindowTitle("Jarvis | Game Chat")
        self.resize(480, 620)
        self.setMinimumSize(380, 480)
        self.setStyleSheet(DISCUSSION_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        header = DialogHeader("game", "Game Chat", "Your coach while you play · Ctrl+Alt+Space")
        self.clear_button = self._button(QStyle.StandardPixmap.SP_DialogResetButton, "Clear discussion", self.clear_chat)
        self.hide_button = self._button(QStyle.StandardPixmap.SP_TitleBarCloseButton, "Hide game chat", self.hide)
        header.add_action(self.clear_button)
        header.add_action(self.hide_button)
        layout.addWidget(header)
        self.voice_controls = PanelVoiceControls(self, screen_optional=True)
        self.voice_controls.mode_changed.connect(self._mode_changed)
        self.voice_controls.call_requested.connect(self.toggle_voice)
        self.voice_controls.mute_changed.connect(lambda muted: self.voice_controller.mute(self, muted) if self.voice_controller else None)
        self.voice_controls.interrupt_requested.connect(lambda: self.voice_controller.interrupt(self) if self.voice_controller else None)
        layout.addWidget(self.voice_controls)
        form = QFormLayout()
        self.game = QLineEdit()
        self.game.setMaxLength(120)
        self.game.setPlaceholderText("Valorant, Minecraft, Elden Ring...")
        self.context = QLineEdit()
        self.context.setMaxLength(600)
        self.context.setPlaceholderText("Map, mode, rank or build (optional)")
        form.addRow("Game", self.game)
        form.addRow("Context", self.context)
        layout.addLayout(form)
        self.web = QCheckBox("Web search")
        self.web.setToolTip("Allow OpenAI web search for patch notes and current game information. API charges apply.")
        self.web.toggled.connect(lambda: self.voice_controller.stop(self) if self.voice_controller else None)
        layout.addWidget(self.web)
        self.messages = QTextBrowser()
        self.messages.setOpenLinks(False)
        self.messages.setOpenExternalLinks(False)
        self.messages.anchorClicked.connect(self._open_source)
        self.messages.document().setMaximumBlockCount(300)
        layout.addWidget(self.messages, 1)
        self.status = QLabel("Ready")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.question = QLineEdit()
        self.question.setMaxLength(3000)
        self.question.setPlaceholderText("Ask about the game...")
        self.question.setToolTip("Sends your question, game context and recent game chat to OpenAI. API charges apply.")
        self.question.returnPressed.connect(self.send_question)
        self.send_button = self._button(QStyle.StandardPixmap.SP_ArrowForward, "Send to OpenAI", self.send_question)
        set_role(self.send_button, "send")
        self.send_button.setFixedSize(32, 32)
        self.send_button.setIcon(discussion_icon(self.style(), QStyle.StandardPixmap.SP_ArrowForward, color="#04131A"))
        self.cancel_button = self._button(QStyle.StandardPixmap.SP_MediaStop, "Discard pending answer (provider request may finish)", self.cancel)
        self.cancel_button.setEnabled(False)
        layout.addWidget(composer(self.question, self.cancel_button, self.send_button))
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._poll)
        self.game.textChanged.connect(self._context_changed)
        self.context.textChanged.connect(self._context_changed)

    def _button(self, icon, title, callback):
        button = QToolButton()
        button.setIcon(discussion_icon(self.style(), icon))
        button.setProperty("role", "ghost")
        button.setFixedSize(32, 32)
        button.setToolTip(title)
        button.setAccessibleName(title)
        button.clicked.connect(callback)
        return button

    def open_chat(self):
        if self._closed:
            return
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen and not self.isVisible():
            area = screen.availableGeometry()
            self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
            self.move(area.right()-self.width()-16, area.top()+16)
        self.show()
        self.raise_()
        self.activateWindow()
        (self.question if self.game.text().strip() else self.game).setFocus()

    def toggle(self):
        if self.isVisible():
            self.hide()
        else:
            self.open_chat()

    def reject(self):
        self.hide()

    def closeEvent(self, event):
        self.hide()
        event.ignore()

    def _context_changed(self):
        current = (self.game.text().strip(), self.context.text().strip())
        if self._game_context != current:
            self.clear_chat()
            self._game_context = current

    def _set_busy(self, busy):
        self._busy = busy
        self.send_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)

    def _append(self, who, text):
        # Speaker in the Aurora accent (Jarvis) or muted (you), then the text.
        color = "#67E8F9" if who == "Jarvis" else "#F28B82" if who == "Error" else "#A2AEBB"
        self.messages.append(f'<p style="margin-bottom:10px"><span style="color:{color};font-weight:600">'
                             f'{escape(who)}</span><br>{escape(text).replace(chr(10), "<br>")}</p>')

    def send_question(self):
        if self.voice_controller and self.voice_controller.owner is self and self.voice_controller.active:
            self.status.setText("Stop voice before sending a text question.")
            return
        if self._closed or self._busy:
            return
        game, context, question = self.game.text().strip(), self.context.text().strip(), self.question.text().strip()
        if not game or not question:
            self.status.setText("Enter a game and a question.")
            return
        self._context_changed()
        ensure_openai_api_key_visible()
        generation = self._generation
        history = [dict(t) for t in self.history]
        web = self.web.isChecked()
        self._append("You", question)
        self.question.clear()
        self._set_busy(True)
        self.status.setText("Thinking...")
        results, ai = self._queue, self.ai

        def run():
            try:
                result = ai.answer_game_question(question, game=game, context=context, history=history, web=web)
            except Exception:
                result = CommandResult(False, "Gaming advice unavailable. Please retry.")
            results.put((generation, question, result))

        self._thread = threading.Thread(target=run, daemon=True, name="jarvis-game-chat")
        self._thread.start()
        self._timer.start()

    def _poll(self):
        try:
            generation, question, result = self._queue.get_nowait()
        except Empty:
            return
        self._timer.stop()
        self._set_busy(False)
        if self._closed or generation != self._generation:
            if not self._closed:
                self.status.setText("Ready | Previous answer discarded")
            return
        if not result.ok:
            self.status.setText(result.message)
            if not self.question.text():
                self.question.setText(question)
            return
        self._append("Jarvis", result.message)
        for source in result.metadata.get("sources", []):
            url, title = source["url"], source["title"]
            self.messages.append(f'<a style="color:#67E8F9" href="{escape(url, quote=True)}">{escape(title)}</a>')
        self.history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": result.message[:4000]}])
        self.history = self.history[-10:]
        self.status.setText("Ready")

    def cancel(self):
        if self._busy:
            self._generation += 1
            self.cancel_button.setEnabled(False)
            self.status.setText("Answer discarded; waiting for request to finish.")

    def clear_chat(self):
        if self.voice_controller:
            self.voice_controller.stop(self)
        self._generation += 1
        self.history.clear()
        self.messages.clear()
        self.status.setText("Discussion cleared" if not self._busy else "Discussion cleared; waiting for request to finish.")

    def shutdown(self):
        if self.voice_controller:
            self.voice_controller.stop(self)
        self._closed = True
        self._generation += 1
        self.history.clear()
        self.messages.clear()
        self._timer.stop()
        self.hide()

    def _mode_changed(self, index):
        if index == 0:
            if self.voice_controller:
                self.voice_controller.stop(self)
        else:
            self.toggle_voice()

    def toggle_voice(self):
        controller = self.voice_controller
        if controller is None:
            self.voice_controls.state.setText("Voice is available in the full Jarvis application.")
            return
        if controller.owner is self and controller.active:
            controller.stop(self)
            return
        if self._busy or not self.game.text().strip():
            self.voice_controls.state.setText("Enter the game and wait for any pending answer.")
            return
        screen = self.voice_controls.screen.isChecked()
        answer = QMessageBox.question(self, "Start gaming voice",
            "Send microphone audio to OpenAI for a gaming conversation? API charges apply. "
            + ("Also share changing primary-screen images until Stop. Close private windows first. " if screen else "No screen images will be sent. ")
            + "This call gives advice, not game control. Hiding the chat keeps this call active; use Stop to end it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            self.voice_controls.text_mode.setChecked(True)
            return
        controller.start(self, context=f"Game: {self.game.text()}. Situation: {self.context.text()}",
                         game=self.game.text().strip(), web=self.web.isChecked(), screen=screen)

    def append_voice_transcript(self, who, text):
        self._append(who, text)

    @staticmethod
    def _open_source(url):
        try:
            parsed = urlsplit(url.toString())
            if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password:
                QDesktopServices.openUrl(url)
        except ValueError:
            pass
