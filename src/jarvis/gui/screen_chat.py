"""Native screen discussion with opt-in, permission-gated command and voice modes."""
import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QStyle, QToolButton, QVBoxLayout

from ..ai_client import JarvisAI
from ..config import ensure_openai_api_key_visible
from ..models import CommandResult
from ..user_settings import JarvisSettings
from ..project_workspace import ProjectWorkspace
from ..project_changes import ProjectChanges
from ..vision.sharing import ScreenSharing
from .screen_sharing import ScreenSharingIndicator
from .project_changes import ProjectChangesDialog
from .panel_voice import PanelVoiceControls
from .discussion_style import DISCUSSION_STYLE, discussion_icon
from .aurora import DialogHeader, chip, composer, set_role


SCREEN_CHAT_MODEL = "gpt-5.6-sol"


class ScreenChatDialog(QDialog):
    command_submitted = Signal(str, str)
    command_cancel_requested = Signal()
    sharing_started = Signal()
    _finished = Signal(int, object)
    _captured = Signal(int)
    _action = Signal(int, object)

    def __init__(self, parent=None, *, dry_run=False, ai=None, settings=None):
        super().__init__(parent)
        client = ai if ai is not None else JarvisAI(dry_run=dry_run, settings=settings if settings is not None else JarvisSettings.load())
        self.voice_controller = None
        self._command_pending = False
        self.sharing = ScreenSharing(client, dry_run=dry_run, chat_only=True)
        self.indicator = ScreenSharingIndicator(self.sharing)
        self._generation = 0
        self._busy = False
        self._thread = None
        self._restore_windows = []
        self._closing = False
        self._retry_question = ""
        self._project = None
        self._actions = []
        self._changes = None
        self._project_panel = None
        self._check_context = ""
        self._sharing_was_ready = False
        self.setWindowTitle("Jarvis | Screen Chat")
        self.resize(680, 650)
        self.setMinimumSize(460, 480)
        self.setStyleSheet(DISCUSSION_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)
        header = DialogHeader("monitor", "Screen Chat",
                              "Talk about what is on your screen. Actions run only with Commands on.")
        self.model_label = header.add_action(chip(str(getattr(client, "model", SCREEN_CHAT_MODEL))))
        layout.addWidget(header)
        self.voice_controls = PanelVoiceControls(self, commands=True)
        self.voice_controls.mode_changed.connect(self._mode_changed)
        self.voice_controls.call_requested.connect(self.toggle_voice)
        self.voice_controls.mute_changed.connect(lambda muted: self.voice_controller.mute(self, muted) if self.voice_controller else None)
        self.voice_controls.interrupt_requested.connect(lambda: self.voice_controller.interrupt(self) if self.voice_controller else None)
        self.voice_controls.commands.toggled.connect(self._sync)
        layout.addWidget(self.voice_controls)
        controls = QHBoxLayout()
        self.share = QPushButton("Share screen")
        self.share.setIcon(discussion_icon(self.style(), QStyle.StandardPixmap.SP_ComputerIcon))
        self.share.clicked.connect(self._toggle_share)
        controls.addWidget(self.share)
        controls.addStretch()
        self.clear = self._button(QStyle.StandardPixmap.SP_DialogResetButton, "Clear screen discussion")
        self.clear.clicked.connect(self.clear_chat)
        controls.addWidget(self.clear)
        self.retry = self._button(QStyle.StandardPixmap.SP_BrowserReload, "Retry the failed question with a new screen image")
        self.retry.clicked.connect(self.retry_question)
        controls.addWidget(self.retry)
        self.stop = self._button(QStyle.StandardPixmap.SP_MediaStop, "Stop screen sharing and cancel the pending answer")
        self.stop.clicked.connect(self.stop_sharing)
        controls.addWidget(self.stop)
        layout.addLayout(controls)
        project_row = QHBoxLayout()
        self.choose_project = self._button(QStyle.StandardPixmap.SP_DirOpenIcon, "Choose a project for read-only analysis")
        self.choose_project.clicked.connect(self._select_project)
        project_row.addWidget(self.choose_project)
        self.project_label = QLabel("No project selected")
        self.project_label.setWordWrap(True)
        self.project_label.setTextFormat(Qt.TextFormat.PlainText)
        self.project_label.setMinimumWidth(0)
        project_row.addWidget(self.project_label, 1)
        self.detach_project = self._button(QStyle.StandardPixmap.SP_DialogCloseButton, "Remove project access and clear discussion")
        self.detach_project.clicked.connect(self._remove_project)
        project_row.addWidget(self.detach_project)
        self.actions_button = self._button(QStyle.StandardPixmap.SP_FileDialogDetailedView, "What was checked? Read-only action history")
        self.actions_button.clicked.connect(self._show_actions)
        project_row.addWidget(self.actions_button)
        self.changes_button = self._button(QStyle.StandardPixmap.SP_FileDialogContentsView, "Review project patches and run checks")
        self.changes_button.clicked.connect(self._show_changes)
        project_row.addWidget(self.changes_button)
        layout.addLayout(project_row)
        self.status = QLabel("Screen not shared")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.messages = QPlainTextEdit()
        self.messages.setReadOnly(True)
        self.messages.document().setMaximumBlockCount(1200)
        self.messages.setPlaceholderText("Share the screen, then ask about anything on it.")
        layout.addWidget(self.messages, 1)
        self.question = QLineEdit()
        self.question.setMaxLength(3000)
        self.question.setPlaceholderText("Ask about your screen...")
        self.question.returnPressed.connect(self.send_question)
        self.send = self._button(QStyle.StandardPixmap.SP_ArrowForward, "Send screen question")
        set_role(self.send, "send")
        self.send.setFixedSize(32, 32)
        self.send.setIcon(discussion_icon(self.style(), QStyle.StandardPixmap.SP_ArrowForward, color="#04131A"))
        self.send.clicked.connect(self.send_question)
        layout.addWidget(composer(self.question, self.send))
        self._finished.connect(self._on_finished)
        self._captured.connect(self._on_captured)
        self._action.connect(self._on_action)
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._sync)
        self._timer.start()
        self._sync()

    def _button(self, icon, title):
        button = QToolButton()
        button.setIcon(discussion_icon(self.style(), icon))
        button.setProperty("role", "ghost")
        button.setFixedSize(34, 34)
        button.setToolTip(title)
        button.setAccessibleName(title)
        return button

    def open_chat(self):
        self._closing = False
        self.show()
        self.raise_()
        self.activateWindow()
        self.question.setFocus()

    def _toggle_share(self):
        if self.voice_controller and self.voice_controller.owner is self:
            self.stop_sharing()
            return
        if self.sharing.state()["sharing"]:
            self.stop_sharing()
            return
        ensure_openai_api_key_visible()
        answer = QMessageBox.question(self, "Share screen with OpenAI",
            "Each question sends a new image of your primary screen to OpenAI, along with recent screen discussion. "
            "API charges apply. This is image analysis, not continuous video. Sharing remains enabled until Stop or closing this chat. "
            "Jarvis windows briefly hide for capture. Start sharing?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._generation += 1
        result = self.sharing.start()
        if result.ok and self.sharing.state()["sharing"]:
            self.messages.clear()
            self.sharing_started.emit()
            self.indicator.refresh()
            self.status.setText("Screen shared | Ready")
        else:
            self.status.setText(result.message)
        self._sync()

    def _sync(self):
        if not hasattr(self, "send"):
            return
        active = self.sharing.state()["ready"]
        voice_active = bool(self.voice_controller and self.voice_controller.owner is self and self.voice_controller.active)
        if self._sharing_was_ready and not active:
            if self._changes is not None:
                self._changes.discard()
            if self._project_panel is not None:
                self._project_panel.cancel_check()
        self._sharing_was_ready = active
        checking = self._project_panel is not None and self._project_panel.session_active
        self.send.setEnabled((active or self.voice_controls.commands.isChecked()) and not self._busy and not checking and not voice_active and not self._command_pending)
        self.retry.setEnabled(active and not self._busy and bool(self._retry_question))
        self.share.setEnabled(not self._busy or active)
        self.share.setText("Stop sharing" if self.sharing.state()["sharing"] or voice_active else "Share screen")
        self.stop.setEnabled(self._busy or self.sharing.state()["sharing"] or voice_active or self._command_pending)
        self.choose_project.setEnabled(not self._busy)
        self.detach_project.setEnabled(self._project is not None)
        self.actions_button.setEnabled(bool(self._actions))
        self.changes_button.setEnabled(self._project is not None)
        if not active and (self.status.text().startswith(("Screen shared", "Project:")) or self.status.text() in {
                "Capturing screen...", "Thinking..."}):
            self.status.setText("Screen not shared")

    def send_question(self):
        question = self.question.text().strip()
        if self._project_panel is not None and self._project_panel.session_active:
            return
        if self.voice_controller and self.voice_controller.owner is self and self.voice_controller.active:
            return
        if self.voice_controls.commands.isChecked() and question and not self._busy and not self._command_pending:
            self._command_pending = True
            self.messages.appendPlainText("You\n" + question + "\n")
            self.question.clear()
            self.status.setText("Command pending...")
            self.command_submitted.emit(question, f"screen_chat_command:{self._generation}")
            self._sync()
            return
        if not question or self._busy or not self.sharing.state()["ready"] or (self._project_panel is not None and self._project_panel.session_active):
            return
        self._busy = True
        self._retry_question = ""
        self._submitted_question = question
        generation = self._generation
        self.messages.appendPlainText("You\n" + question + "\n")
        self.question.clear()
        self.status.setText("Capturing screen...")
        self._sync()
        # Hide only Jarvis's own windows, not the user's foreground application.
        self._restore_windows = [widget for widget in (self.parentWidget(), self, self._project_panel)
            if widget is not None and widget.isVisible() and not widget.isMinimized()]
        for widget in self._restore_windows:
            widget.hide()
        QTimer.singleShot(180, lambda: self._launch(question, generation))

    def _launch(self, question, generation):
        if generation != self._generation or self._closing:
            self._busy = False
            self._restore()
            self._sync()
            return
        project, changes, check_context = self._project, self._changes, self._check_context
        def work():
            original = self.sharing._snapshot
            def capture():
                try:
                    return original()
                finally:
                    self._captured.emit(generation)
            self.sharing._snapshot = capture
            try:
                if project is None:
                    result = self.sharing.ask(question)
                else:
                    result = self.sharing.ask(question, project=project,
                        on_action=lambda item: self._action.emit(generation, item), changes=changes, check_context=check_context)
            except Exception:
                result = CommandResult(False, "Screen Chat failed. No action was executed.")
            finally:
                self.sharing._snapshot = original
            self._finished.emit(generation, result)
        self._thread = threading.Thread(target=work, daemon=True, name="jarvis-screen-chat")
        self._thread.start()

    def _restore(self):
        windows, self._restore_windows = self._restore_windows, []
        if self._closing:
            return
        for widget in windows:
            widget.show()
        if windows:
            self.raise_()

    def _on_captured(self, generation):
        self._restore()
        if generation == self._generation and not self._closing:
            self.status.setText("Thinking...")

    def _on_finished(self, generation, result):
        self._busy = False
        self._restore()
        if generation == self._generation and not self._closing and self.sharing.state()["ready"]:
            self.messages.appendPlainText(("Jarvis" if result.ok else "Error") + "\n" + result.message + "\n")
            self._retry_question = "" if result.ok else self._submitted_question
            self.status.setText("Screen shared | Ready" if result.ok else result.message)
        self._sync()

    def stop_sharing(self):
        if self.voice_controller:
            self.voice_controller.stop(self)
        if self._command_pending:
            self.command_cancel_requested.emit()
            self._command_pending = False
        self._generation += 1
        self._retry_question = ""
        self.indicator.stop()
        if self._changes is not None:
            self._changes.discard()
        if self._project_panel is not None:
            self._project_panel.cancel_check()
        self._restore()
        self.status.setText("Screen sharing stopped")
        self._sync()

    def clear_chat(self):
        self.stop_sharing()
        if self._changes is not None:
            self._changes.revoke()
        if self._project_panel is not None:
            self._project_panel.shutdown()
        self._changes, self._project_panel, self._check_context = None, None, ""
        self._project = None
        self.project_label.setText("No project selected")
        self.project_label.setToolTip("")
        self._actions.clear()
        self.messages.clear()
        self.question.clear()
        self._sync()

    def _select_project(self):
        if self._busy:
            return
        path = QFileDialog.getExistingDirectory(self, "Select project for Screen Chat")
        if not path:
            return
        try:
            project = ProjectWorkspace(path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Project unavailable", str(exc))
            return
        answer = QMessageBox.question(self, "Allow project reading",
            "Allow the configured OpenAI model to list, search and read supported files in this project when you ask a screen question? "
            "Selected excerpts and paths are sent to OpenAI. One question can use up to six model requests, with API charges. "
            "No files are edited and no commands are run. "
            "Private paths, recognized credentials, linked paths and generated folders are excluded. "
            "Choosing a project clears the previous discussion. Clear, Remove or closing this chat revokes access.\n\n" + str(project.root),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.clear_chat()
        self._project = project
        self._changes = ProjectChanges(project)
        self._project_panel = ProjectChangesDialog(self._changes, self, dry_run=self.sharing.dry_run, ai=self.sharing.ai)
        self._project_panel.verification_changed.connect(self._on_verification)
        self.project_label.setText(project.root.name + " | Read only")
        self.project_label.setToolTip(str(project.root))
        self._sync()

    def _remove_project(self):
        self.clear_chat()

    def _show_changes(self):
        if self._project_panel is not None:
            self._project_panel.refresh()
            self._project_panel.show()
            self._project_panel.raise_()

    def _on_verification(self, text):
        self._check_context = text
        self.messages.appendPlainText("Local project result\n" + text[:2000] + "\n")

    def _on_action(self, generation, item):
        if generation != self._generation or self._closing:
            return
        self._actions = (self._actions + [item])[-100:]
        self.status.setText("Project: " + item["tool"] + (" | checked" if item["ok"] else " | unavailable"))
        self._sync()

    def _show_actions(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("What was checked?")
        dialog.resize(560, 400)
        layout = QVBoxLayout(dialog)
        report = QPlainTextEdit()
        report.setReadOnly(True)
        report.setPlainText("\n\n".join(
            f"{item['time_utc']}\n{item['tool']} {item['path']}\n"
            + ("Checked" if item["ok"] else "Unavailable")
            + (" | Search/read limits reached" if item["limited"] else "")
            for item in self._actions))
        layout.addWidget(report)
        dialog.exec()

    def retry_question(self):
        if self.retry.isEnabled():
            self.question.setText(self._retry_question)
            self.send_question()

    def closeEvent(self, event):
        self.clear_chat()
        self._closing = True
        super().closeEvent(event)

    def reject(self):
        self.clear_chat()
        self._closing = True
        super().reject()

    def shutdown(self):
        if self.voice_controller:
            self.voice_controller.stop(self)
        if self._command_pending:
            self.command_cancel_requested.emit()
            self._command_pending = False
        self._closing = True
        self._generation += 1
        if self._changes is not None:
            self._changes.revoke()
        if self._project_panel is not None:
            self._project_panel.shutdown()
        self._project = None
        self._actions.clear()
        self._timer.stop()
        self.indicator.shutdown()
        self._restore_windows = []
        self.hide()

    def on_command_result(self, source, text, result):
        if source != f"screen_chat_command:{self._generation}" or self._closing:
            return
        self._command_pending = False
        self.messages.appendPlainText(("Jarvis" if result.ok else "Error") + "\n" + result.message + "\n")
        self.status.setText("Command finished" if result.ok else result.message)
        self._sync()

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
        if self._busy or self._command_pending or (self._project_panel is not None and self._project_panel.session_active):
            self.voice_controls.state.setText("Wait for the current request to finish.")
            return
        commands = self.voice_controls.commands.isChecked()
        answer = QMessageBox.question(self, "Start screen voice",
            "Send microphone audio and changing primary-screen images to OpenAI until Stop? API charges apply. "
            "Images update periodically, not continuous video. Close private windows first. "
            + ("Requested laptop commands use normal Jarvis permissions." if commands else "Discussion only; no computer actions."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            self.voice_controls.text_mode.setChecked(True)
            return
        self.stop_sharing()
        controller.start(self, context="Discuss the visible screen. Ask when text is unreadable.", screen=True, commands=commands)
        self._sync()

    def append_voice_transcript(self, who, text):
        self.messages.appendPlainText(who + "\n" + text + "\n")
