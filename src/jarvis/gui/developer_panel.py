from __future__ import annotations

import json
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..permissions import ADMIN, BLOCKED, CONFIRM, SAFE

_COLUMNS = ("Time", "Source", "Command", "Intent", "Action", "Permission", "Confirmation", "Result", "Latency", "Error")

# Loaded once at construction: a generous window so a session's whole day of
# activity shows up, capped so a long-running log can't stall the UI.
_INITIAL_WINDOW_MINUTES = 24 * 60
_INITIAL_LIMIT = 200

_PERMISSION_CHOICES = ("Any", SAFE, CONFIRM, ADMIN, BLOCKED)
_RESULT_CHOICES = ("Any", "OK", "Failed")

# Seed values only, not a closed list -- both combos are editable below
# since error_taxonomy.py's taxonomy is Codex-owned and still growing (see
# TASK_SPLIT.md's "Codex Next"); free typing keeps filtering usable even
# for a value added there after this file ships.
_ERROR_TYPE_CHOICES = (
    "",
    "missing_argument",
    "unexpected_argument",
    "blocked_action",
    "user_cancelled",
    "configuration_missing",
    "unregistered_tool",
    "not_found",
    "transient_external_failure",
    "protected_action_failed",
    "command_failed",
)
_RECOMMENDED_ACTION_CHOICES = (
    "",
    "ask_for_missing_argument",
    "reject_and_reparse_intent",
    "request_safer_alternative",
    "ask_user_before_retrying",
    "open_settings_or_install_dependency",
    "reject_and_use_registered_tool",
    "ask_for_another_target_or_search_again",
    "retry_or_try_alternative_source",
    "explain_and_ask_before_retrying",
    "report_failure_to_user",
)

_FILTER_MINUTES_DEFAULT = 24 * 60
_FILTER_LIMIT_DEFAULT = 20


class DeveloperPanel(QWidget):
    """Developer-mode view of command metadata: what got classified as what
    intent/action/permission, whether confirmation was required and given,
    latency, and errors -- for both this session's live commands and
    history loaded from logs/audit.jsonl.

    Selecting a row shows its full metadata dict as pretty-printed JSON
    (workflow_steps, ai_trace, llm_tool_trace, adaptive_decisions, research/
    browser/screen-vision results, and anything else Codex adds to
    CommandResult.metadata later) rather than one hardcoded sub-view per
    shape -- none of those keys are guaranteed present on any given row,
    and a fixed set of panels would need a matching GUI change every time a
    new trace shape is added upstream.

    Reuses AuditLogger's own query methods (recent(), filtered(),
    latest_trace()) for both historical and live rows, rather than
    re-parsing the JSONL file -- guarantees all three sources format
    identically since they're read by the exact same code.
    """

    def __init__(self, audit_logger, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._audit = audit_logger
        self._records: list = []
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("Command trace (intent, action, permission, confirmation, latency)"))
        header_row.addStretch(1)
        refresh_button = QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        header_row.addWidget(refresh_button)
        layout.addLayout(header_row)

        layout.addWidget(self._build_filter_group())

        splitter = QSplitter(Qt.Orientation.Vertical)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_COLUMNS))
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self._table)

        metadata_group = QGroupBox("Metadata for selected command")
        metadata_layout = QVBoxLayout(metadata_group)
        self._metadata_view = QTextEdit()
        self._metadata_view.setReadOnly(True)
        self._metadata_view.setPlaceholderText("Select a row above to see its full metadata.")
        metadata_layout.addWidget(self._metadata_view)
        splitter.addWidget(metadata_group)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, stretch=1)

    def _build_filter_group(self) -> QGroupBox:
        group = QGroupBox("Filters")
        form = QFormLayout(group)

        self._filter_source = QLineEdit()
        form.addRow("Source", self._filter_source)
        self._filter_intent = QLineEdit()
        form.addRow("Intent", self._filter_intent)
        self._filter_action = QLineEdit()
        form.addRow("Action", self._filter_action)

        self._filter_permission = QComboBox()
        self._filter_permission.addItems(_PERMISSION_CHOICES)
        form.addRow("Permission", self._filter_permission)

        self._filter_result = QComboBox()
        self._filter_result.addItems(_RESULT_CHOICES)
        form.addRow("Result", self._filter_result)

        self._filter_error_type = QComboBox()
        self._filter_error_type.setEditable(True)
        self._filter_error_type.addItems(_ERROR_TYPE_CHOICES)
        form.addRow("Error type", self._filter_error_type)

        self._filter_recommended_action = QComboBox()
        self._filter_recommended_action.setEditable(True)
        self._filter_recommended_action.addItems(_RECOMMENDED_ACTION_CHOICES)
        form.addRow("Recommended action", self._filter_recommended_action)

        self._filter_minutes = QSpinBox()
        self._filter_minutes.setRange(1, 7 * 24 * 60)
        self._filter_minutes.setValue(_FILTER_MINUTES_DEFAULT)
        self._filter_minutes.setSuffix(" min")
        form.addRow("Time window", self._filter_minutes)

        self._filter_limit = QSpinBox()
        self._filter_limit.setRange(1, 500)
        self._filter_limit.setValue(_FILTER_LIMIT_DEFAULT)
        form.addRow("Max rows", self._filter_limit)

        button_row = QHBoxLayout()
        apply_button = QPushButton("Apply filters")
        apply_button.clicked.connect(self._apply_filters)
        button_row.addWidget(apply_button)
        clear_button = QPushButton("Clear filters")
        clear_button.clicked.connect(self._clear_filters)
        button_row.addWidget(clear_button)
        form.addRow(button_row)

        return group

    def refresh(self) -> None:
        self._load(self._audit.recent(minutes=_INITIAL_WINDOW_MINUTES, limit=_INITIAL_LIMIT))

    def _apply_filters(self) -> None:
        result_choice = self._filter_result.currentText()
        ok = {"OK": True, "Failed": False}.get(result_choice)
        permission_choice = self._filter_permission.currentText()
        records = self._audit.filtered(
            minutes=self._filter_minutes.value(),
            limit=self._filter_limit.value(),
            source=self._filter_source.text().strip(),
            intent=self._filter_intent.text().strip(),
            action=self._filter_action.text().strip(),
            permission="" if permission_choice == "Any" else permission_choice,
            ok=ok,
            error_type=self._filter_error_type.currentText().strip(),
            recommended_action=self._filter_recommended_action.currentText().strip(),
        )
        self._load(records)

    def _clear_filters(self) -> None:
        self._filter_source.clear()
        self._filter_intent.clear()
        self._filter_action.clear()
        self._filter_permission.setCurrentIndex(0)
        self._filter_result.setCurrentIndex(0)
        self._filter_error_type.setCurrentText("")
        self._filter_recommended_action.setCurrentText("")
        self._filter_minutes.setValue(_FILTER_MINUTES_DEFAULT)
        self._filter_limit.setValue(_FILTER_LIMIT_DEFAULT)
        self.refresh()

    def add_live_entry(self, source: str, text: str, result) -> None:
        """Called by app.py from the same handler that already updates
        history/speaks the result, right after CommandExecutor's audit
        write for this command -- latest_trace() reads that just-written
        line back, so a live row and a reloaded historical row for the
        same command are identical. Always appends regardless of any
        active filter -- filters are for browsing history, not a live feed
        subscription, so a command that doesn't match the current filter
        still shows up in real time rather than silently vanishing."""
        record = self._audit.latest_trace()
        if record is not None:
            self._append_row(record)

    def _load(self, records) -> None:
        self._table.setRowCount(0)
        self._records = []
        self._metadata_view.clear()
        for record in records:
            self._append_row(record)

    def _append_row(self, record) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._records.append(record)
        self._table.setItem(row, 0, QTableWidgetItem(self._format_timestamp(record.timestamp)))
        self._table.setItem(row, 1, QTableWidgetItem(record.source))
        self._table.setItem(row, 2, QTableWidgetItem(record.raw_text))
        self._table.setItem(row, 3, QTableWidgetItem(record.intent))
        self._table.setItem(row, 4, QTableWidgetItem(record.action))
        self._table.setItem(row, 5, QTableWidgetItem(record.permission))
        self._table.setItem(row, 6, QTableWidgetItem(self._format_confirmation(record)))
        self._table.setItem(row, 7, QTableWidgetItem("OK" if record.ok else "FAIL"))
        self._table.setItem(row, 8, QTableWidgetItem(self._format_latency(record.latency_ms)))
        self._table.setItem(row, 9, QTableWidgetItem(record.error))
        self._table.scrollToBottom()

    def _on_selection_changed(self) -> None:
        row = self._table.currentRow()
        # Guarded, not assumed in-range: refresh()/filtering can shrink the
        # table out from under a previously-selected row index.
        if row < 0 or row >= len(self._records):
            self._metadata_view.clear()
            return
        self._metadata_view.setPlainText(self._metadata_text(self._records[row]))

    @staticmethod
    def _metadata_text(record) -> str:
        if not record.metadata:
            return "(no metadata)"
        return json.dumps(record.metadata, indent=2, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _format_timestamp(raw: str) -> str:
        try:
            return datetime.fromisoformat(raw).astimezone().strftime("%H:%M:%S")
        except ValueError:
            return raw

    @staticmethod
    def _format_confirmation(record) -> str:
        if not record.requires_confirmation:
            return "not required"
        if record.confirmed is True:
            return "confirmed"
        if record.confirmed is False:
            return "denied"
        return "required"

    @staticmethod
    def _format_latency(latency_ms: float | None) -> str:
        return "-" if latency_ms is None else f"{latency_ms:.0f} ms"

    def row_count(self) -> int:
        return self._table.rowCount()
