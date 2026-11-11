from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QKeySequence, QLinearGradient, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                              QPlainTextEdit, QPushButton, QStyle, QToolButton, QVBoxLayout, QWidget)

from ..privacy import redact_sensitive_text
from .voice_core import AURORA, BASE_STYLE, FONT_BODY, FONT_SEMIBOLD, apply_window_corners, glyph_icon

_STATE_LABELS = {
    "idle": "Jarvis",
    "listening": "Listening...",
    "processing": "Thinking...",
    "unclear": "Didn't catch that",
    "warning": "Attention needed",
}

_A = AURORA
_STATE_COLORS = {
    "idle": _A["accent"],
    "listening": _A["accent_light"],
    "processing": _A["accent_2_light"],
    "unclear": _A["warning"],
    "warning": _A["danger"],
}

OVERLAY_STYLE = BASE_STYLE + f"""
#commandOverlay {{ background: {_A['bg_raised']}; }}
#commandOverlay[chrome="plain"] {{ border: 1px solid {_A['border_strong']}; }}
#commandOverlay QLabel[role="state"] {{ color: {_A['text']}; font-family: {FONT_SEMIBOLD}; font-weight: 600; }}
#commandOverlay QLabel[role="hint"] {{ color: {_A['text_tertiary']}; font-size: 11px; }}
#commandOverlay QLabel[role="kbd"] {{ color: {_A['text_secondary']}; font-size: 11px; background: {_A['card']};
    border: 1px solid {_A['border_strong']}; border-radius: 4px; padding: 0 5px; }}
#commandOverlay QFrame[role="divider"] {{ background: {_A['border']}; border: none; }}
#commandOverlay QToolButton {{ background: transparent; border: none; border-radius: 8px; }}
#commandOverlay QToolButton:hover {{ background: rgba(255, 255, 255, 14); }}
#commandOverlay QToolButton:pressed {{ background: rgba(255, 255, 255, 8); }}
#commandOverlay QToolButton#sendButton {{ border-radius: 20px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent']}, stop:1 {_A['accent_2']}); }}
#commandOverlay QToolButton#sendButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent_light']}, stop:1 {_A['accent_2_light']}); }}
#commandOverlay QToolButton#sendButton:pressed {{ background: {_A['accent']}; }}
#modeSwitch {{ background: {_A['input']}; border: 1px solid {_A['border']}; border-radius: 15px; }}
#modeSwitch QPushButton {{ background: transparent; border: none; border-radius: 12px; padding: 4px 12px;
    color: {_A['text_secondary']}; font-family: {FONT_BODY}; font-weight: 400; font-size: 12px; }}
#modeSwitch QPushButton:hover {{ color: {_A['text']}; }}
#modeSwitch QPushButton:checked {{ background: rgba(34, 211, 238, 34); color: {_A['accent_light']};
    font-family: {FONT_SEMIBOLD}; font-weight: 600; }}
#commandOverlay QLineEdit#commandInput {{ font-size: 16px; padding: 10px 14px; border-radius: 12px; }}
#commandOverlay QPlainTextEdit#commandOutput {{ background: transparent; border: none; padding: 0;
    color: {_A['text']}; font-size: 13px; }}
#commandOverlay QPlainTextEdit#commandOutput[tone="error"] {{ color: {_A['danger']}; }}
#commandOverlay QPlainTextEdit#commandOutput[tone="pending"] {{ color: {_A['text_secondary']}; }}
"""


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class _Shimmer(QWidget):
    """A thin light sweep along the palette's top edge while Jarvis works."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._offset = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_active(self, active: bool) -> None:
        if active and not self._timer.isActive():
            self._offset = 0.0
            self.show()
            self.raise_()
            self._timer.start()
        elif not active and self._timer.isActive():
            self._timer.stop()
            self.hide()

    def is_active(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        self._offset = (self._offset + 0.02) % 1.5
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        width = self.width()
        center = (self._offset - 0.25) * width
        sweep = QLinearGradient(center - width * 0.22, 0, center + width * 0.22, 0)
        edge = QColor(_A["accent"])
        edge.setAlpha(0)
        sweep.setColorAt(0.0, edge)
        sweep.setColorAt(0.5, QColor(_A["accent_light"]))
        tail = QColor(_A["accent_2_light"])
        tail.setAlpha(0)
        sweep.setColorAt(1.0, tail)
        painter.fillRect(self.rect(), sweep)


class OverlayWidget(QWidget):
    """Native command palette. Shares the audited executor, never owns actions."""

    command_submitted = Signal(str, str)
    activity_requested = Signal()
    undo_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool,
        )
        self._chrome_applied = False
        self._pending = False
        self._voice_state = "idle"
        self._build_ui()

    def _build_ui(self) -> None:
        self.setWindowTitle("Jarvis command overlay")
        self.setObjectName("commandOverlay")
        # Opaque on purpose: a translucent frameless window costs a layered
        # window and blurs nothing on Windows anyway. Rounded corners come
        # from DWM on Windows 11 (see showEvent); elsewhere a hairline border.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("chrome", "plain")
        self.setStyleSheet(OVERLAY_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 14, 12)
        layout.setSpacing(12)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._dot = QLabel()
        self._dot.setFixedSize(8, 8)
        header.addWidget(self._dot)
        self._label = QLabel(_STATE_LABELS["idle"])
        self._label.setProperty("role", "state")
        header.addWidget(self._label)
        header.addStretch()

        # The combo stays the single source of truth for the mode (callers and
        # tests drive it); the segmented switch is its visible face.
        self.mode = QComboBox(self)
        for label, mode in (("Разговор", "overlay"), ("Локално", "overlay_local"), ("Научи ме", "overlay_teach")):
            self.mode.addItem(label, mode)
        self.mode.setAccessibleName("Command mode")
        self.mode.setToolTip("Local and Teach do not send this command to AI. An existing live voice call remains active until stopped.")
        self.mode.hide()
        switch = QFrame()
        switch.setObjectName("modeSwitch")
        switch.setToolTip(self.mode.toolTip())
        switch_layout = QHBoxLayout(switch)
        switch_layout.setContentsMargins(3, 3, 3, 3)
        switch_layout.setSpacing(2)
        self._mode_buttons = QButtonGroup(self)
        self._mode_buttons.setExclusive(True)
        for index in range(self.mode.count()):
            button = QPushButton(self.mode.itemText(index))
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(f"Command mode: {self.mode.itemText(index)}")
            self._mode_buttons.addButton(button, index)
            switch_layout.addWidget(button)
        self._mode_buttons.idClicked.connect(self.mode.setCurrentIndex)
        self.mode.currentIndexChanged.connect(self._sync_mode)
        self._sync_mode(self.mode.currentIndex())
        header.addWidget(switch)
        header.addSpacing(6)

        for glyph, fallback, title, callback in (
            ("history", QStyle.StandardPixmap.SP_FileDialogContentsView, "Какво направи?", self.activity_requested.emit),
            ("undo", QStyle.StandardPixmap.SP_ArrowBack, "Undo Center", self.undo_requested.emit),
            ("cancel", QStyle.StandardPixmap.SP_BrowserStop, "Спри задачата", self.cancel_requested.emit),
            ("close", QStyle.StandardPixmap.SP_TitleBarCloseButton, "Затвори", self.hide),
        ):
            button = QToolButton()
            button.setIcon(glyph_icon(glyph, fallback, self.style(), size=16))
            button.setIconSize(QSize(16, 16))
            button.setToolTip(title)
            button.setAccessibleName(title)
            button.setFixedSize(30, 30)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(callback)
            header.addWidget(button)
        layout.addLayout(header)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.command_input = QLineEdit()
        self.command_input.setObjectName("commandInput")
        self.command_input.setPlaceholderText("Кажи на Jarvis какво да направи…")
        self.command_input.setAccessibleName("Jarvis command")
        self.command_input.setMaxLength(4000)
        self.command_input.addAction(
            glyph_icon("sparkle", QStyle.StandardPixmap.SP_ArrowForward, self.style(), color=_A["accent_light"], size=18),
            QLineEdit.ActionPosition.LeadingPosition,
        )
        self.command_input.returnPressed.connect(self._submit)
        row.addWidget(self.command_input, 1)
        send = QToolButton()
        send.setObjectName("sendButton")
        send.setIcon(glyph_icon("send", QStyle.StandardPixmap.SP_ArrowForward, self.style(), color="#04131A", size=18))
        send.setIconSize(QSize(18, 18))
        send.setToolTip("Изпрати")
        send.setAccessibleName("Изпрати")
        send.setFixedSize(40, 40)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.clicked.connect(self._submit)
        row.addWidget(send)
        layout.addLayout(row)

        divider = QFrame()
        divider.setProperty("role", "divider")
        divider.setFixedHeight(1)
        layout.addWidget(divider)

        self.output = QPlainTextEdit()
        self.output.setObjectName("commandOutput")
        self.output.setReadOnly(True)
        self.output.setAccessibleName("Command result")
        self.output.setMaximumBlockCount(150)
        self.output.setPlaceholderText("Например: „звук на 30“ · „отвори youtube“ · „какво ми товари компютъра“")
        layout.addWidget(self.output, 1)

        footer = QHBoxLayout()
        footer.setSpacing(6)
        for key, action in (("Enter", "изпрати"), ("Esc", "затвори")):
            keycap = QLabel(key)
            keycap.setProperty("role", "kbd")
            footer.addWidget(keycap)
            hint = QLabel(action)
            hint.setProperty("role", "hint")
            footer.addWidget(hint)
            footer.addSpacing(8)
        footer.addStretch()
        privacy = QLabel("Локално и Научи ме не изпращат към AI")
        privacy.setProperty("role", "hint")
        footer.addWidget(privacy)
        layout.addLayout(footer)

        self._escape = QShortcut(QKeySequence("Escape"), self)
        self._escape.activated.connect(self.hide)
        self._shimmer = _Shimmer(self)
        self.set_state("idle")
        self.resize(660, 380)

    def _sync_mode(self, index: int) -> None:
        button = self._mode_buttons.button(index)
        if button is not None:
            button.setChecked(True)

    def _set_output_tone(self, tone: str) -> None:
        if self.output.property("tone") != tone:
            self.output.setProperty("tone", tone)
            _repolish(self.output)

    def _submit(self) -> None:
        text = self.command_input.text().strip()
        if text:
            self.output.setPlainText("Обработва се...")
            self._set_output_tone("pending")
            self.command_input.clear()
            self._pending = True
            self._sync_shimmer()
            self.command_submitted.emit(text, self.mode.currentData())

    def show_result(self, message: str, ok: bool) -> None:
        self.output.setPlainText(redact_sensitive_text(message).text[:12000])
        self._set_output_tone("ok" if ok else "error")
        self._pending = False
        self._sync_shimmer()

    def set_state(self, state: str) -> None:
        self._voice_state = state
        self._label.setText(_STATE_LABELS.get(state, state))
        color = _STATE_COLORS.get(state, _A["neutral"])
        self._dot.setStyleSheet(f"background: {color}; border-radius: 4px;")
        self._sync_shimmer()

    def _sync_shimmer(self) -> None:
        self._shimmer.set_active(self._pending or self._voice_state == "processing")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._shimmer.setGeometry(0, 0, self.width(), 2)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self._reposition()
            self.show()
            self.raise_()
            self.activateWindow()
            self.command_input.setFocus()

    def _reposition(self) -> None:
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.resize(min(660, max(320, geometry.width() - 40)), min(380, max(200, geometry.height() - 80)))
        x = geometry.center().x() - self.width() // 2
        y = geometry.top() + max(40, min(geometry.height() // 6, geometry.height() - self.height() - 20))
        self.move(x, y)

    def current_state_text(self) -> str:
        return self._label.text()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._chrome_applied:
            self._chrome_applied = True
            if apply_window_corners(self):
                self.setProperty("chrome", "rounded")
                _repolish(self)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)
