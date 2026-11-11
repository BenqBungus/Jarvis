"""Aurora kit for Jarvis's secondary windows (Screen Chat, Game Chat, Activity,
Gmail, Project changes): one header, pill tabs, segmented controls, cards,
status chips and a composer, so every window matches the HUD.

Owned by Claude (UI). The windows themselves keep their own logic; they only
call style_dialog()/DialogHeader/segmented()/composer().
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QFrame, QHBoxLayout, QLabel, QStyle, QVBoxLayout, QWidget

from .voice_core import AURORA, BASE_STYLE, CHECK_IMAGE, FONT_DISPLAY, FONT_MONO, FONT_SEMIBOLD, glyph_icon

_A = AURORA


def dialog_rules(scope: str) -> str:
    """Rules for everything inside `scope` (an #objectName or a type such as QDialog)."""
    rules = f"""
{scope} {{ background: {_A['bg']}; }}
{scope} QLabel {{ color: {_A['text_secondary']}; }}
{scope} QLabel[role="dialogTitle"], {scope} QLabel#discussionTitle {{ color: {_A['text']};
    font-family: {FONT_DISPLAY}; font-weight: 600; font-size: 17px; }}
{scope} QLabel[role="dialogSubtitle"] {{ color: {_A['text_tertiary']}; font-size: 12px; }}
{scope} QLabel[role="overline"] {{ color: {_A['text_tertiary']}; font-family: {FONT_SEMIBOLD}; font-weight: 600;
    font-size: 10px; letter-spacing: 1.4px; }}
{scope} QLabel[role="chip"] {{ background: {_A['card_hover']}; color: {_A['text_secondary']};
    border: 1px solid {_A['border_strong']}; border-radius: 10px; padding: 2px 10px; font-size: 11px; }}
{scope} QLabel#status, {scope} QLabel#panelVoiceState, {scope} QLabel[role="note"] {{
    color: {_A['text_tertiary']}; font-size: 12px; }}
{scope} QLabel[role="body"] {{ color: {_A['text']}; font-size: 13px; }}
{scope} QFrame[role="card"] {{ background: {_A['card']}; border: 1px solid {_A['border']}; border-radius: 12px; }}
{scope} QFrame[role="rule"] {{ background: {_A['border']}; border: none; }}
{scope} QPlainTextEdit, {scope} QTextBrowser, {scope} QTextEdit {{ background: {_A['bg_raised']};
    border: 1px solid {_A['border']}; border-radius: 12px; padding: 10px 12px; color: {_A['text']};
    font-size: 13px; selection-background-color: rgba(34, 211, 238, 72); }}
{scope} QPlainTextEdit:focus, {scope} QTextBrowser:focus {{ border-color: {_A['border_strong']}; }}
{scope} QListWidget {{ background: {_A['bg_raised']}; border: 1px solid {_A['border']}; border-radius: 12px;
    padding: 6px; outline: 0; }}
{scope} QListWidget::item {{ padding: 0 8px; border-radius: 8px; color: {_A['text']}; }}
{scope} QListWidget::item:selected {{ background: rgba(34, 211, 238, 28); color: {_A['text']}; }}
{scope} QListWidget::item:hover:!selected {{ background: rgba(255, 255, 255, 7); }}
{scope} QTabWidget::pane {{ border: none; top: 6px; }}
{scope} QTabBar {{ qproperty-drawBase: 0; }}
{scope} QTabBar::tab {{ background: transparent; color: {_A['text_tertiary']}; padding: 6px 14px; margin-right: 4px;
    border: 1px solid transparent; border-radius: 8px; font-family: {FONT_SEMIBOLD}; font-weight: 600; }}
{scope} QTabBar::tab:selected {{ background: rgba(34, 211, 238, 26); color: {_A['text']};
    border-color: rgba(34, 211, 238, 70); }}
{scope} QTabBar::tab:hover:!selected {{ background: rgba(255, 255, 255, 7); color: {_A['text_secondary']}; }}
{scope} QFrame[role="segmented"] {{ background: {_A['bg_raised']}; border: 1px solid {_A['border']};
    border-radius: 10px; }}
{scope} QFrame[role="segmented"] QPushButton {{ background: transparent; border: 1px solid transparent;
    border-radius: 7px; padding: 4px 14px; color: {_A['text_tertiary']}; }}
{scope} QFrame[role="segmented"] QPushButton:checked {{ background: rgba(34, 211, 238, 30); color: {_A['text']};
    border-color: rgba(34, 211, 238, 80); }}
{scope} QFrame[role="segmented"] QPushButton:hover:!checked {{ color: {_A['text_secondary']}; }}
{scope} QFrame[role="composer"] {{ background: {_A['input']}; border: 1px solid {_A['border_strong']};
    border-radius: 14px; }}
{scope} QFrame[role="composer"] QLineEdit {{ background: transparent; border: none; padding: 7px 4px;
    font-size: 14px; }}
{scope} QToolButton[role="ghost"] {{ background: transparent; border: 1px solid transparent; border-radius: 9px; }}
{scope} QToolButton[role="ghost"]:hover {{ background: #172130; border-color: {_A['border_strong']}; }}
{scope} QToolButton[role="ghost"]:checked {{ background: rgba(230, 184, 106, 30); border-color: rgba(230, 184, 106, 110); }}
{scope} QToolButton[role="ghost"]:disabled {{ background: transparent; border-color: transparent; }}
{scope} QToolButton[role="send"] {{ border: none; border-radius: 16px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent']}, stop:1 {_A['accent_2']}); }}
{scope} QToolButton[role="send"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent_light']}, stop:1 {_A['accent_2_light']}); }}
{scope} QToolButton[role="send"]:disabled {{ background: #172130; }}
{scope} QToolButton[role="call"] {{ border: none; border-radius: 17px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent']}, stop:1 {_A['accent_2']}); }}
{scope} QToolButton[role="call"]:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent_light']}, stop:1 {_A['accent_2_light']}); }}
{scope} QToolButton[role="call"][active="true"] {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #F6A197, stop:1 #E0685C); }}
{scope} QToolButton[role="call"]:disabled {{ background: #172130; }}
{scope} QPushButton[variant="danger"] {{ color: {_A['danger']}; }}
{scope} QPushButton[variant="danger"]:hover {{ background: rgba(242, 139, 130, 22); border-color: rgba(242, 139, 130, 90); }}
{scope} QCheckBox {{ spacing: 9px; color: {_A['text_secondary']}; }}
{scope} QCheckBox:hover {{ color: {_A['text']}; }}
{scope} QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #3A4658;
    background: {_A['input']}; }}
{scope} QCheckBox::indicator:hover {{ border-color: #56657A; }}
{scope} QCheckBox::indicator:checked {{ border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_A['accent']}, stop:1 {_A['accent_2']}); }}
{scope} QPlainTextEdit[role="code"] {{ font-family: {FONT_MONO}; font-size: 12px; }}
"""
    if CHECK_IMAGE:
        rules += f'{scope} QCheckBox::indicator:checked {{ image: url("{CHECK_IMAGE}"); }}\n'
    return rules


def style_dialog(widget: QWidget, name: str, extra: str = "") -> None:
    """Give a secondary window the Aurora look (scoped to its object name)."""
    widget.setObjectName(name)
    widget.setStyleSheet(BASE_STYLE + dialog_rules(f"#{name}") + extra)


def _paint_badge(painter: QPainter, side: float, glyph: str, style: QStyle) -> None:
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    box = QRectF(0, 0, side, side).adjusted(0.5, 0.5, -0.5, -0.5)
    radius = box.width() * 0.3
    fill = QLinearGradient(box.topLeft(), box.bottomRight())
    fill.setColorAt(0.0, QColor("#12202B"))
    fill.setColorAt(1.0, QColor("#0D121B"))
    path = QPainterPath()
    path.addRoundedRect(box, radius, radius)
    painter.fillPath(path, fill)
    edge = QLinearGradient(box.topLeft(), box.bottomRight())
    edge.setColorAt(0.0, QColor(34, 211, 238, 150))
    edge.setColorAt(1.0, QColor(139, 92, 246, 120))
    painter.setPen(QPen(edge, 1))
    painter.drawPath(path)
    size = round(side * 0.46)
    icon = glyph_icon(glyph, QStyle.StandardPixmap.SP_FileDialogInfoView, style, color=_A["accent_light"], size=size)
    painter.drawPixmap(round((side - size) / 2), round((side - size) / 2), icon.pixmap(QSize(size, size), 2.0))


def badge_pixmap(glyph: str, side: int, style: QStyle) -> QPixmap:
    """The header badge as a crisp 2x pixmap (for QMessageBox icons)."""
    pixmap = QPixmap(side * 2, side * 2)
    pixmap.setDevicePixelRatio(2.0)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    _paint_badge(painter, side, glyph, style)
    painter.end()
    return pixmap


class GlyphBadge(QWidget):
    """The rounded icon tile at the start of a window header."""

    def __init__(self, glyph: str, size: int = 38, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        _paint_badge(painter, self.width(), self._glyph, self.style())


class DialogHeader(QWidget):
    """Badge, title and subtitle, with room on the right for chips or buttons."""

    def __init__(self, glyph: str, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 4)
        layout.setSpacing(12)
        layout.addWidget(GlyphBadge(glyph), 0, Qt.AlignmentFlag.AlignTop)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        self.title_label = QLabel(title)
        self.title_label.setProperty("role", "dialogTitle")
        texts.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setProperty("role", "dialogSubtitle")
        self.subtitle_label.setWordWrap(True)
        self.subtitle_label.setVisible(bool(subtitle))
        texts.addWidget(self.subtitle_label)
        layout.addLayout(texts, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)
        return widget


def chip(text: str) -> QLabel:
    label = QLabel(text)
    label.setProperty("role", "chip")
    return label


def segmented(*buttons: QAbstractButton) -> QFrame:
    """Checkable buttons as one pill control (Text | Voice)."""
    frame = QFrame()
    frame.setProperty("role", "segmented")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(3, 3, 3, 3)
    layout.setSpacing(2)
    for button in buttons:
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(button)
    return frame


def composer(field: QWidget, *buttons: QWidget) -> QFrame:
    """A rounded input bar with its buttons inside (like the command overlay)."""
    frame = QFrame()
    frame.setProperty("role", "composer")
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(12, 4, 5, 4)
    layout.setSpacing(6)
    layout.addWidget(field, 1)
    for button in buttons:
        layout.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
    return frame


def card(*widgets: QWidget, margins: tuple[int, int, int, int] = (14, 12, 14, 12), spacing: int = 6) -> QFrame:
    frame = QFrame()
    frame.setProperty("role", "card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return frame


def set_role(widget: QWidget, role: str, **properties) -> QWidget:
    widget.setProperty("role", role)
    for key, value in properties.items():
        widget.setProperty(key, value)
    return widget


def set_glyph(button, glyph: str, fallback: QStyle.StandardPixmap, *, size: int = 16, color: str | None = None,
              checked_color: str | None = None) -> None:
    kwargs = {"size": size}
    if color:
        kwargs["color"] = color
    if checked_color:
        kwargs["checked_color"] = checked_color
    button.setIcon(glyph_icon(glyph, fallback, button.style(), **kwargs))
    button.setIconSize(QSize(size, size))
