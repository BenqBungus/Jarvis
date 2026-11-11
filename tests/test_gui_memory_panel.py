from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from jarvis.gui.memory_panel import MemoryPanel
from jarvis.models import CommandResult


def _ok(metadata: dict | None = None, message: str = "ok") -> CommandResult:
    return CommandResult(True, message, metadata=metadata or {})


def _fail(message: str = "boom") -> CommandResult:
    return CommandResult(False, message, error=message)


# --- Search --------------------------------------------------------------------


def test_search_button_emits_semantic_search_command(qapp):
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append((text, source)))

    panel._search_input.setText("browser preference")
    panel._on_search()

    assert received == [("jarvis търси семантично в паметта browser preference", "memory")]


def test_search_on_enter_key_emits_the_same_command(qapp):
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append((text, source)))

    panel._search_input.setText("gaming mouse")
    panel._search_input.returnPressed.emit()

    assert received == [("jarvis търси семантично в паметта gaming mouse", "memory")]


def test_empty_search_does_not_emit(qapp):
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append(True))
    panel._on_search()
    assert received == []


# --- Bootstrap -------------------------------------------------------------------


def test_bootstrap_emits_category_counts_and_episodes_commands(qapp):
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append((text, source)))

    panel.bootstrap()

    assert received == [
        ("jarvis покажи категории памет", "memory"),
        ("jarvis покажи епизодична памет", "memory"),
    ]


def test_all_dispatched_commands_use_the_memory_source(qapp):
    # app.py's on_result_ready special-cases source="memory" to skip
    # history/speech -- every command_requested emission from this panel
    # must use it, or bootstrap()/search would get spoken out loud.
    panel = MemoryPanel()
    sources = []
    panel.command_requested.connect(lambda text, source: sources.append(source))

    panel.bootstrap()
    panel._search_input.setText("x")
    panel._on_search()
    panel._add_content_input.setText("remember this")
    panel._on_add()

    assert all(source == "memory" for source in sources)
    assert len(sources) == 4


# --- Category counts + results table ----------------------------------------------


def test_category_counts_populate_from_memory_categories_metadata(qapp):
    panel = MemoryPanel()
    counts = {"general": 5, "preference": 2, "project": 0, "device": 0, "game": 1, "website": 0, "routine": 0}
    panel.on_command_result("memory", "jarvis покажи категории памет", _ok({"memory_categories": counts}))
    assert panel._category_labels["general"].text() == "general: 5"
    assert panel._category_labels["game"].text() == "game: 1"
    assert panel._category_labels["routine"].text() == "routine: 0"


def test_results_table_populates_from_semantic_memory_hits(qapp):
    panel = MemoryPanel()
    hits = [
        {"kind": "long_term", "id": "7", "content": "likes Opera GX", "score": 0.9, "category": "preference"},
        {"kind": "episode", "id": "uuid-1", "content": "talked about browsers", "score": 0.5, "category": ""},
    ]
    panel.on_command_result("memory", "jarvis търси семантично в паметта browser", _ok({"semantic_memory_hits": hits}))
    assert panel.results_row_count() == 2
    assert panel._results_table.item(0, 4).text() == "likes Opera GX"
    assert panel._results_table.item(1, 0).text() == "episode"


def test_long_term_row_selection_enables_mutation_buttons(qapp):
    panel = MemoryPanel()
    hits = [{"kind": "long_term", "id": "7", "content": "likes Opera GX", "score": 0.9, "category": "preference"}]
    panel.on_command_result("memory", "search", _ok({"semantic_memory_hits": hits}))

    panel._results_table.selectRow(0)

    assert panel._edit_button.isEnabled() is True
    assert panel._move_button.isEnabled() is True
    assert panel._delete_button.isEnabled() is True
    assert panel._selected_memory_id == "7"


def test_episode_row_selection_disables_mutation_buttons(qapp):
    panel = MemoryPanel()
    hits = [{"kind": "episode", "id": "uuid-1", "content": "talked about browsers", "score": 0.5, "category": ""}]
    panel.on_command_result("memory", "search", _ok({"semantic_memory_hits": hits}))

    panel._results_table.selectRow(0)

    assert panel._edit_button.isEnabled() is False
    assert panel._move_button.isEnabled() is False
    assert panel._delete_button.isEnabled() is False


def test_fresh_panel_starts_with_mutation_buttons_disabled(qapp):
    panel = MemoryPanel()
    assert panel._edit_button.isEnabled() is False
    assert panel._move_button.isEnabled() is False
    assert panel._delete_button.isEnabled() is False


def test_reloading_results_with_no_matches_disables_mutation_buttons(qapp):
    panel = MemoryPanel()
    hits = [{"kind": "long_term", "id": "7", "content": "x", "score": 0.9, "category": "general"}]
    panel.on_command_result("memory", "search", _ok({"semantic_memory_hits": hits}))
    panel._results_table.selectRow(0)
    assert panel._edit_button.isEnabled() is True

    panel.on_command_result("memory", "search again", _ok({"semantic_memory_hits": []}))

    assert panel._edit_button.isEnabled() is False


# --- Episodes tab ------------------------------------------------------------------


def test_episodes_tab_populates_from_episodes_metadata(qapp):
    panel = MemoryPanel()
    episodes = [
        {
            "id": "uuid-1",
            "summary": "Discussed favorite browser.",
            "source": "conversation",
            "topics": ["browser", "opera"],
            "turn_count": 4,
            "action_count": 0,
            "created_at": "2026-08-07T12:00:00+00:00",
            "metadata": {},
        }
    ]
    panel.on_command_result("memory", "jarvis покажи епизодична памет", _ok({"episodes": episodes}))
    assert panel.episodes_row_count() == 1
    assert panel._episodes_table.item(0, 0).text() == "conversation"
    assert "browser" in panel._episodes_table.item(0, 1).text()
    assert panel._episodes_table.item(0, 4).text() == "Discussed favorite browser."


def test_episode_search_with_query_emits_search_command(qapp):
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append(text))
    panel._episode_search_input.setText("browser")
    panel._on_episode_search()
    assert received == ["jarvis търси в епизодичната памет browser"]


def test_episode_search_with_no_query_emits_the_bare_listing_command(qapp):
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append(text))
    panel._on_episode_search()
    assert received == ["jarvis покажи епизодична памет"]


# --- Add ---------------------------------------------------------------------------


def test_add_emits_the_verified_correct_categorized_remember_phrasing(qapp):
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append(text))

    panel._add_category_combo.setCurrentText("preference")
    panel._add_content_input.setText("favorite browser is Opera GX")
    panel._on_add()

    assert received == ["jarvis запомни като preference: favorite browser is Opera GX"]


def test_add_clears_the_content_field_after_dispatch(qapp):
    panel = MemoryPanel()
    panel.command_requested.connect(lambda text, source: None)
    panel._add_content_input.setText("something")
    panel._on_add()
    assert panel._add_content_input.text() == ""


def test_add_with_empty_content_does_not_emit(qapp):
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append(True))
    panel._on_add()
    assert received == []


def test_add_category_combo_offers_only_the_seven_valid_categories(qapp):
    panel = MemoryPanel()
    values = {panel._add_category_combo.itemText(i) for i in range(panel._add_category_combo.count())}
    assert values == {"general", "preference", "project", "device", "game", "website", "routine"}
    assert not panel._add_category_combo.isEditable()


# --- Edit / Move / Delete -----------------------------------------------------------


def _select_long_term_row(panel: MemoryPanel, memory_id: str = "7", content: str = "likes Opera GX") -> None:
    hits = [{"kind": "long_term", "id": memory_id, "content": content, "score": 0.9, "category": "preference"}]
    panel.on_command_result("memory", "search", _ok({"semantic_memory_hits": hits}))
    panel._results_table.selectRow(0)


def test_edit_emits_id_addressed_update_command(qapp):
    panel = MemoryPanel()
    _select_long_term_row(panel, memory_id="7")
    received = []
    panel.command_requested.connect(lambda text, source: received.append(text))

    panel._edit_content_input.setText("likes Opera GX and Firefox")
    panel._on_edit()

    assert received == ["jarvis промени памет #7 на likes Opera GX and Firefox"]


def test_edit_with_no_selection_does_not_emit(qapp):
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append(True))
    panel._edit_content_input.setText("x")
    panel._on_edit()
    assert received == []


def test_move_emits_id_addressed_category_command(qapp):
    panel = MemoryPanel()
    _select_long_term_row(panel, memory_id="7")
    received = []
    panel.command_requested.connect(lambda text, source: received.append(text))

    panel._move_category_combo.setCurrentText("website")
    panel._on_move()

    assert received == ["jarvis сложи памет #7 в категория website"]


def test_delete_shows_confirmation_before_dispatching(qapp, monkeypatch):
    panel = MemoryPanel()
    _select_long_term_row(panel, memory_id="7", content="likes Opera GX")
    asked = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *a, **k: asked.append(True) or QMessageBox.StandardButton.Yes),
    )
    received = []
    panel.command_requested.connect(lambda text, source: received.append(text))

    panel._on_delete()

    assert asked == [True]
    assert received == ["jarvis забрави likes Opera GX"]


def test_delete_does_not_dispatch_when_declined(qapp, monkeypatch):
    panel = MemoryPanel()
    _select_long_term_row(panel, memory_id="7", content="likes Opera GX")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    received = []
    panel.command_requested.connect(lambda text, source: received.append(text))

    panel._on_delete()

    assert received == []


def test_delete_with_no_selection_does_not_show_a_dialog(qapp, monkeypatch):
    panel = MemoryPanel()
    asked = []
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(True) or QMessageBox.StandardButton.Yes)
    )
    panel._on_delete()
    assert asked == []


# --- Refresh after mutation ----------------------------------------------------------


def test_successful_mutation_re_issues_category_counts_and_last_search(qapp):
    panel = MemoryPanel()
    panel._search_input.setText("opera")
    panel._on_search()  # sets _last_memory_query
    received = []
    panel.command_requested.connect(lambda text, source: received.append(text))

    panel.on_command_result("memory", "jarvis запомни като preference: likes Opera GX", _ok({"memory_id": 9}))

    assert received == [
        "jarvis покажи категории памет",
        "jarvis търси семантично в паметта opera",
    ]


def test_successful_delete_re_issues_category_counts(qapp):
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append(text))

    panel.on_command_result("memory", "jarvis забрави x", _ok({"deleted_memories": 1}))

    assert received == ["jarvis покажи категории памет"]


def test_a_plain_search_result_does_not_trigger_a_re_search_loop(qapp):
    # semantic_memory_hits alone (no memory_id/deleted_memories) means this
    # was just a search result, not a mutation -- must not recurse.
    panel = MemoryPanel()
    received = []
    panel.command_requested.connect(lambda text, source: received.append(text))

    panel.on_command_result("memory", "jarvis търси семантично в паметта x", _ok({"semantic_memory_hits": []}))

    assert received == []


# --- Failure feedback ----------------------------------------------------------------


def test_failed_result_shows_message_in_status_label(qapp):
    panel = MemoryPanel()
    panel.on_command_result("memory", "jarvis забрави nonexistent", _fail("I did not find a memory matching: nonexistent"))
    assert "did not find" in panel._status_label.text()


def test_successful_result_clears_the_status_label(qapp):
    panel = MemoryPanel()
    panel.on_command_result("memory", "x", _fail("boom"))
    assert panel._status_label.text() != ""
    panel.on_command_result("memory", "y", _ok())
    assert panel._status_label.text() == ""
