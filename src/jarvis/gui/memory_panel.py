from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

# Mirrors long_term.py's MEMORY_CATEGORIES exactly. A closed dropdown, not
# free text: normalize_memory_category() in the backend silently falls back
# to "general" for anything else, which would otherwise let a typo silently
# miscategorize a memory with no feedback.
_MEMORY_CATEGORIES = ("general", "preference", "project", "device", "game", "website", "routine")

# router._normalize() strips the wake word and lowercases before any regex
# runs -- every dispatched command below needs the literal prefix anyway,
# matching every other synthesized command in this app (see
# main_window.py's _QUICK_ACTION_COMMANDS/_MODE_COMMANDS).
_SHOW_CATEGORIES_COMMAND = "jarvis покажи категории памет"
_SHOW_EPISODES_COMMAND = "jarvis покажи епизодична памет"


class MemoryPanel(QWidget):
    """View/search/edit/categorize/delete saved long-term memories, and
    browse read-only episodic conversation/action summaries.

    Deliberately has no backend dependency of its own (no LongTermMemory/
    AuditLogger/etc. reference) -- unlike every other tab widget, this one
    both reads AND writes, and the only safe way to write is through the
    exact same command_requested -> CommandExecutor -> router.handle()
    pipeline every other button in this app already uses.
    router.tools.execute() is never an option here: it applies zero
    permission/confirmation/audit gating (see tool_registry.py), so calling
    it directly from a GUI button would silently bypass GuiSafetyPolicy and
    the audit trail both.

    Every router-exposed memory listing command caps out at 8 results with
    no pagination, so this is a search box + results, not a browsable table
    of "your whole memory store" -- and is labelled that way in the UI
    rather than silently surprising someone with more than 8 memories saved.

    Only "jarvis търси семантично в паметта <query>" returns a usable
    per-row id (the real SQLite primary key, for kind=="long_term" rows) --
    the plain "какво помниш" listing returns bare content strings with
    nothing to hang an Edit/Move button off. Episode-kind rows share the
    same results list but use a different id space with no update/delete
    operation anywhere in the backend, so their Edit/Move/Delete stay
    disabled.
    """

    # text, source -- always "memory", never "button" like other panels'
    # quick actions. app.py's on_result_ready special-cases this source to
    # skip history/speech: bootstrap() fires two commands on every launch
    # with no user action at all, and every result already has its own
    # visual home in this panel's own table/status label -- speaking
    # "Memory categories: general 76, preference 0, ..." out loud on every
    # app start, or every keystroke-driven search, would be a real
    # regression, not just cosmetic. developer_panel still logs these
    # (add_live_entry is unconditional), so nothing is hidden from the
    # audit trail, only from the spoken/visible-history UI surface.
    command_requested = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._last_memory_query = ""
        self._last_episode_query = ""
        self._selected_memory_id: str | None = None
        self._selected_memory_kind: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_memories_tab(), "Memories")
        tabs.addTab(self._build_episodes_tab(), "Episodes")
        layout.addWidget(tabs)
        self._status_label = QLabel("")
        layout.addWidget(self._status_label)

    def _build_memories_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(
            QLabel(
                "Search saves memories, not a full listing -- every backend memory "
                "query returns at most 8 results."
            )
        )

        search_row = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search memories, e.g. browser preference")
        self._search_input.returnPressed.connect(self._on_search)
        search_row.addWidget(self._search_input, stretch=1)
        search_button = QPushButton("Search")
        search_button.clicked.connect(self._on_search)
        search_row.addWidget(search_button)
        layout.addLayout(search_row)

        self._category_labels: dict[str, QLabel] = {}
        categories_row = QHBoxLayout()
        for category in _MEMORY_CATEGORIES:
            label = QLabel(f"{category}: -")
            self._category_labels[category] = label
            categories_row.addWidget(label)
        layout.addLayout(categories_row)

        self._results_table = QTableWidget(0, 5)
        self._results_table.setHorizontalHeaderLabels(["Kind", "Id", "Category", "Score", "Content"])
        self._results_table.horizontalHeader().setStretchLastSection(True)
        self._results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._results_table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._results_table, stretch=1)

        actions_group = QGroupBox("Selected memory")
        actions_layout = QVBoxLayout(actions_group)
        self._selection_label = QLabel("No long-term memory selected.")
        actions_layout.addWidget(self._selection_label)

        edit_row = QHBoxLayout()
        self._edit_content_input = QLineEdit()
        self._edit_content_input.setPlaceholderText("New content")
        edit_row.addWidget(self._edit_content_input, stretch=1)
        self._edit_button = QPushButton("Update Content")
        self._edit_button.setEnabled(False)
        self._edit_button.clicked.connect(self._on_edit)
        edit_row.addWidget(self._edit_button)
        actions_layout.addLayout(edit_row)

        move_row = QHBoxLayout()
        self._move_category_combo = QComboBox()
        self._move_category_combo.addItems(_MEMORY_CATEGORIES)
        move_row.addWidget(self._move_category_combo, stretch=1)
        self._move_button = QPushButton("Move to Category")
        self._move_button.setEnabled(False)
        self._move_button.clicked.connect(self._on_move)
        move_row.addWidget(self._move_button)
        actions_layout.addLayout(move_row)

        self._delete_button = QPushButton("Delete Selected")
        self._delete_button.setEnabled(False)
        self._delete_button.clicked.connect(self._on_delete)
        actions_layout.addWidget(self._delete_button)

        layout.addWidget(actions_group)

        add_group = QGroupBox("Add memory")
        add_row = QHBoxLayout(add_group)
        self._add_category_combo = QComboBox()
        self._add_category_combo.addItems(_MEMORY_CATEGORIES)
        add_row.addWidget(self._add_category_combo)
        self._add_content_input = QLineEdit()
        self._add_content_input.setPlaceholderText("What should Jarvis remember?")
        self._add_content_input.returnPressed.connect(self._on_add)
        add_row.addWidget(self._add_content_input, stretch=1)
        add_button = QPushButton("Add")
        add_button.clicked.connect(self._on_add)
        add_row.addWidget(add_button)
        layout.addWidget(add_group)

        return tab

    def _build_episodes_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel("Read-only: episodic summaries have no edit or delete operation in the backend."))

        search_row = QHBoxLayout()
        self._episode_search_input = QLineEdit()
        self._episode_search_input.setPlaceholderText("Search episode topics/summaries (optional)")
        self._episode_search_input.returnPressed.connect(self._on_episode_search)
        search_row.addWidget(self._episode_search_input, stretch=1)
        episode_search_button = QPushButton("Search")
        episode_search_button.clicked.connect(self._on_episode_search)
        search_row.addWidget(episode_search_button)
        layout.addLayout(search_row)

        self._episodes_table = QTableWidget(0, 5)
        self._episodes_table.setHorizontalHeaderLabels(["Source", "Topics", "Turns/Actions", "Created", "Summary"])
        self._episodes_table.horizontalHeader().setStretchLastSection(True)
        self._episodes_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._episodes_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self._episodes_table, stretch=1)

        return tab

    def bootstrap(self) -> None:
        """Populates category counts and episode summaries. Must be called
        by app.py after command_requested/result routing are both fully
        wired -- unlike DeveloperPanel, this widget cannot self-populate in
        __init__, since nothing is connected to command_requested yet at
        construction time and the emitted signal would simply be dropped."""
        self.command_requested.emit(_SHOW_CATEGORIES_COMMAND, "memory")
        self.command_requested.emit(_SHOW_EPISODES_COMMAND, "memory")

    def _on_search(self) -> None:
        query = self._search_input.text().strip()
        if not query:
            return
        self._last_memory_query = query
        self.command_requested.emit(f"jarvis търси семантично в паметта {query}", "memory")

    def _on_episode_search(self) -> None:
        query = self._episode_search_input.text().strip()
        self._last_episode_query = query
        text = f"jarvis търси в епизодичната памет {query}" if query else _SHOW_EPISODES_COMMAND
        self.command_requested.emit(text, "memory")

    def _on_add(self) -> None:
        content = self._add_content_input.text().strip()
        if not content:
            return
        category = self._add_category_combo.currentText()
        self.command_requested.emit(f"jarvis запомни като {category}: {content}", "memory")
        self._add_content_input.clear()

    def _on_edit(self) -> None:
        if self._selected_memory_id is None:
            return
        new_content = self._edit_content_input.text().strip()
        if not new_content:
            return
        self.command_requested.emit(f"jarvis промени памет #{self._selected_memory_id} на {new_content}", "memory")

    def _on_move(self) -> None:
        if self._selected_memory_id is None:
            return
        category = self._move_category_combo.currentText()
        self.command_requested.emit(
            f"jarvis сложи памет #{self._selected_memory_id} в категория {category}", "button"
        )

    def _on_delete(self) -> None:
        row = self._results_table.currentRow()
        if row < 0:
            return
        content_item = self._results_table.item(row, 4)
        content = content_item.text() if content_item else ""
        if not content:
            return
        answer = QMessageBox.question(
            self,
            "Delete memory",
            "This deletes every saved memory whose content or category contains this exact "
            f'text, not just this one row -- the backend has no per-id delete.\n\n"{content}"',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.command_requested.emit(f"jarvis забрави {content}", "memory")

    def _on_selection_changed(self) -> None:
        row = self._results_table.currentRow()
        kind_item = self._results_table.item(row, 0) if row >= 0 else None
        if kind_item is None:
            self._selected_memory_id = None
            self._selected_memory_kind = None
            self._selection_label.setText("No long-term memory selected.")
            self._set_mutation_buttons_enabled(False)
            return

        data = kind_item.data(Qt.ItemDataRole.UserRole) or {}
        self._selected_memory_id = data.get("id")
        self._selected_memory_kind = data.get("kind")

        if self._selected_memory_kind == "long_term":
            self._selection_label.setText(f"Selected memory #{self._selected_memory_id}.")
            self._set_mutation_buttons_enabled(True)
        else:
            self._selection_label.setText(
                "Episode results have no id-based update/delete in the backend -- select a "
                "long-term memory row to edit, move, or delete it."
            )
            self._set_mutation_buttons_enabled(False)

    def _set_mutation_buttons_enabled(self, enabled: bool) -> None:
        self._edit_button.setEnabled(enabled)
        self._move_button.setEnabled(enabled)
        self._delete_button.setEnabled(enabled)

    def on_command_result(self, source: str, text: str, result) -> None:
        metadata = result.metadata or {}

        if not result.ok:
            self._status_label.setText(result.message)
        else:
            self._status_label.setText("")

        if "memory_categories" in metadata:
            self._update_category_counts(metadata["memory_categories"])
        if "semantic_memory_hits" in metadata:
            self._update_results_table(metadata["semantic_memory_hits"])
        if "episodes" in metadata:
            self._update_episodes_table(metadata["episodes"])

        # A mutation just succeeded (add/update/move/delete) -- the results
        # table and category counts would otherwise silently show
        # pre-mutation data until the user manually re-searches.
        if result.ok and ("memory_id" in metadata or "deleted_memories" in metadata):
            self.command_requested.emit(_SHOW_CATEGORIES_COMMAND, "memory")
            if self._last_memory_query:
                self.command_requested.emit(f"jarvis търси семантично в паметта {self._last_memory_query}", "memory")

    def _update_category_counts(self, counts: dict) -> None:
        for category, label in self._category_labels.items():
            label.setText(f"{category}: {counts.get(category, 0)}")

    def _update_results_table(self, hits: list) -> None:
        self._results_table.setRowCount(0)
        for hit in hits:
            row = self._results_table.rowCount()
            self._results_table.insertRow(row)
            kind = hit.get("kind", "")
            memory_id = hit.get("id", "")
            kind_item = QTableWidgetItem(kind)
            kind_item.setData(Qt.ItemDataRole.UserRole, {"id": memory_id, "kind": kind})
            self._results_table.setItem(row, 0, kind_item)
            self._results_table.setItem(row, 1, QTableWidgetItem(str(memory_id)))
            self._results_table.setItem(row, 2, QTableWidgetItem(str(hit.get("category", ""))))
            self._results_table.setItem(row, 3, QTableWidgetItem(str(hit.get("score", ""))))
            self._results_table.setItem(row, 4, QTableWidgetItem(str(hit.get("content", ""))))

    def _update_episodes_table(self, episodes: list) -> None:
        self._episodes_table.setRowCount(0)
        for episode in episodes:
            row = self._episodes_table.rowCount()
            self._episodes_table.insertRow(row)
            self._episodes_table.setItem(row, 0, QTableWidgetItem(str(episode.get("source", ""))))
            self._episodes_table.setItem(row, 1, QTableWidgetItem(", ".join(episode.get("topics", []))))
            counts = f"{episode.get('turn_count', 0)} / {episode.get('action_count', 0)}"
            self._episodes_table.setItem(row, 2, QTableWidgetItem(counts))
            self._episodes_table.setItem(row, 3, QTableWidgetItem(str(episode.get("created_at", ""))))
            self._episodes_table.setItem(row, 4, QTableWidgetItem(str(episode.get("summary", ""))))

    def results_row_count(self) -> int:
        return self._results_table.rowCount()

    def episodes_row_count(self) -> int:
        return self._episodes_table.rowCount()
