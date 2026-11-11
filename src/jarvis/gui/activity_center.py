from __future__ import annotations

from datetime import datetime
import json
import re

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QListWidget, QPlainTextEdit,
                              QPushButton, QStyle, QStyledItemDelegate, QTabWidget, QVBoxLayout, QWidget)

from ..audit import AuditLogger
from ..automation_suggestions import suggest_repetitions
from ..privacy import redact_sensitive_text
from ..rollback import RollbackManager
from .aurora import DialogHeader, set_glyph, style_dialog
from .voice_core import AURORA

_RECORD = re.compile(r"^(?P<when>\S+ \S+)\s+\[(?P<status>\w+)\]\s+(?P<title>.*)$")
_UNDO = re.compile(r"^(?P<status>NEXT|WAIT)\s+(?P<when>\S+)\s+(?P<title>.*)$")
_STATUS_COLORS = {"OK": AURORA["success"], "FAILED": AURORA["danger"], "TEST": AURORA["warning"],
                  "NEXT": AURORA["accent"], "WAIT": AURORA["neutral"]}


class _RowDelegate(QStyledItemDelegate):
    """Draws "time [STATUS] action" and "NEXT time label" rows as a status dot,
    the action and the time; the item text itself is unchanged."""

    def sizeHint(self, option, index) -> QSize:
        return QSize(option.rect.width(), 40)

    def paint(self, painter: QPainter, option, index) -> None:
        text = str(index.data() or "")
        match = _RECORD.match(text) or _UNDO.match(text)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(option.rect).adjusted(2, 2, -2, -2)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected or hovered:
            path = QPainterPath()
            path.addRoundedRect(box, 8, 8)
            painter.fillPath(path, QColor(34, 211, 238, 30) if selected else QColor(255, 255, 255, 8))
        font = QFont(option.font)
        if match is None:
            painter.setPen(QColor(AURORA["text_tertiary"]))
            painter.setFont(font)
            painter.drawText(box.adjusted(12, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter, text)
            painter.restore()
            return
        status = match["status"]
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_STATUS_COLORS.get(status, AURORA["neutral"])))
        painter.drawEllipse(QRectF(box.left() + 12, box.center().y() - 4, 8, 8))
        when = match["when"].replace("T", " ")
        small = QFont(font)
        small.setPointSizeF(max(7.0, font.pointSizeF() - 1))
        painter.setFont(small)
        painter.setPen(QColor(AURORA["text_tertiary"]))
        painter.drawText(box.adjusted(0, 0, -12, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                         f"{when}  ·  {status}")
        width = painter.fontMetrics().horizontalAdvance(f"{when}  ·  {status}") + 24
        title = QFont(font)
        title.setWeight(QFont.Weight.DemiBold)
        painter.setFont(title)
        painter.setPen(QColor(AURORA["text"]))
        area = box.adjusted(30, 0, -width, 0)
        painter.drawText(area, Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(match["title"], Qt.TextElideMode.ElideRight, int(area.width())))
        painter.restore()


class ActivityCenter(QDialog):
    """A read-only audit view plus a confirmed, latest-action-only undo request."""

    undo_requested = Signal(str)

    def __init__(self, audit: AuditLogger, rollback: RollbackManager | None = None, parent=None) -> None:
        super().__init__(parent)
        self.audit, self.rollback = audit, rollback or RollbackManager()
        self.setWindowTitle("Jarvis | Activity & Undo")
        self.setMinimumSize(620, 420)
        style_dialog(self, "activityCenter")  # the Aurora look (gui/aurora.py)
        self.resize(820, 580)
        self.records = []
        self._latest_timestamp = ""
        self._busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(DialogHeader("history", "Активност",
                                      "Какво направи Jarvis и защо, какво може да се върне и какво се повтаря."))
        self.tabs = QTabWidget()
        actions, undo = QWidget(), QWidget()
        self.tabs.addTab(actions, "Какво направи?")
        self.tabs.addTab(undo, "Undo Center")
        self.suggestions = QPlainTextEdit()
        self.suggestions.setReadOnly(True)
        self.tabs.addTab(self.suggestions, "Повтарящи се задачи")
        action_layout = QVBoxLayout(actions)
        self.actions_list = QListWidget()
        self._rows = _RowDelegate(self)
        self.actions_list.setItemDelegate(self._rows)
        self.actions_list.setMouseTracking(True)
        self.actions_list.currentRowChanged.connect(self._show_record)
        action_layout.addWidget(self.actions_list, 1)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        action_layout.addWidget(self.detail, 1)
        undo_layout = QVBoxLayout(undo)
        self.undo_list = QListWidget()
        self.undo_list.setItemDelegate(self._rows)
        undo_layout.addWidget(self.undo_list, 1)
        self.undo_result = QLabel()
        self.undo_result.setTextFormat(Qt.TextFormat.PlainText)
        self.undo_result.setWordWrap(True)
        undo_layout.addWidget(self.undo_result)
        self.undo_button = QPushButton("Върни последната промяна")
        set_glyph(self.undo_button, "undo", QStyle.StandardPixmap.SP_ArrowBack)
        self.undo_button.clicked.connect(self._request_undo)
        undo_layout.addWidget(self.undo_button)
        layout.addWidget(self.tabs)
        footer = QHBoxLayout()
        refresh = QPushButton("Обнови")
        set_glyph(refresh, "refresh", QStyle.StandardPixmap.SP_BrowserReload)
        refresh.clicked.connect(self.refresh)
        footer.addWidget(refresh)
        footer.addStretch()
        close = QPushButton("Затвори")
        close.clicked.connect(self.hide)
        footer.addWidget(close)
        layout.addLayout(footer)

    def open_page(self, undo: bool = False) -> None:
        self.refresh()
        self.tabs.setCurrentIndex(1 if undo else 0)
        self.show()
        self.raise_()
        self.activateWindow()

    def refresh(self) -> None:
        self.actions_list.clear()
        self.detail.clear()
        try:
            self.records = list(reversed(self.audit.filtered(minutes=7 * 24 * 60, limit=100)))
            for record in self.records:
                stamp = datetime.fromisoformat(record.timestamp).astimezone().strftime("%d.%m %H:%M:%S")
                status = "TEST" if record.dry_run else "OK" if record.ok else "FAILED"
                self.actions_list.addItem(f"{stamp}  [{status}]  {record.action or record.intent or 'command'}")
            if self.records:
                self.actions_list.setCurrentRow(0)
            else:
                self.detail.setPlainText("Няма записани действия за последните 7 дни.")
            suggestions = suggest_repetitions(self.records)
            self.suggestions.setPlainText("\n\n".join(
                f"{item['count']} x {item['action']}\n{json.dumps(item['arguments'], ensure_ascii=False)}\n"
                f"Последно: {item['last_seen']}\nСтатус: предложение, не е включено"
                for item in suggestions) or "Няма повтарящи се команди сред последните 100 записа.")
        except (OSError, ValueError, KeyError) as exc:
            self.detail.setPlainText(f"Журналът не може да бъде прочетен: {exc}")
            self.suggestions.setPlainText("Няма достъп до журнала.")
        self.undo_list.clear()
        self._latest_timestamp = ""
        try:
            stack = self.rollback.load()
            for index, item in enumerate(reversed(stack)):
                self.undo_list.addItem(f"{'NEXT' if index == 0 else 'WAIT'}  {item.timestamp[:19]}  {item.label}")
            if stack:
                self._latest_timestamp = stack[-1].timestamp
            else:
                self.undo_list.addItem("Няма обратима промяна.")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.undo_result.setText(f"Историята за връщане не може да бъде прочетена: {exc}")
        self.undo_button.setEnabled(bool(self._latest_timestamp) and not self._busy)

    def _show_record(self, row: int) -> None:
        if row < 0 or row >= len(self.records):
            return
        record = self.records[row]
        metadata = record.metadata or {}
        trace = metadata.get("llm_tool_trace") or {}
        reason = metadata.get("intent_reason") or (trace.get("reason") if isinstance(trace, dict) else "")
        reason = reason or "Няма отделно записана причина; виж заявката и източника."
        text = (f"Заявка: {record.raw_text}\nИзточник: {record.source}\nПричина: {reason}\n"
                f"Действие: {record.action}\nРазрешение: {record.permission}\n"
                f"Потвърждение: {record.confirmed}\nТестов режим: {record.dry_run}\n\n"
                f"Проверка: {metadata.get('verification', 'Няма отделно записано доказателство.')}\n"
                f"Резултат:\n{record.message}\n\nГрешка: {record.error or '-'}")
        self.detail.setPlainText(redact_sensitive_text(text).text[:16000])

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.undo_button.setEnabled(bool(self._latest_timestamp) and not busy)

    def _request_undo(self) -> None:
        if self._latest_timestamp and not self._busy:
            self.set_busy(True)
            self.undo_result.setText("Очаква потвърждение...")
            self.undo_requested.emit(self._latest_timestamp)

    def show_undo_result(self, message: str) -> None:
        self.undo_result.setText(redact_sensitive_text(message).text[:2000])
        self.set_busy(False)
        self.refresh()
