from __future__ import annotations

import sys
import time

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QStyle, QToolButton, QVBoxLayout, QWidget

from .voice_core import FONT_BODY, FONT_SEMIBOLD, glyph_icon

# The privacy indicator keeps its amber identity (never the calm cyan of the
# rest of the app) with a pulsing "recording" dot; painted by Claude's UI kit.
# Two lines: the state, then what it means. Drag it anywhere; double-click
# puts it back at the top. It is kept out of the frames Jarvis sends.
_INDICATOR_STYLE = f"""
QLabel#shareTitle {{ background: transparent; color: #FFE0A0; font-family: {FONT_SEMIBOLD}; font-weight: 600;
    font-size: 11px; letter-spacing: 1.2px; }}
QLabel#shareDetail {{ background: transparent; color: #CDB88F; font-family: {FONT_BODY}; font-size: 11.5px; }}
QToolButton {{ background: rgba(230, 184, 106, 28); border: 1px solid rgba(230, 184, 106, 125); border-radius: 15px;
    color: #FFE0A0; font-family: {FONT_SEMIBOLD}; font-weight: 600; font-size: 12px; padding: 0 12px 0 9px; }}
QToolButton:hover {{ background: rgba(230, 184, 106, 64); }}
QToolButton:pressed {{ background: rgba(230, 184, 106, 96); }}
"""
_WDA_EXCLUDEFROMCAPTURE = 0x11


def _exclude_from_capture(widget: QWidget) -> None:
    """Leave the pill out of screen captures (Windows 10 2004+), so the AI sees
    the screen, not the indicator on top of it. Older Windows: no change."""
    if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
        return
    try:
        import ctypes

        ctypes.windll.user32.SetWindowDisplayAffinity(ctypes.c_void_p(int(widget.winId())), _WDA_EXCLUDEFROMCAPTURE)
    except Exception:
        pass


class ScreenSharingIndicator(QWidget):
    _saved_position: QPoint | None = None  # where the user dragged it, for this run

    def __init__(self, sharing):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
        self.sharing = sharing
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)  # the pill is painted
        self.setWindowTitle("Jarvis screen sharing")
        self.setAccessibleName("Jarvis screen sharing")
        self.setFixedSize(420, 52)
        self.setStyleSheet(_INDICATOR_STYLE)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._pulse = 0
        self._session = ""
        self._started_at = 0.0
        self._shown_minutes = -1
        self._drag_offset: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(40, 6, 11, 6)  # room for the painted dot
        layout.setSpacing(10)
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(1)
        self.label = QLabel("SCREEN SHARING")
        self.label.setObjectName("shareTitle")
        self.detail = QLabel("")
        self.detail.setObjectName("shareDetail")
        text.addWidget(self.label)
        text.addWidget(self.detail)
        layout.addLayout(text, 1)
        self.stop_button = QToolButton()
        self.stop_button.setText("Stop")
        self.stop_button.setFixedHeight(30)
        self.stop_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.stop_button.setIcon(glyph_icon("stop", QStyle.StandardPixmap.SP_MediaStop, self.style(),
                                            color="#FFE0A0", size=12))
        self.stop_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stop_button.setToolTip("Stop screen sharing")
        self.stop_button.setAccessibleName("Stop screen sharing")
        self.stop_button.clicked.connect(self.stop)
        layout.addWidget(self.stop_button)
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        sharing.indicator_available = True

    def refresh(self):
        state = self.sharing.state()
        if not state["sharing"]:
            self.hide()
            self._session = ""
            return
        if state.get("session_id") != self._session:
            self._session, self._started_at, self._shown_minutes = state.get("session_id", ""), time.monotonic(), -1
        if not self.isVisible():
            self._place()
            self.show()
        if state.get("capture_mode") == "chat_on_question":
            title, detail = "SCREEN CHAT  ·  READY", "One picture of this screen per question you ask."
        elif state["live"]:
            title, detail = "SCREEN SHARING  ·  LIVE", "Jarvis sees this screen during the voice call."
        else:
            title, detail = "SCREEN SHARING  ·  READY", "Ask about it, or start a voice call to talk it over."
        if self.label.text() != title:
            self.label.setText(title)
            self.detail.setText(detail)
        minutes = int((time.monotonic() - self._started_at) // 60)
        if minutes != self._shown_minutes:
            self._shown_minutes = minutes
            shared = "Shared just now" if minutes < 1 else f"Shared for {minutes} min"
            self.setToolTip(f"{shared}. Drag to move it; double-click to put it back at the top.")
        if self.isVisible():
            self.sharing.indicator_visible()
        self._pulse = (self._pulse + 1) % 8
        self.update()

    # ------------------------------------------------------------ placement

    def _place(self):
        saved = ScreenSharingIndicator._saved_position
        if saved is not None and QGuiApplication.screenAt(saved + QPoint(self.width() // 2, self.height() // 2)):
            self.move(saved)
            return
        screen = QApplication.primaryScreen()
        if screen:
            area = screen.availableGeometry()
            self.move(area.center().x() - self.width() // 2, area.top() + 10)

    def showEvent(self, event):
        super().showEvent(event)
        _exclude_from_capture(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            target = event.globalPosition().toPoint() - self._drag_offset
            screen = QGuiApplication.screenAt(event.globalPosition().toPoint()) or QApplication.primaryScreen()
            if screen:
                area = screen.availableGeometry()
                target.setX(max(area.left(), min(target.x(), area.right() - self.width() + 1)))
                target.setY(max(area.top(), min(target.y(), area.bottom() - self.height() + 1)))
            self.move(target)
            ScreenSharingIndicator._saved_position = QPoint(target)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        ScreenSharingIndicator._saved_position = None
        self._place()
        event.accept()

    # --------------------------------------------------------------- painting

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        pill = QPainterPath()
        pill.addRoundedRect(box, box.height() / 2, box.height() / 2)
        fill = QLinearGradient(box.topLeft(), box.bottomLeft())
        fill.setColorAt(0, QColor(38, 31, 18, 246))
        fill.setColorAt(1, QColor(24, 20, 12, 246))
        painter.fillPath(pill, fill)
        painter.setPen(QPen(QColor(230, 184, 106, 135), 1))
        painter.drawPath(pill)
        glow = 1 - abs(4 - self._pulse) / 4  # 0 -> 1 -> 0 over two seconds
        center = QPointF(22, box.center().y())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(242, 139, 130, round(34 + 76 * glow)))
        painter.drawEllipse(center, 8.5, 8.5)
        painter.setBrush(QColor("#F28B82"))
        painter.drawEllipse(center, 4, 4)

    def stop(self):
        self.sharing.stop()
        self.hide()

    def closeEvent(self, event):
        self.stop()
        super().closeEvent(event)

    def shutdown(self):
        self.timer.stop()
        self.sharing.indicator_available = False
        self.stop()
