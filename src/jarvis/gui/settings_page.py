from __future__ import annotations

import os
import re
from pathlib import Path

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QLinearGradient, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..personality import DETAIL_LEVELS, HUMOR_LEVELS, PRESETS
from ..personality import normalize as normalize_personality
from ..personality import sample_line
from ..role_packs import PACKS, normalize_packs
from ..user_settings import SETTINGS_PATH, JarvisSettings
from . import autostart
from .settings_io import save_settings
from .voice_core import AURORA, BASE_STYLE, CHECK_IMAGE, FONT_BODY, FONT_SEMIBOLD, card_rules, glyph_icon

# Matches the exact keys router.py's GuiSafetyPolicy consults via
# settings.safety_enabled(key) -- see gui_safety.py's _ACTION_TO_SAFETY_KEY.
_SAFETY_LABELS = {
    "confirm_restart": "Confirm before restart",
    "confirm_shutdown": "Confirm before shutdown",
    "confirm_sleep": "Confirm before sleep",
    "confirm_network_changes": "Confirm before enabling/disabling internet adapters",
    "confirm_bluetooth_changes": "Confirm before enabling/disabling Bluetooth",
    "confirm_temp_cleanup": "Confirm before cleaning temp files",
    "confirm_gaming_mode": "Confirm before gaming mode",
    "confirm_undo": "Confirm before undoing the last reversible action",
}

# windows_actions.py's _preferred_browser_command() special-cases "opera_gx"
# with known install paths; any other key needs an explicit browser_paths
# entry to resolve to a real executable.
_BROWSER_CHOICES = ("", "opera_gx", "chrome", "edge")

# Matches windows_actions.py's apply_mode() defaults (quiet=20, study=35,
# battery=20, gaming=60) and temperature_warning()'s default (85) -- these
# are the values these controls save when a key isn't set yet.
_MODE_VOLUME_KEYS = (
    ("quiet_volume", "Quiet mode volume", 20),
    ("study_volume", "Study mode volume", 35),
    ("battery_volume", "Battery Saver mode volume", 20),
    ("gaming_volume", "Gaming mode volume", 60),
)
_TEMPERATURE_KEY = "temperature_warning_c"
_TEMPERATURE_DEFAULT = 85

_STT_PROVIDERS = ("google", "openai")
_TTS_PROVIDERS = ("windows", "openai")

# (label, settings code) -- code is what's stored in
# settings.openai["conversation_language"] and read by
# RealtimeVoiceConfig.from_settings()/SpeechToText/VoiceAssistant.
_CONVERSATION_LANGUAGES = (
    ("English", "en"),
    ("Bulgarian (Български)", "bg"),
    ("Auto-detect (Bulgarian / English)", "auto"),
)

_A = AURORA
_SP = QStyle.StandardPixmap

# BASE_STYLE is repeated here so the page also looks right on its own (tests,
# previews); inside MainWindow's settings dialog the same rules simply agree.
SETTINGS_STYLE = BASE_STYLE + card_rules("#settingsPage") + f"""
#settingsPage QScrollArea {{ background: transparent; border: none; }}
#settingsPage QScrollArea > QWidget > QWidget {{ background: transparent; }}
#settingsNav QPushButton {{ background: transparent; border: none; border-radius: 8px; padding: 8px 12px 8px 14px;
    text-align: left; color: {_A['text_secondary']}; font-family: {FONT_BODY}; font-weight: 400; font-size: 13px; }}
#settingsNav QPushButton:hover {{ background: rgba(255, 255, 255, 10); color: {_A['text']}; }}
#settingsNav QPushButton:checked {{ background: rgba(34, 211, 238, 24); color: {_A['text']};
    font-family: {FONT_SEMIBOLD}; font-weight: 600; }}
#settingsNav QLabel[role="overline"] {{ color: {_A['text_tertiary']}; font-family: {FONT_SEMIBOLD}; font-weight: 600;
    font-size: 10px; letter-spacing: 1.4px; padding: 14px 12px 4px 14px; }}
#settingsPage QLabel[role="rowTitle"] {{ color: {_A['text']}; }}
#settingsPage QLabel[role="rowHint"] {{ color: {_A['text_tertiary']}; font-size: 12px; }}
#settingsPage QLabel[role="cardHint"] {{ color: {_A['text_secondary']}; }}
#settingsPage QLabel[role="subheading"] {{ color: {_A['text_tertiary']}; font-family: {FONT_SEMIBOLD}; font-weight: 600;
    font-size: 10px; letter-spacing: 1.4px; padding: 14px 0 4px 0; }}
#settingsPage QLabel[role="status"] {{ color: {_A['warning']}; font-size: 12px; }}
#settingsPage QLabel[role="profileNote"] {{ color: {_A['accent_light']}; font-size: 12px; padding-bottom: 8px; }}
#settingsPage QLabel[role="saveStatus"] {{ color: {_A['success']}; }}
#settingsPage QFrame[role="divider"] {{ background: {_A['border']}; border: none; }}
#settingsFooter {{ border: none; border-top: 1px solid {_A['border']}; }}
#settingsPage QPushButton[role="ghost"] {{ background: transparent; border: 1px solid transparent; border-radius: 7px;
    color: {_A['text_secondary']}; padding: 5px 10px; font-size: 12px; }}
#settingsPage QPushButton[role="ghost"]:hover {{ background: rgba(255, 255, 255, 10); color: {_A['text']}; }}
#settingsPage QTableWidget, #settingsPage QListWidget {{ alternate-background-color: #0C1117; }}
#settingsPage QTableWidget::item, #settingsPage QListWidget::item {{ padding: 0 8px; border: none; }}
#settingsPage QListWidget::item {{ min-height: 30px; border-radius: 6px; }}
#settingsPage QTableWidget QLineEdit, #settingsPage QListWidget QLineEdit {{ padding: 0 6px; border-radius: 4px; }}
#settingsPage QFrame[role="previewBox"] {{ background: rgba(34, 211, 238, 12); border: 1px solid rgba(34, 211, 238, 70);
    border-radius: 10px; }}
#settingsPage QLabel[role="previewQuote"] {{ color: {_A['text']}; font-size: 14px; }}
#settingsPage QLabel[role="sliderValue"] {{ color: {_A['text_secondary']}; font-size: 12px; }}
#settingsPage QSlider::groove:horizontal {{ height: 4px; background: {_A['border_strong']}; border-radius: 2px; }}
#settingsPage QSlider::sub-page:horizontal {{ border-radius: 2px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {_A['accent']}, stop:1 {_A['accent_2']}); }}
#settingsPage QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -6px 0; border-radius: 8px;
    background: {_A['text']}; border: 2px solid {_A['accent']}; }}
#settingsPage QCheckBox {{ spacing: 10px; }}
#settingsPage QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid #3A4658;
    background: {_A['input']}; }}
#settingsPage QCheckBox::indicator:hover {{ border-color: #56657A; }}
#settingsPage QCheckBox::indicator:checked {{ border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent']}, stop:1 {_A['accent_2']}); }}
""" + (f'#settingsPage QCheckBox::indicator:checked {{ image: url("{CHECK_IMAGE}"); }}\n' if CHECK_IMAGE else "")
# The rules above only reach plain QCheckBoxes other modules add (app.py's
# Game Chat shortcut toggle); _ToggleSwitch paints itself.
_SHORTCUT_TEXT = re.compile(r"\b(ctrl|alt|shift|win)\s*\+", re.IGNORECASE)


def _role_label(text: str, role: str, *, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)  # "<alias>" must not be parsed as a tag
    label.setProperty("role", role)
    label.setWordWrap(wrap)
    return label


def _divider() -> QFrame:
    line = QFrame()
    line.setProperty("role", "divider")
    line.setFixedHeight(1)
    return line


def _mix(start: str, end: str, amount: float) -> QColor:
    a, b = QColor(start), QColor(end)
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * amount,
        a.greenF() + (b.greenF() - a.greenF()) * amount,
        a.blueF() + (b.blueF() - a.blueF()) * amount,
    )


class _ToggleSwitch(QCheckBox):
    """A QCheckBox drawn as a switch -- label on the left, pill on the right.

    Only painting and hit-testing change: checked state, toggled/blockSignals
    and every other QCheckBox API behave exactly as before, which is what
    app.py and the tests drive directly.
    """

    _TRACK = QSize(40, 20)
    _GAP = 16

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Keyboard users still Tab to it; a mouse click doesn't leave a focus ring behind.
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._progress = 0.0
        self._animation = QVariantAnimation(self)
        self._animation.setDuration(140)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.valueChanged.connect(self._on_progress)
        self.toggled.connect(self._animate_to)

    def _animate_to(self, checked: bool) -> None:
        start = self._knob_progress()
        self._animation.stop()
        if not self.isVisible():
            self.update()
            return
        self._animation.setStartValue(start)
        self._animation.setEndValue(1.0 if checked else 0.0)
        self._animation.start()

    def _on_progress(self, value) -> None:
        self._progress = float(value)
        self.update()

    def _knob_progress(self) -> float:
        # Loads use blockSignals(), so no animation runs -- read the real state.
        if self._animation.state() == QAbstractAnimation.State.Running:
            return self._progress
        return 1.0 if self.isChecked() else 0.0

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        width = metrics.horizontalAdvance(self.text()) + self._GAP + self._TRACK.width() + 4
        return QSize(width, max(metrics.height(), self._TRACK.height()) + 10)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: ARG002 - always repaints fully
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        enabled = self.isEnabled()
        track = QRectF(self.width() - self._TRACK.width() - 2, (self.height() - self._TRACK.height()) / 2,
                       self._TRACK.width(), self._TRACK.height())
        radius = track.height() / 2
        progress = self._knob_progress()
        hovered = enabled and self.underMouse()

        text_width = max(0, int(track.left()) - self._GAP)
        painter.setFont(self.font())
        painter.setPen(QColor(_A["text"] if enabled else _A["text_tertiary"]))
        painter.drawText(QRectF(0, 0, text_width, self.height()),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, text_width))

        if progress < 1:
            painter.setOpacity(1 - progress)
            painter.setPen(QPen(QColor("#56657A" if hovered else "#3A4658"), 1))
            painter.setBrush(QColor(_A["input"]))
            painter.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if progress > 0:
            painter.setOpacity(progress)
            gradient = QLinearGradient(track.topLeft(), track.bottomRight())
            gradient.setColorAt(0, QColor(_A["accent_light" if hovered else "accent"] if enabled else _A["border_strong"]))
            gradient.setColorAt(1, QColor(_A["accent_2_light" if hovered else "accent_2"] if enabled else _A["border_strong"]))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(gradient)
            painter.drawRoundedRect(track, radius, radius)
        painter.setOpacity(1)

        knob_off = _A["text_secondary"] if enabled else _A["text_tertiary"]
        knob_on = "#04131A" if enabled else _A["text_tertiary"]
        knob_radius = 6 if hovered else 5
        x = track.left() + radius + (track.width() - 2 * radius) * progress
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_mix(knob_off, knob_on, progress))
        painter.drawEllipse(QPointF(x, track.center().y()), knob_radius, knob_radius)

        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(_A["accent_light"]), 1.5))
            painter.drawRoundedRect(track.adjusted(-3, -3, 3, 3), radius + 3, radius + 3)
        painter.end()


class _ChoiceCard(QAbstractButton):
    """A selectable card -- title, description and a radio mark -- for the
    personality presets. Exclusivity comes from a QButtonGroup."""

    _PAD = 12
    _MARK = 16

    def __init__(self, title: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setText(title)
        self._description = description
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAccessibleName(title)
        self.setAccessibleDescription(description)
        policy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

    def _fonts(self) -> tuple[QFont, QFont]:
        title = QFont(self.font())
        title.setWeight(QFont.Weight.DemiBold)
        detail = QFont(self.font())
        detail.setPixelSize(max(10, self.fontInfo().pixelSize() - 1))
        return title, detail

    def _text_width(self, width: int) -> int:
        return max(40, width - 2 * self._PAD - self._MARK - 10)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        title, detail = self._fonts()
        wrapped = QFontMetrics(detail).boundingRect(QRect(0, 0, self._text_width(width), 2000),
                                                    Qt.TextFlag.TextWordWrap, self._description)
        return self._PAD + QFontMetrics(title).height() + 3 + wrapped.height() + self._PAD

    def sizeHint(self) -> QSize:
        return QSize(260, self.heightForWidth(260))

    def minimumSizeHint(self) -> QSize:
        return QSize(160, self.heightForWidth(160))

    def paintEvent(self, event) -> None:  # noqa: ARG002 - always repaints fully
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked, hovered = self.isChecked(), self.underMouse()
        outline = _A["accent"] if checked else ("#33415A" if hovered else _A["border_strong"])
        painter.setPen(QPen(QColor(outline), 1.5 if checked else 1.0))
        painter.setBrush(QColor(34, 211, 238, 22) if checked else QColor(_A["card_hover"] if hovered else _A["input"]))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75), 10, 10)
        title_font, detail_font = self._fonts()
        title_height = QFontMetrics(title_font).height()
        width = self._text_width(self.width())
        painter.setFont(title_font)
        painter.setPen(QColor(_A["text"]))
        painter.drawText(QRectF(self._PAD, self._PAD, width, title_height),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.text())
        painter.setFont(detail_font)
        painter.setPen(QColor(_A["text_secondary"]))
        painter.drawText(QRectF(self._PAD, self._PAD + title_height + 3, width, self.height()),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop) | int(Qt.TextFlag.TextWordWrap),
                         self._description)
        mark = QPointF(self.width() - self._PAD - self._MARK / 2, self._PAD + title_height / 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(_A["accent"] if checked else "#56657A"), 1.5))
        painter.drawEllipse(mark, 7, 7)
        if checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(_A["accent"]))
            painter.drawEllipse(mark, 3.5, 3.5)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(_A["accent_light"]), 1.5))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(2.5, 2.5, -2.5, -2.5), 8, 8)
        painter.end()


class _StatusLabel(QLabel):
    """A warning line under a control that only takes space while it has text
    (app.py and the toggle handlers set these directly)."""

    def __init__(self, text: str = "") -> None:
        super().__init__(text)
        self.setProperty("role", "status")
        self.setWordWrap(True)
        self.setVisible(bool(text))

    def setText(self, text: str) -> None:  # noqa: N802 - Qt override
        super().setText(text)
        self.setVisible(bool(text))


class _NavButton(QPushButton):
    """A settings navigation entry; the current one gets an accent pill."""

    def __init__(self, text: str, icon, parent: QWidget | None = None) -> None:
        super().__init__(icon, text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(18, 18))

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.isChecked():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_A["accent"]))
        height = min(16, self.height() - 12)
        painter.drawRoundedRect(QRectF(1, (self.height() - height) / 2, 3, height), 1.5, 1.5)
        painter.end()


class _PageLayout(QVBoxLayout):
    """The page's outer layout. app.py (Codex-owned) inserts its own widgets
    into it: buttons at index 0 (Gmail, Game Chat) go to the navigation rail's
    Integrations area, and shortcut checkboxes (the Game Chat Ctrl+Alt+Space
    toggle) go to the Global Hotkey card, instead of floating outside the
    cards. add_account_action()/add_hotkey_option() are the direct APIs
    (docs/claude/INTEGRATION_REQUESTS.md #6)."""

    def insertWidget(self, index, widget, stretch=0, alignment=Qt.AlignmentFlag(0)):  # noqa: N802 - Qt API
        page = self.parentWidget()
        if isinstance(page, SettingsPage):
            if isinstance(widget, QCheckBox) and _SHORTCUT_TEXT.search(widget.text()):
                page.add_hotkey_option(widget)
                return
            if index == 0 and isinstance(widget, QAbstractButton) and not isinstance(widget, QCheckBox):
                page.add_account_action(widget)
                return
        super().insertWidget(index, widget, stretch, alignment)


def _row(title: str, control: QWidget, hint: str = "") -> QWidget:
    """A setting row: title (and optional hint) on the left, control on the right."""
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 9, 0, 9)
    layout.setSpacing(20)
    text = QVBoxLayout()
    text.setSpacing(1)
    title_label = _role_label(title, "rowTitle")
    title_label.setBuddy(control)
    text.addWidget(title_label)
    if hint:
        text.addWidget(_role_label(hint, "rowHint", wrap=True))
    layout.addLayout(text, 3)
    control.setMinimumWidth(180)
    control.setMaximumWidth(300)
    control.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    layout.addWidget(control, 2, Qt.AlignmentFlag.AlignVCenter)
    return row


def _toggle_row(switch: QCheckBox, hint: str = "", status: QLabel | None = None) -> QWidget:
    row = QWidget()
    layout = QVBoxLayout(row)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(1)
    layout.addWidget(switch)
    if hint:
        label = _role_label(hint, "rowHint", wrap=True)
        label.setContentsMargins(0, 0, 64, 0)
        layout.addWidget(label)
    if status is not None:
        layout.addWidget(status)
    return row


class _Card:
    """One settings section: a QGroupBox (a card, via card_rules) whose rows are
    separated by hairlines."""

    def __init__(self, title: str) -> None:
        self.group = QGroupBox(title)
        self.layout = QVBoxLayout(self.group)
        self.layout.setContentsMargins(0, 2, 0, 0)
        self.layout.setSpacing(0)
        self._divide = False

    def add(self, widget: QWidget, *, divided: bool = True) -> None:
        if divided and self._divide:
            self.layout.addWidget(_divider())
        self.layout.addWidget(widget)
        self._divide = divided

    def row(self, title: str, control: QWidget, hint: str = "") -> None:
        self.add(_row(title, control, hint))

    def attach(self, widget: QWidget) -> None:
        """Add a widget that belongs to the previous row: no divider around it."""
        self.layout.addWidget(widget)

    def toggle(self, switch: QCheckBox, hint: str = "", status: QLabel | None = None) -> None:
        self.add(_toggle_row(switch, hint, status))

    def note(self, text: str) -> None:
        label = _role_label(text, "cardHint", wrap=True)
        label.setContentsMargins(0, 0, 0, 10)
        self.add(label, divided=False)

    def subheading(self, text: str) -> None:
        self.add(_role_label(text.upper(), "subheading"), divided=False)


class _AliasTable(QTableWidget):
    """Simple 2-column key/value editor for website_aliases/app_aliases."""

    def __init__(self, key_header: str, value_header: str, parent: QWidget | None = None) -> None:
        super().__init__(0, 2, parent)
        self.setHorizontalHeaderLabels([key_header, value_header])
        self.horizontalHeader().setStretchLastSection(True)
        self.horizontalHeader().setHighlightSections(False)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.horizontalHeader().resizeSection(0, 180)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(34)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setMinimumHeight(190)

    def load(self, mapping: dict[str, str]) -> None:
        self.setRowCount(0)
        for key, value in sorted(mapping.items()):
            self._append_row(key, value)

    def add_blank_row(self) -> None:
        self._append_row("", "")

    def edit_last_row(self) -> None:
        row = self.rowCount() - 1
        if row >= 0 and self.isVisible():
            self.setCurrentCell(row, 0)
            self.scrollToBottom()
            self.editItem(self.item(row, 0))

    def _append_row(self, key: str, value: str) -> None:
        row = self.rowCount()
        self.insertRow(row)
        self.setItem(row, 0, QTableWidgetItem(key))
        self.setItem(row, 1, QTableWidgetItem(value))

    def remove_selected_row(self) -> None:
        row = self.currentRow()
        if row >= 0:
            self.removeRow(row)

    def to_dict(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for row in range(self.rowCount()):
            key_item = self.item(row, 0)
            value_item = self.item(row, 1)
            key = key_item.text().strip().lower() if key_item else ""
            value = value_item.text().strip() if value_item else ""
            if key and value:
                result[key] = value
        return result


class _StringListEditor(QListWidget):
    """Single-column editable list, for gaming.close_processes/launch_apps."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(150)

    def load(self, items: list[str]) -> None:
        self.clear()
        for item in items:
            self._append_item(item)

    def add_blank_item(self) -> None:
        self._append_item("")

    def edit_last_item(self) -> None:
        if self.count() and self.isVisible():
            item = self.item(self.count() - 1)
            self.setCurrentItem(item)
            self.editItem(item)

    def _append_item(self, text: str) -> None:
        item = QListWidgetItem(text)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        self.addItem(item)

    def remove_selected_item(self) -> None:
        row = self.currentRow()
        if row >= 0:
            self.takeItem(row)

    def to_list(self) -> list[str]:
        values = []
        for row in range(self.count()):
            text = self.item(row).text().strip()
            if text:
                values.append(text)
        return values


class SettingsPage(QWidget):
    """Website/app aliases, safety confirmations, preferred browser, mode
    volumes, gaming apps, voice provider, and the OpenAI model -- everything
    that can meaningfully be configured from the GUI today.

    Layout: a navigation rail (one entry per section, plus an Accounts area
    for integration buttons such as Gmail) beside one scrolling column of
    section cards; Save stays pinned below both. The rail follows the scroll
    position, and clicking an entry scrolls its card to the top.

    Mutates the shared JarvisSettings instance in place on Save (clear()+
    update() on dicts, not reassignment) rather than replacing it, so
    router.py and GuiSafetyPolicy -- which both hold a reference to the
    same object -- pick up alias/safety changes live, with no app restart.
    STT/TTS provider changes need a restart (SpeechToText/TextToSpeech read
    settings once at construction) -- labelled in the UI, not silently
    incomplete.

    Mode-preference volumes and gaming app lists are read by
    windows_actions.py's apply_mode()/game_mode() on each command.
    """

    saved = Signal()
    hotkey_toggled = Signal(bool)
    overlay_hotkey_toggled = Signal(bool)
    # {"personality": {...}, "role_packs": [...], "address_name": str} after Save.
    personalization_changed = Signal(dict)
    # (profile id, {"personality": {...}, "role_packs": [...]}) after Save while
    # set_active_profile() has a profile: ProfileStore.update() applies it.
    profile_changes_requested = Signal(str, dict)

    def __init__(
        self,
        settings: JarvisSettings,
        ai=None,
        settings_path: Path = SETTINGS_PATH,
        hotkey_manager=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._active_profile: dict | None = None  # set_active_profile()
        self._ai = ai
        self._settings_path = settings_path
        # Optional: the real HotkeyManager instance app.py also wires up to
        # installNativeEventFilter/overlay/push-to-talk -- must be the SAME
        # instance, not a second one, or this checkbox would silently
        # control a hotkey manager that isn't the one actually intercepting
        # Ctrl+Space. None under headless/offscreen construction (tests,
        # or any future caller that doesn't have a real one to hand over).
        self._hotkey_manager = hotkey_manager
        self.setObjectName("settingsPage")
        self.setStyleSheet(SETTINGS_STYLE)
        self._build_ui()
        self._load_from_settings()

    def _build_ui(self) -> None:
        # The section cards add up to content far taller than most laptop
        # screens -- a plain QVBoxLayout directly on `self` would force the
        # containing window to either grow past the screen or clip the bottom
        # sections with no way to reach them. Wrapped in a QScrollArea
        # instead, with Save pinned outside it so it's always reachable
        # without scrolling to the very bottom. The outer layout stays a
        # QVBoxLayout: app.py inserts its Gmail button into it.
        outer_layout = _PageLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(12)

        self._sections: list[tuple[QGroupBox, _NavButton]] = []
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_lock: int | None = None

        self._content = QWidget()
        self._content.setMaximumWidth(900)
        layout = QVBoxLayout(self._content)
        layout.setContentsMargins(0, 0, 14, 24)
        layout.setSpacing(18)
        nav_scroll = self._build_nav()

        sections = (
            (self._build_voice_group, "Voice", "mic", _SP.SP_MediaVolume),
            (self._build_personality_group, "Personality", "person", _SP.SP_DialogHelpButton),
            (self._build_packs_group, "Role packs", "puzzle", _SP.SP_FileDialogDetailedView),
            (self._build_ai_group, "OpenAI", "sparkle", _SP.SP_ComputerIcon),
            (self._build_safety_group, "Safety", "shield", _SP.SP_MessageBoxWarning),
            (self._build_browser_group, "Browser", "globe", _SP.SP_DriveNetIcon),
            (lambda: self._build_aliases_group("Website aliases", "Alias", "URL", "_website_table"),
             "Website aliases", "link", _SP.SP_FileLinkIcon),
            (lambda: self._build_aliases_group("App aliases", "Alias", "Command", "_app_table"),
             "App aliases", "apps", _SP.SP_FileDialogListView),
            (self._build_gaming_group, "Gaming mode", "game", _SP.SP_ComputerIcon),
            (self._build_mode_group, "Mode volumes", "volume", _SP.SP_MediaVolume),
            (self._build_temperature_group, "Temperature", "thermometer", _SP.SP_MessageBoxInformation),
            (self._build_startup_group, "Startup", "power", _SP.SP_BrowserReload),
            (self._build_hotkey_group, "Global hotkey", "keyboard", _SP.SP_ComputerIcon),
        )
        for build, nav_title, glyph, fallback in sections:
            group = build()
            layout.addWidget(group)
            self._add_section(group, nav_title, glyph, fallback)
        layout.addStretch(1)
        self._sections[0][1].setChecked(True)

        self._scroll = QScrollArea()
        self._scroll.setWidget(self._content)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        bar = self._scroll.verticalScrollBar()
        bar.valueChanged.connect(self._on_scrolled)
        self._scroll_animation = QPropertyAnimation(bar, b"value", self)
        self._scroll_animation.setDuration(240)
        self._scroll_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)
        body.addWidget(nav_scroll)
        body.addWidget(self._scroll, 1)
        outer_layout.addLayout(body, stretch=1)

        footer = QFrame()
        footer.setObjectName("settingsFooter")
        save_row = QHBoxLayout(footer)
        save_row.setContentsMargins(4, 12, 0, 0)
        self._status_label = QLabel("")
        self._status_label.setProperty("role", "saveStatus")
        save_row.addWidget(self._status_label, stretch=1)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(4000)
        self._status_timer.timeout.connect(lambda: self._status_label.setText(""))
        save_button = QPushButton("Save")
        save_button.setProperty("variant", "primary")
        save_button.setMinimumWidth(112)
        save_button.setToolTip("Save (Ctrl+S)")
        save_button.clicked.connect(self._on_save)
        save_row.addWidget(save_button)
        self._save_button = save_button
        outer_layout.addWidget(footer)

        self._save_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        self._save_shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._save_shortcut.activated.connect(self._on_save)

    # ------------------------------------------------------------ navigation

    def _build_nav(self) -> QScrollArea:
        self._nav = QWidget()
        self._nav.setObjectName("settingsNav")
        layout = QVBoxLayout(self._nav)
        layout.setContentsMargins(0, 2, 8, 4)
        layout.setSpacing(0)
        self._nav_buttons = QVBoxLayout()
        self._nav_buttons.setSpacing(2)
        layout.addLayout(self._nav_buttons)
        layout.addStretch(1)
        self._accounts_label = _role_label("INTEGRATIONS", "overline")
        self._accounts_label.hide()
        layout.addWidget(self._accounts_label)
        self._accounts_layout = QVBoxLayout()
        self._accounts_layout.setSpacing(2)
        layout.addLayout(self._accounts_layout)

        # Scrollable so a short (1366x768 at 150%) screen never forces the
        # dialog taller than the display just to fit the rail.
        scroll = QScrollArea()
        scroll.setObjectName("settingsNavScroll")
        scroll.setWidget(self._nav)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(212)
        return scroll

    def _add_section(self, group: QGroupBox, title: str, glyph: str, fallback) -> None:
        icon = glyph_icon(glyph, fallback, self.style(), checked_color=_A["accent_light"], size=18)
        button = _NavButton(title, icon)
        index = len(self._sections)
        button.clicked.connect(lambda _checked=False, i=index: self._scroll_to_section(i))
        self._nav_group.addButton(button, index)
        self._nav_buttons.addWidget(button)
        self._sections.append((group, button))

    def add_account_action(self, widget: QWidget) -> None:
        """Show an integration button (Gmail, Game Chat) in the rail's
        Integrations area, styled like the navigation entries."""
        if isinstance(widget, QAbstractButton):
            widget.setIconSize(QSize(18, 18))
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
        self._accounts_layout.addWidget(widget)
        self._accounts_label.show()

    def add_hotkey_option(self, checkbox: QCheckBox) -> None:
        """Place another module's shortcut toggle (app.py's Game Chat
        Ctrl+Alt+Space checkbox) in the Global Hotkey card."""
        checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hotkey_card.toggle(checkbox)

    def _scroll_to_section(self, index: int) -> None:
        group = self._sections[index][0]
        bar = self._scroll.verticalScrollBar()
        target = max(bar.minimum(), min(bar.maximum(), group.y() - 4))
        self._sections[index][1].setChecked(True)
        # The rail keeps the clicked entry even when the last sections can't
        # reach the top; the next user scroll hands control back to the spy.
        self._nav_lock = target
        self._scroll_animation.stop()
        if not self.isVisible() or abs(bar.value() - target) < 2:
            bar.setValue(target)
            return
        self._scroll_animation.setStartValue(bar.value())
        self._scroll_animation.setEndValue(target)
        self._scroll_animation.start()

    def _on_scrolled(self, value: int) -> None:
        if self._scroll_animation.state() == QAbstractAnimation.State.Running:
            return
        if self._nav_lock is not None:
            if value == self._nav_lock:
                return
            self._nav_lock = None
        bar = self._scroll.verticalScrollBar()
        if bar.maximum() > 0 and value >= bar.maximum() - 2:
            index = len(self._sections) - 1
        else:
            index = 0
            for position, (group, _button) in enumerate(self._sections):
                if group.y() <= value + 48:
                    index = position
        self._sections[index][1].setChecked(True)

    # -------------------------------------------------------------- sections

    def _build_browser_group(self) -> QGroupBox:
        card = _Card("Preferred browser")
        self._browser_combo = QComboBox()
        self._browser_combo.setEditable(True)
        self._browser_combo.addItems(_BROWSER_CHOICES)
        self._browser_combo.lineEdit().setPlaceholderText("System default")
        card.row("Browser", self._browser_combo, "Used when Jarvis opens websites and searches.")
        self._browser_path_input = QLineEdit()
        self._browser_path_input.setPlaceholderText("Optional: full path to the browser .exe")
        card.row("Path override", self._browser_path_input)
        return card.group

    def _build_aliases_group(self, title: str, key_header: str, value_header: str, attr_name: str) -> QGroupBox:
        card = _Card(title)
        target = "address" if value_header == "URL" else "command"
        card.note(f"Say “open <alias>” and Jarvis opens the matching {target}.")
        table = _AliasTable(key_header, value_header)
        setattr(self, attr_name, table)
        card.add(table, divided=False)

        def add_row() -> None:
            table.add_blank_row()
            table.edit_last_row()

        card.layout.addLayout(self._make_add_remove_row(add_row, table.remove_selected_row))
        return card.group

    def _build_mode_group(self) -> QGroupBox:
        card = _Card("Mode volumes")
        self._mode_spinboxes: dict[str, QSpinBox] = {}
        for key, label, default in _MODE_VOLUME_KEYS:
            spinbox = QSpinBox()
            spinbox.setRange(0, 100)
            spinbox.setSuffix("%")
            spinbox.setValue(default)
            self._mode_spinboxes[key] = spinbox
            card.row(label, spinbox)
        return card.group

    def _build_temperature_group(self) -> QGroupBox:
        # BackgroundMonitor._temperature_threshold_c() reads this value fresh
        # on every GPU poll, so a saved change takes effect within seconds.
        card = _Card("Temperature warning")
        self._temperature_spinbox = QSpinBox()
        self._temperature_spinbox.setRange(40, 110)
        self._temperature_spinbox.setSuffix(" °C")
        self._temperature_spinbox.setValue(_TEMPERATURE_DEFAULT)
        self._temperature_spinbox.setToolTip(
            "The GUI dashboard/tray warns once when CPU or GPU temperature reaches this value, "
            "and again after it drops back down and rises to it a second time."
        )
        card.row("Warn at", self._temperature_spinbox,
                 "Warns once when the CPU or GPU reaches this, again after it cools down and climbs back.")
        return card.group

    def _build_gaming_group(self) -> QGroupBox:
        card = _Card("Gaming mode apps")
        columns = QWidget()
        group_layout = QHBoxLayout(columns)
        group_layout.setContentsMargins(0, 0, 0, 0)
        group_layout.setSpacing(18)

        close_column = QVBoxLayout()
        close_column.setSpacing(6)
        close_column.addWidget(_role_label("Close on Gaming mode", "rowTitle"))
        self._close_processes_list = _StringListEditor()
        close_column.addWidget(self._close_processes_list)
        close_column.addLayout(self._make_add_remove_row(
            lambda: (self._close_processes_list.add_blank_item(), self._close_processes_list.edit_last_item()),
            self._close_processes_list.remove_selected_item,
        ))
        group_layout.addLayout(close_column)

        launch_column = QVBoxLayout()
        launch_column.setSpacing(6)
        launch_column.addWidget(_role_label("Launch on Gaming mode", "rowTitle"))
        self._launch_apps_list = _StringListEditor()
        launch_column.addWidget(self._launch_apps_list)
        launch_column.addLayout(self._make_add_remove_row(
            lambda: (self._launch_apps_list.add_blank_item(), self._launch_apps_list.edit_last_item()),
            self._launch_apps_list.remove_selected_item,
        ))
        group_layout.addLayout(launch_column)

        card.add(columns, divided=False)
        return card.group

    def _build_safety_group(self) -> QGroupBox:
        card = _Card("Safety confirmations")
        self._full_access_checkbox = _ToggleSwitch("Full access: trusted local files and apps")
        self._full_access_checkbox.setChecked(self._settings.safety.get("full_access_local") is True)
        self._full_access_checkbox.setToolTip("Skip repeated prompts for local file changes, recycling and ending user apps. System/security actions and screen uploads remain protected.")
        card.toggle(self._full_access_checkbox,
                    "Skips repeated prompts for local file changes, recycling and ending apps. "
                    "System actions and screen uploads stay protected.")
        card.subheading("Ask before")
        self._safety_checkboxes: dict[str, QCheckBox] = {}
        for key, label in _SAFETY_LABELS.items():
            checkbox = _ToggleSwitch(label)
            self._safety_checkboxes[key] = checkbox
            card.toggle(checkbox)
        return card.group

    def _build_voice_group(self) -> QGroupBox:
        card = _Card("Voice")

        self._language_combo = QComboBox()
        for label, code in _CONVERSATION_LANGUAGES:
            self._language_combo.addItem(label, code)
        self._language_combo.setToolTip(
            "Language Jarvis listens for and replies in. Auto-detect follows whichever language "
            "you're currently speaking; applies to the next live call and the next voice command."
        )
        card.row("Conversation language", self._language_combo,
                 "Jarvis listens and replies in this language. Auto-detect follows whichever one you speak.")

        card.subheading("Live call")
        self._realtime_model_input = QLineEdit()
        card.row("Live model", self._realtime_model_input)
        self._realtime_voice_combo = QComboBox()
        self._realtime_voice_combo.setEditable(True)
        self._realtime_voice_combo.addItems(["cedar", "marin"])
        self._realtime_voice_combo.setToolTip("AI-generated voice. Changes apply to the next live call.")
        card.row("Live voice", self._realtime_voice_combo)
        self._live_audio_mode = QComboBox()
        self._live_audio_mode.addItem("Speakers", True)
        self._live_audio_mode.addItem("Headphones", False)
        self._live_audio_mode.addItem("Auto: detect headphones", "auto")
        self._live_audio_mode.setToolTip(
            "Speakers pause microphone transmission during replies to prevent self-listening. "
            "Headphones keep the microphone open. Auto picks per call from the output device.")
        card.row("Live audio mode", self._live_audio_mode,
                 "Auto is best: headphones stay full-duplex, speakers pause the mic while Jarvis talks.")
        self._barge_in_switch = _ToggleSwitch("Interrupt by talking over Jarvis")
        card.toggle(self._barge_in_switch,
                    "With speakers Jarvis listens for your voice above its own and stops. Speak clearly; "
                    "saying “Jarvis” also works.")

        card.subheading("Speech engines")
        self._stt_provider_combo = QComboBox()
        self._stt_provider_combo.addItems(_STT_PROVIDERS)
        card.row("Speech-to-text provider", self._stt_provider_combo)
        self._stt_model_input = QLineEdit()
        self._stt_model_input.setPlaceholderText("e.g. gpt-transcribe")
        card.row("Speech-to-text model", self._stt_model_input)
        self._tts_provider_combo = QComboBox()
        self._tts_provider_combo.addItems(_TTS_PROVIDERS)
        card.row("Text-to-speech provider", self._tts_provider_combo,
                 "Classic voice and spoken results; live calls use the live voice. openai speaks Bulgarian and "
                 "English, windows only the voices installed in Windows.")
        # Shown only when the choice would leave Bulgarian replies silent.
        self._windows_voices = self._installed_windows_voices()
        self._tts_language_warning = _StatusLabel("")
        self._tts_language_warning.setContentsMargins(0, 0, 0, 8)
        card.attach(self._tts_language_warning)
        self._tts_provider_combo.currentTextChanged.connect(self._refresh_tts_language_warning)
        self._language_combo.currentIndexChanged.connect(self._refresh_tts_language_warning)
        self._tts_model_input = QLineEdit()
        self._tts_model_input.setPlaceholderText("e.g. gpt-4o-mini-tts")
        card.row("Text-to-speech model", self._tts_model_input)
        self._tts_voice_combo = QComboBox()
        self._tts_voice_combo.setEditable(True)
        self._tts_voice_combo.addItems(self._openai_voice_choices())
        card.row("Text-to-speech voice", self._tts_voice_combo)

        card.subheading("Microphone and output")
        self._audio_output_combo = QComboBox()
        self._audio_output_combo.setEditable(True)
        # Long WASAPI device names would otherwise set a ~650px minimum width.
        self._audio_output_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self._audio_output_combo.setMinimumContentsLength(20)
        self._audio_output_combo.addItem("System default", "")
        self._audio_output_combo.addItems(self._audio_output_choices())
        self._audio_output_combo.setToolTip("Choose the speaker/headset Jarvis should use for OpenAI TTS and Realtime voice.")
        self._fit_popup_to_items(self._audio_output_combo)
        card.row("Audio output device", self._audio_output_combo)

        self._energy_threshold_spinbox = QSpinBox()
        self._energy_threshold_spinbox.setRange(0, 4000)
        self._energy_threshold_spinbox.setSpecialValueText("Auto")
        self._energy_threshold_spinbox.setToolTip(
            "Higher = needs louder speech to register (useful in noisy rooms). 0 lets Jarvis auto-calibrate."
        )
        card.row("Microphone noise threshold", self._energy_threshold_spinbox,
                 "Higher needs louder speech. Auto calibrates to the room.")

        self._pause_threshold_spinbox = QSpinBox()
        self._pause_threshold_spinbox.setRange(0, 3000)
        self._pause_threshold_spinbox.setSingleStep(100)
        self._pause_threshold_spinbox.setSuffix(" ms")
        self._pause_threshold_spinbox.setSpecialValueText("Default (800 ms)")
        self._pause_threshold_spinbox.setToolTip("How much silence ends a phrase. Lower reacts faster but may cut off slow speech.")
        card.row("Silence cutoff", self._pause_threshold_spinbox, "How much silence ends a phrase.")

        return card.group

    @staticmethod
    def _installed_windows_voices() -> set[str]:
        try:
            from ..audio.text_to_speech import windows_voice_languages

            return windows_voice_languages()
        except Exception:  # pragma: no cover - registry unavailable: better no warning than a wrong one
            return {"bg", "en"}

    def _refresh_tts_language_warning(self, *_args) -> None:
        provider = self._tts_provider_combo.currentText().strip().lower()
        silent = (provider == "windows" and self._language_combo.currentData() in {"bg", "auto"}
                  and "bg" not in self._windows_voices)
        self._tts_language_warning.setText(
            "No Bulgarian Windows voice is installed here, so Bulgarian replies would be silent with the windows "
            "provider. Choose openai to hear Bulgarian." if silent else "")

    @staticmethod
    def _fit_popup_to_items(combo: QComboBox) -> None:
        """Let the drop-down list be wider than the (width-capped) field so long
        device names stay readable, and show each full name as a tooltip."""
        metrics = combo.fontMetrics()
        widest = 0
        for index in range(combo.count()):
            text = combo.itemText(index)
            combo.setItemData(index, text, Qt.ItemDataRole.ToolTipRole)
            widest = max(widest, metrics.horizontalAdvance(text))
        combo.view().setMinimumWidth(min(560, widest + 48))
        combo.view().setTextElideMode(Qt.TextElideMode.ElideMiddle)

    @staticmethod
    def _openai_voice_choices() -> list[str]:
        try:
            from ..audio.text_to_speech import OPENAI_TTS_VOICES

            return list(OPENAI_TTS_VOICES)
        except ImportError:  # pragma: no cover - text_to_speech.py has no hard import-time deps
            return []

    @staticmethod
    def _audio_output_choices() -> list[str]:
        try:
            from ..audio.output_device import list_output_devices

            return [device.label for device in list_output_devices()]
        except ImportError:  # pragma: no cover - optional sounddevice dependency
            return []

    def _build_personality_group(self) -> QGroupBox:
        card = _Card("Personality")
        card.note("How Jarvis talks to you: tone and detail only. Permissions never change with the personality.")
        self._profile_notes = (_role_label("", "profileNote"), _role_label("", "profileNote"))
        self._profile_notes[0].hide()
        card.attach(self._profile_notes[0])
        grid_host = QWidget()
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(0, 0, 0, 6)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self._preset_group = QButtonGroup(self)
        self._preset_group.setExclusive(True)
        self._preset_buttons: dict[str, _ChoiceCard] = {}
        for index, preset in enumerate(PRESETS.values()):
            button = _ChoiceCard(preset.name, preset.tagline)
            self._preset_group.addButton(button, index)
            self._preset_buttons[preset.id] = button
            grid.addWidget(button, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        card.add(grid_host, divided=False)

        self._humor_slider, humor_row = self._level_slider(HUMOR_LEVELS)
        card.row("Humor", humor_row, "From strictly serious to playful.")
        self._detail_slider, detail_row = self._level_slider(DETAIL_LEVELS)
        card.row("Detail", detail_row, "How long and thorough the answers are.")
        self._address_input = QLineEdit()
        self._address_input.setPlaceholderText("e.g. Берк, or sir")
        self._address_input.setMaxLength(40)
        card.row("Call me", self._address_input, "The name or title Jarvis uses for you.")

        preview = QFrame()
        preview.setProperty("role", "previewBox")
        preview_layout = QVBoxLayout(preview)
        preview_layout.setContentsMargins(14, 10, 14, 10)
        preview_layout.setSpacing(3)
        self._preview_quote = _role_label("", "previewQuote", wrap=True)
        self._preview_caption = _role_label("", "rowHint", wrap=True)
        preview_layout.addWidget(self._preview_quote)
        preview_layout.addWidget(self._preview_caption)
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 10, 0, 6)
        holder_layout.addWidget(preview)
        card.add(holder, divided=False)

        self._preset_group.idToggled.connect(lambda _id, checked: checked and self._refresh_personality_preview())
        self._humor_slider.valueChanged.connect(self._refresh_personality_preview)
        self._detail_slider.valueChanged.connect(self._refresh_personality_preview)
        self._language_combo.currentIndexChanged.connect(self._refresh_personality_preview)
        return card.group

    @staticmethod
    def _level_slider(levels: tuple[str, ...]) -> tuple[QSlider, QWidget]:
        host = QWidget()
        layout = QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, len(levels) - 1)
        slider.setPageStep(1)
        slider.setCursor(Qt.CursorShape.PointingHandCursor)
        value = _role_label(levels[slider.value()], "sliderValue")
        value.setFixedWidth(64)
        slider.valueChanged.connect(lambda index: value.setText(levels[index]))
        layout.addWidget(slider, 1)
        layout.addWidget(value)
        return slider, host

    def _selected_personality(self) -> dict:
        preset = next((preset_id for preset_id, button in self._preset_buttons.items() if button.isChecked()), "jarvis")
        return {"preset": preset, "humor": self._humor_slider.value(), "detail": self._detail_slider.value()}

    def _refresh_personality_preview(self, *_args) -> None:
        personality = self._selected_personality()
        language = self._language_combo.currentData() or "en"
        self._preview_quote.setText(f"“{sample_line(personality, language)}”")
        self._preview_caption.setText(
            f"Preview · {PRESETS[personality['preset']].name} · humor {HUMOR_LEVELS[personality['humor']].lower()}"
            f" · detail {DETAIL_LEVELS[personality['detail']].lower()}")

    def _build_packs_group(self) -> QGroupBox:
        card = _Card("Role packs")
        card.note("Know-how and quick actions for what you do. Packs never grant extra permissions.")
        self._profile_notes[1].hide()
        card.attach(self._profile_notes[1])
        self._pack_switches: dict[str, _ToggleSwitch] = {}
        for pack in PACKS.values():
            switch = _ToggleSwitch(pack.name)
            switch.setToolTip(pack.tagline)
            self._pack_switches[pack.id] = switch
            card.toggle(switch, pack.tagline)
        return card.group

    def current_personalization(self) -> dict:
        """The person's saved personality, role packs and name (for MainWindow):
        the active profile's once set_active_profile() has one, otherwise
        settings.personalization (docs/claude/PERSONALIZATION_HANDOFF.md)."""
        profile = self._active_profile
        source = profile if profile is not None else self._settings.personalization
        name = profile.get("display_name") if profile is not None else source.get("address_name")
        return {"personality": normalize_personality(source.get("personality")),
                "role_packs": normalize_packs(source.get("role_packs")),
                "address_name": str(name or "")}

    def set_active_profile(self, profile: dict | None) -> None:
        """With profiles, Personality and Role packs edit the active profile
        (saved through profile_changes_requested) instead of the settings."""
        self._active_profile = dict(profile) if isinstance(profile, dict) else None
        language = (self._active_profile or {}).get("language")
        if language in {"en", "bg", "auto"}:  # the conversation language follows the profile
            self._language_combo.setCurrentIndex(max(0, self._language_combo.findData(language)))
        self._load_personalization()

    def _load_personalization(self) -> None:
        personalization = self.current_personalization()
        personality = personalization["personality"]
        self._preset_buttons[personality["preset"]].setChecked(True)
        self._humor_slider.setValue(personality["humor"])
        self._detail_slider.setValue(personality["detail"])
        # "Call me" is the profile's nickname (address_as) with profiles, and
        # the address_name that "наричай ме ..." saves without them.
        profile = self._active_profile
        self._address_input.setText(personality["address_as"] if profile is not None
                                    else personalization["address_name"])
        for pack_id, switch in self._pack_switches.items():
            switch.setChecked(pack_id in personalization["role_packs"])
        name = str(profile.get("display_name") or "this profile") if profile is not None else ""
        self._profile_notes[0].setText(f"Editing {name}'s profile." if profile is not None else "")
        self._profile_notes[1].setText(f"For {name}'s profile." if profile is not None else "")
        for note in self._profile_notes:
            note.setVisible(profile is not None)
        self._refresh_personality_preview()

    def _build_ai_group(self) -> QGroupBox:
        card = _Card("OpenAI")
        self._model_input = QLineEdit()
        self._model_input.setPlaceholderText("e.g. gpt-5.6-sol")
        card.row("Model", self._model_input, "Used for chat, planning and tools.")
        self._use_memory_context_checkbox = _ToggleSwitch("Use saved context in chat and voice")
        self._use_memory_context_checkbox.setToolTip(
            "Include saved context in OpenAI conversations. Also enables local Realtime transcript history. "
            "Turning this off prevents the current voice session from saving its transcript."
        )
        card.toggle(self._use_memory_context_checkbox,
                    "Also keeps a local transcript history of live calls. Off stops the current call from being saved.")
        return card.group

    def _build_startup_group(self) -> QGroupBox:
        card = _Card("Startup")
        self._autostart_checkbox = _ToggleSwitch("Start Jarvis when Windows starts")
        # Applies immediately, unlike everything above it: this is a real
        # filesystem/system-affecting action (creates or removes a Startup-
        # folder shortcut), not a value to batch behind Save -- matches how
        # every native Windows app's own autostart checkbox behaves, and
        # means the checkbox can never show a state that Save hasn't
        # actually applied yet.
        self._autostart_checkbox.toggled.connect(self._on_autostart_toggled)
        self._autostart_status_label = _StatusLabel("")
        card.toggle(self._autostart_checkbox, "Applies immediately.", self._autostart_status_label)
        return card.group

    def _on_autostart_toggled(self, checked: bool) -> None:
        ok = autostart.enable() if checked else autostart.disable()
        if ok:
            self._autostart_status_label.setText("")
        else:
            action = "enable" if checked else "disable"
            self._autostart_status_label.setText(f"Could not {action} autostart.")
            self._autostart_checkbox.blockSignals(True)
            self._autostart_checkbox.setChecked(not checked)
            self._autostart_checkbox.blockSignals(False)

    def _build_hotkey_group(self) -> QGroupBox:
        card = _Card("Global Hotkey")
        self._hotkey_card = card
        self._hotkey_checkbox = _ToggleSwitch("Enable global Ctrl+Space hotkey")
        self._hotkey_checkbox.setToolTip(
            "Toggles the overlay and triggers push-to-talk from anywhere, even when Jarvis is not focused."
        )
        # Applies immediately, same reasoning as the Startup checkbox above --
        # this mutates a real, currently-active OS-level hotkey registration,
        # not a value to batch behind Save.
        self._hotkey_checkbox.toggled.connect(self._on_hotkey_toggled)
        self._hotkey_status_label = _StatusLabel("")
        card.toggle(self._hotkey_checkbox, "Push-to-talk and the overlay from anywhere. Applies immediately.",
                    self._hotkey_status_label)
        self._overlay_hotkey_checkbox = _ToggleSwitch("Command overlay")
        self._overlay_hotkey_checkbox.setToolTip("Alt+Space. Does not start the microphone. May conflict with another launcher.")
        self._overlay_hotkey_checkbox.toggled.connect(self._on_overlay_hotkey_toggled)
        self._overlay_hotkey_status = _StatusLabel("")
        card.toggle(self._overlay_hotkey_checkbox,
                    "Alt+Space opens the command bar without the microphone. May conflict with another launcher.",
                    self._overlay_hotkey_status)
        return card.group

    def _on_overlay_hotkey_toggled(self, checked: bool) -> None:
        self._settings.mode_preferences["overlay_hotkey_enabled"] = checked
        save_settings(self._settings, path=self._settings_path)
        self.overlay_hotkey_toggled.emit(checked)

    def _on_hotkey_toggled(self, checked: bool) -> None:
        # hotkey_enabled has no filesystem-derived fact to re-check the way
        # autostart.is_enabled() does, so -- unlike autostart -- the
        # preference must be saved immediately, or it would silently revert
        # to the default on the next launch even though this session's
        # toggle succeeded.
        self._settings.mode_preferences["hotkey_enabled"] = checked
        save_settings(self._settings, path=self._settings_path)

        if self._hotkey_manager is not None:
            if checked:
                ok = self._hotkey_manager.register()
                if ok:
                    self._hotkey_status_label.setText("")
                else:
                    self._hotkey_status_label.setText(
                        "Could not enable: Ctrl+Space may already be used by another application."
                    )
                    self._hotkey_checkbox.blockSignals(True)
                    self._hotkey_checkbox.setChecked(False)
                    self._hotkey_checkbox.blockSignals(False)
                    self._settings.mode_preferences["hotkey_enabled"] = False
                    save_settings(self._settings, path=self._settings_path)
            else:
                self._hotkey_manager.unregister()
                self._hotkey_status_label.setText("")

        # Emitted after this method has already settled the manager's real
        # register()/unregister() state above, so app.py's handler -- which
        # only keeps installNativeEventFilter in sync -- can read
        # hotkey_manager.registered and trust it reflects what just happened.
        self.hotkey_toggled.emit(self._hotkey_checkbox.isChecked())

    @staticmethod
    def _make_add_remove_row(add_callback, remove_callback) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 8, 0, 0)
        row.setSpacing(4)
        add_button = QPushButton("Add")
        add_button.setIcon(glyph_icon("add", _SP.SP_FileIcon, add_button.style(), size=14))
        add_button.clicked.connect(add_callback)
        remove_button = QPushButton("Remove")
        remove_button.setIcon(glyph_icon("delete", _SP.SP_TrashIcon, remove_button.style(), size=14))
        remove_button.setToolTip("Remove the selected entry")
        remove_button.clicked.connect(remove_callback)
        for button in (add_button, remove_button):
            button.setProperty("role", "ghost")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _load_from_settings(self) -> None:
        self._website_table.load(self._settings.website_aliases)
        self._app_table.load(self._settings.app_aliases)
        for key, checkbox in self._safety_checkboxes.items():
            checkbox.setChecked(self._settings.safety_enabled(key))

        self._browser_combo.setCurrentText(self._settings.preferred_browser)
        self._browser_path_input.setText(self._settings.browser_paths.get(self._settings.preferred_browser, ""))

        for key, spinbox in self._mode_spinboxes.items():
            default = next(default for k, _label, default in _MODE_VOLUME_KEYS if k == key)
            spinbox.setValue(int(self._settings.mode_preferences.get(key, default)))
        self._temperature_spinbox.setValue(int(self._settings.mode_preferences.get(_TEMPERATURE_KEY, _TEMPERATURE_DEFAULT)))

        self._close_processes_list.load(list(self._settings.gaming.get("close_processes", [])))
        self._launch_apps_list.load(list(self._settings.gaming.get("launch_apps", [])))

        openai_settings = self._settings.openai
        from ..realtime import RealtimeVoiceConfig

        self._language_combo.setCurrentIndex(max(0, self._language_combo.findData(self._settings.conversation_language)))

        realtime_config = RealtimeVoiceConfig.from_settings(self._settings)
        self._realtime_model_input.setText(realtime_config.model)
        self._realtime_voice_combo.setCurrentText(realtime_config.voice)
        guard = openai_settings.get("realtime_speaker_guard", True)
        guard = guard if guard == "auto" else bool(guard)
        self._live_audio_mode.setCurrentIndex(max(0, self._live_audio_mode.findData(guard)))
        self._barge_in_switch.setChecked(bool(openai_settings.get("realtime_barge_in", True)))
        self._model_input.setText(str(openai_settings.get("model", "")))
        # Default True: matches router.py's own `openai.get("use_memory_context", True)`.
        self._use_memory_context_checkbox.setChecked(bool(openai_settings.get("use_memory_context", True)))
        self._stt_provider_combo.setCurrentText(str(openai_settings.get("speech_to_text_provider", "google")))
        self._stt_model_input.setText(str(openai_settings.get("speech_to_text_model", "")))
        self._tts_provider_combo.setCurrentText(str(openai_settings.get("tts_provider", "windows")))
        self._tts_model_input.setText(str(openai_settings.get("text_to_speech_model", "")))
        self._tts_voice_combo.setCurrentText(str(openai_settings.get("text_to_speech_voice", "")))
        self._audio_output_combo.setCurrentText(str(openai_settings.get("audio_output_device", "") or "System default"))
        self._energy_threshold_spinbox.setValue(int(openai_settings.get("energy_threshold") or 0))
        self._pause_threshold_spinbox.setValue(int(openai_settings.get("pause_threshold_ms") or 0))
        self._refresh_tts_language_warning()

        self._load_personalization()

        # blockSignals: this is a display-only sync from the real filesystem
        # state (see autostart.is_enabled()'s docstring) -- without this
        # guard, merely opening the Settings page would fire
        # _on_autostart_toggled and silently create/delete the real Startup
        # shortcut just to match whatever the checkbox's default state is.
        self._autostart_checkbox.blockSignals(True)
        self._autostart_checkbox.setChecked(autostart.is_enabled())
        self._autostart_checkbox.blockSignals(False)

        # blockSignals: same reasoning as the startup checkbox above --
        # merely opening Settings must never itself call register()/
        # unregister() or re-save the preference just to sync the checkbox
        # to whatever it already is.
        self._hotkey_checkbox.blockSignals(True)
        self._hotkey_checkbox.setChecked(bool(self._settings.mode_preferences.get("hotkey_enabled", True)))
        self._hotkey_checkbox.blockSignals(False)
        self._overlay_hotkey_checkbox.blockSignals(True)
        self._overlay_hotkey_checkbox.setChecked(bool(self._settings.mode_preferences.get("overlay_hotkey_enabled", True)))
        self._overlay_hotkey_checkbox.blockSignals(False)

    def _on_save(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        enabled = self._full_access_checkbox.isChecked()
        if enabled and self._settings.safety.get("full_access_local") is not True:
            answer = QMessageBox.warning(self, "Enable trusted local access?",
                "Jarvis will perform requested local file changes, send files/folders to the Recycle Bin "
                "and end user apps without further approval. Unsaved app work can be lost. "
                "System/security processes, administrative actions and screen/document uploads remain protected.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            enabled = answer == QMessageBox.StandardButton.Yes
            self._full_access_checkbox.setChecked(enabled)
        self._settings.safety["full_access_local"] = enabled
        self._settings.website_aliases.clear()
        self._settings.website_aliases.update(self._website_table.to_dict())
        self._settings.app_aliases.clear()
        self._settings.app_aliases.update(self._app_table.to_dict())
        self._settings.safety.update(
            {key: checkbox.isChecked() for key, checkbox in self._safety_checkboxes.items()}
        )

        preferred_browser = self._browser_combo.currentText().strip().lower()
        self._settings.preferred_browser = preferred_browser
        browser_path = self._browser_path_input.text().strip()
        if preferred_browser and browser_path:
            self._settings.browser_paths[preferred_browser] = browser_path

        for key, spinbox in self._mode_spinboxes.items():
            self._settings.mode_preferences[key] = spinbox.value()
        self._settings.mode_preferences[_TEMPERATURE_KEY] = self._temperature_spinbox.value()

        self._settings.gaming["close_processes"] = self._close_processes_list.to_list()
        self._settings.gaming["launch_apps"] = self._launch_apps_list.to_list()

        model = self._model_input.text().strip()
        audio_output_text = self._audio_output_combo.currentText().strip()
        self._settings.openai.update(
            {
                "model": model,
                "conversation_language": self._language_combo.currentData(),
                "realtime_model": self._realtime_model_input.text().strip(),
                "realtime_voice": self._realtime_voice_combo.currentText().strip(),
                "realtime_speaker_guard": self._live_audio_mode.currentData(),
                "realtime_barge_in": self._barge_in_switch.isChecked(),
                "speech_to_text_provider": self._stt_provider_combo.currentText().strip(),
                "speech_to_text_model": self._stt_model_input.text().strip(),
                "tts_provider": self._tts_provider_combo.currentText().strip(),
                "text_to_speech_model": self._tts_model_input.text().strip(),
                "text_to_speech_voice": self._tts_voice_combo.currentText().strip(),
                "audio_output_device": "" if audio_output_text == "System default" else audio_output_text,
                "energy_threshold": self._energy_threshold_spinbox.value() or None,
                "pause_threshold_ms": self._pause_threshold_spinbox.value() or None,
                "use_memory_context": self._use_memory_context_checkbox.isChecked(),
            }
        )

        packs = [pack_id for pack_id, switch in self._pack_switches.items() if switch.isChecked()]
        address = self._address_input.text().strip()
        profile_changes: dict | None = None
        if self._active_profile is not None:
            personality = normalize_personality(self._active_profile.get("personality"))
            personality.update(self._selected_personality(), address_as=address)
            profile_changes = {"personality": personality, "role_packs": packs,
                               "language": self._language_combo.currentData()}
            self._active_profile.update(profile_changes)
        else:
            # "Call me" is the same address_name that "наричай ме ..." saves.
            personalization = self._settings.personalization
            personality = normalize_personality(personalization.get("personality"))
            personality.update(self._selected_personality())  # keeps a stored address_as
            personalization["personality"] = personality
            personalization["role_packs"] = packs
            if address:
                personalization["address_name"] = address
            else:
                personalization.pop("address_name", None)

        save_settings(self._settings, path=self._settings_path)

        if model:
            os.environ["JARVIS_OPENAI_MODEL"] = model
            if self._ai is not None:
                self._ai.model = model

        self._status_label.setText("Saved.")
        self._status_timer.start()
        if profile_changes is not None:  # first, so everything that reacts to `saved` sees the new profile
            self.profile_changes_requested.emit(str(self._active_profile.get("id") or ""), profile_changes)
        self.saved.emit()
        self.personalization_changed.emit(self.current_personalization())
