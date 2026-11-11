from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_ALL_CATEGORIES = "All"


class ToolsPanel(QWidget):
    """Read-only display of the tools router.tools (a ToolRegistry) exposes:
    name/category/permission/description/parameters per registered tool.

    Tools are registered once when CommandRouter is constructed
    (build_core_tool_registry) and never change afterward, so this panel
    reads router.tools.list_specs() once at construction rather than
    needing a live refresh mechanism.
    """

    def __init__(self, tool_registry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._specs = list(tool_registry.list_specs())
        self._build_ui()
        self._populate()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Category:"))
        self._category_filter = QComboBox()
        categories = [_ALL_CATEGORIES] + sorted({spec.category for spec in self._specs})
        self._category_filter.addItems(categories)
        self._category_filter.currentTextChanged.connect(self._populate)
        filter_row.addWidget(self._category_filter)
        filter_row.addWidget(QLabel(f"{len(self._specs)} tools registered"))
        filter_row.addStretch(1)
        layout.addLayout(filter_row)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Name", "Category", "Permission", "Description", "Parameters"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self._table, stretch=1)

    def _populate(self, *_args) -> None:
        category = self._category_filter.currentText()
        visible = self._specs if category == _ALL_CATEGORIES else [s for s in self._specs if s.category == category]
        self._table.setRowCount(0)
        for spec in visible:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._table.setItem(row, 0, QTableWidgetItem(spec.name))
            self._table.setItem(row, 1, QTableWidgetItem(spec.category))
            self._table.setItem(row, 2, QTableWidgetItem(spec.permission))
            self._table.setItem(row, 3, QTableWidgetItem(spec.description))
            self._table.setItem(row, 4, QTableWidgetItem(self._format_parameters(spec.parameters)))

    @staticmethod
    def _format_parameters(parameters) -> str:
        if not parameters:
            return "(none)"
        parts = []
        for param in parameters:
            suffix = "" if param.required else ", optional"
            parts.append(f"{param.name} ({param.type}{suffix})")
        return "; ".join(parts)

    def tool_count(self) -> int:
        return len(self._specs)

    def visible_row_count(self) -> int:
        return self._table.rowCount()
