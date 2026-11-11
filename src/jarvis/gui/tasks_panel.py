from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QStyle, QVBoxLayout, QWidget

from ..privacy import redact_sensitive_text


class TasksPanel(QWidget):
    command_requested = Signal(str, str)
    cancel_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)
        title = QLabel("TASKS")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        goal_row = QHBoxLayout()
        self.goal = QLineEdit()
        self.goal.setPlaceholderText("Goal")
        self.goal.setMaxLength(3000)
        self.goal.returnPressed.connect(self._run_goal)
        goal_row.addWidget(self.goal, 1)
        self.run_button = QPushButton("Run")
        self.run_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
        self.run_button.clicked.connect(self._run_goal)
        goal_row.addWidget(self.run_button)
        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserStop))
        self.stop_button.setToolTip("Stop task after the current operation; cancel queued commands")
        self.stop_button.setAccessibleName("Stop task")
        self.stop_button.setFixedSize(40, 40)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.cancel_requested.emit)
        goal_row.addWidget(self.stop_button)
        layout.addLayout(goal_row)
        browser_row = QHBoxLayout()
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://")
        self.url.returnPressed.connect(self._open_browser)
        browser_row.addWidget(self.url, 1)
        open_button = QPushButton("Open")
        open_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DriveNetIcon))
        open_button.clicked.connect(self._open_browser)
        browser_row.addWidget(open_button)
        inspect_button = QPushButton()
        inspect_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogInfoView))
        inspect_button.setToolTip("Read managed browser page")
        inspect_button.setAccessibleName("Read managed browser page")
        inspect_button.setFixedSize(40, 40)
        inspect_button.clicked.connect(lambda: self.command_requested.emit("inspect browser", "task"))
        browser_row.addWidget(inspect_button)
        layout.addLayout(browser_row)
        self.status = QLabel("Idle")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.events = QListWidget()
        self.events.setWordWrap(True)
        self.events.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.events, 1)

    def _run_goal(self) -> None:
        if self.goal.text().strip() and self.run_button.isEnabled():
            self.command_requested.emit("agent mode " + self.goal.text().strip(), "task")

    def _open_browser(self) -> None:
        if self.url.text().strip():
            self.command_requested.emit("managed browser " + self.url.text().strip(), "task")

    def set_task_state(self, active: bool, message: str) -> None:
        self.run_button.setEnabled(not active)
        self.stop_button.setEnabled(active)
        self.status.setText(message)

    def add_progress(self, message: str) -> None:
        text = redact_sensitive_text(message).text
        self.status.setText(text[:300])
        self.events.addItem(text)
        while self.events.count() > 100:
            self.events.takeItem(0)
        self.events.scrollToBottom()

    def on_result(self, source: str, text: str, result) -> None:
        if source in {"task", "realtime"} or result.metadata.get("workflow"):
            self.add_progress(result.message[:16000])
