from __future__ import annotations

from jarvis.audit import AuditRecord
from jarvis.gui.developer_panel import _FILTER_MINUTES_DEFAULT, DeveloperPanel


class _FakeAuditLogger:
    def __init__(self, records: list[AuditRecord] | None = None) -> None:
        self._records = records or []
        self.latest = None
        self.filtered_calls: list[dict] = []
        self.filtered_result: list[AuditRecord] | None = None

    def recent(self, minutes: int, limit: int) -> list[AuditRecord]:
        return list(self._records)[-limit:]

    def latest_trace(self) -> AuditRecord | None:
        return self.latest

    def filtered(self, **kwargs) -> list[AuditRecord]:
        self.filtered_calls.append(kwargs)
        return self.filtered_result if self.filtered_result is not None else list(self._records)


def _record(**overrides) -> AuditRecord:
    defaults = dict(
        timestamp="2026-08-07T12:00:00+00:00",
        raw_text="jarvis отвори facebook",
        intent="apps_or_web.open",
        action="open_target",
        permission="safe",
        requires_confirmation=False,
        confirmed=None,
        ok=True,
        message="Opening https://www.facebook.com",
        error="",
        dry_run=True,
        source="gui_text",
        latency_ms=12.5,
        metadata={},
    )
    defaults.update(overrides)
    return AuditRecord(**defaults)


def test_loads_historical_records_on_construction(qapp):
    audit = _FakeAuditLogger([_record(), _record(raw_text="jarvis увеличи звука", action="volume_up")])
    panel = DeveloperPanel(audit)
    assert panel.row_count() == 2


def test_columns_show_intent_action_permission(qapp):
    audit = _FakeAuditLogger([_record(intent="system.volume_up", action="volume_up", permission="safe")])
    panel = DeveloperPanel(audit)
    assert panel._table.item(0, 3).text() == "system.volume_up"
    assert panel._table.item(0, 4).text() == "volume_up"
    assert panel._table.item(0, 5).text() == "safe"


def test_confirmation_column_shows_not_required(qapp):
    audit = _FakeAuditLogger([_record(requires_confirmation=False)])
    panel = DeveloperPanel(audit)
    assert panel._table.item(0, 6).text() == "not required"


def test_confirmation_column_shows_confirmed(qapp):
    audit = _FakeAuditLogger([_record(requires_confirmation=True, confirmed=True)])
    panel = DeveloperPanel(audit)
    assert panel._table.item(0, 6).text() == "confirmed"


def test_confirmation_column_shows_denied(qapp):
    audit = _FakeAuditLogger([_record(requires_confirmation=True, confirmed=False)])
    panel = DeveloperPanel(audit)
    assert panel._table.item(0, 6).text() == "denied"


def test_result_column_shows_ok_and_fail(qapp):
    audit = _FakeAuditLogger([_record(ok=True), _record(ok=False, error="boom")])
    panel = DeveloperPanel(audit)
    assert panel._table.item(0, 7).text() == "OK"
    assert panel._table.item(1, 7).text() == "FAIL"
    assert panel._table.item(1, 9).text() == "boom"


def test_latency_column_formats_milliseconds(qapp):
    audit = _FakeAuditLogger([_record(latency_ms=42.3)])
    panel = DeveloperPanel(audit)
    assert panel._table.item(0, 8).text() == "42 ms"


def test_latency_column_shows_dash_when_missing(qapp):
    audit = _FakeAuditLogger([_record(latency_ms=None)])
    panel = DeveloperPanel(audit)
    assert panel._table.item(0, 8).text() == "-"


def test_add_live_entry_appends_a_row_from_latest_trace(qapp):
    audit = _FakeAuditLogger([])
    panel = DeveloperPanel(audit)
    assert panel.row_count() == 0

    audit.latest = _record(raw_text="jarvis quiet mode", action="apply_mode")
    panel.add_live_entry("button", "jarvis quiet mode", result=None)

    assert panel.row_count() == 1
    assert panel._table.item(0, 2).text() == "jarvis quiet mode"


def test_add_live_entry_does_nothing_when_no_trace_available(qapp):
    audit = _FakeAuditLogger([])
    panel = DeveloperPanel(audit)
    audit.latest = None
    panel.add_live_entry("button", "jarvis quiet mode", result=None)
    assert panel.row_count() == 0


def test_refresh_button_reloads_from_audit_logger(qapp):
    audit = _FakeAuditLogger([_record()])
    panel = DeveloperPanel(audit)
    assert panel.row_count() == 1

    audit._records.append(_record(raw_text="jarvis провери температурите"))
    panel.refresh()
    assert panel.row_count() == 2


def test_selecting_a_row_shows_its_metadata_as_json(qapp):
    audit = _FakeAuditLogger([_record(metadata={"workflow_steps": [{"tool": "open_url", "status": "ok"}]})])
    panel = DeveloperPanel(audit)
    panel._table.selectRow(0)
    text = panel._metadata_view.toPlainText()
    assert "workflow_steps" in text
    assert "open_url" in text


def test_selecting_a_row_with_no_metadata_shows_a_placeholder(qapp):
    audit = _FakeAuditLogger([_record(metadata={})])
    panel = DeveloperPanel(audit)
    panel._table.selectRow(0)
    assert panel._metadata_view.toPlainText() == "(no metadata)"


def test_selecting_a_row_with_nested_ai_trace_metadata_shows_it(qapp):
    audit = _FakeAuditLogger(
        [_record(metadata={"ai_trace": {"provider": "openai", "model": "gpt-5.6-sol", "usage": {"total_tokens": 42}}})]
    )
    panel = DeveloperPanel(audit)
    panel._table.selectRow(0)
    text = panel._metadata_view.toPlainText()
    assert "ai_trace" in text
    assert "gpt-5.6-sol" in text
    assert "42" in text


def test_selection_changed_is_safe_when_records_list_is_shorter_than_the_stale_row_index(qapp):
    audit = _FakeAuditLogger([_record()])
    panel = DeveloperPanel(audit)
    panel._table.selectRow(0)
    # Simulate a stale selection index surviving a reload that shrank the
    # backing list out from under it.
    panel._records = []
    panel._on_selection_changed()  # must not raise
    assert panel._metadata_view.toPlainText() == ""


def test_apply_filters_calls_audit_logger_filtered_with_form_values(qapp):
    audit = _FakeAuditLogger([_record()])
    panel = DeveloperPanel(audit)

    panel._filter_source.setText("gui_text")
    panel._filter_intent.setText("apps_or_web.open")
    panel._filter_action.setText("open_target")
    panel._filter_permission.setCurrentText("confirm")
    panel._filter_result.setCurrentText("Failed")
    panel._filter_error_type.setCurrentText("not_found")
    panel._filter_recommended_action.setCurrentText("ask_for_another_target_or_search_again")
    panel._filter_minutes.setValue(120)
    panel._filter_limit.setValue(50)

    panel._apply_filters()

    assert len(audit.filtered_calls) == 1
    call = audit.filtered_calls[0]
    assert call["source"] == "gui_text"
    assert call["intent"] == "apps_or_web.open"
    assert call["action"] == "open_target"
    assert call["permission"] == "confirm"
    assert call["ok"] is False
    assert call["error_type"] == "not_found"
    assert call["recommended_action"] == "ask_for_another_target_or_search_again"
    assert call["minutes"] == 120
    assert call["limit"] == 50


def test_apply_filters_permission_any_sends_empty_string(qapp):
    audit = _FakeAuditLogger([_record()])
    panel = DeveloperPanel(audit)
    panel._apply_filters()
    assert audit.filtered_calls[0]["permission"] == ""


def test_apply_filters_result_any_sends_none_for_ok(qapp):
    audit = _FakeAuditLogger([_record()])
    panel = DeveloperPanel(audit)
    panel._apply_filters()
    assert audit.filtered_calls[0]["ok"] is None


def test_apply_filters_result_ok_sends_true(qapp):
    audit = _FakeAuditLogger([_record()])
    panel = DeveloperPanel(audit)
    panel._filter_result.setCurrentText("OK")
    panel._apply_filters()
    assert audit.filtered_calls[0]["ok"] is True


def test_apply_filters_replaces_table_contents(qapp):
    audit = _FakeAuditLogger([_record()])
    audit.filtered_result = [_record(raw_text="jarvis provери температурите"), _record(raw_text="jarvis quiet mode")]
    panel = DeveloperPanel(audit)
    assert panel.row_count() == 1

    panel._apply_filters()

    assert panel.row_count() == 2


def test_clear_filters_resets_form_and_reloads(qapp):
    audit = _FakeAuditLogger([_record()])
    panel = DeveloperPanel(audit)
    panel._filter_source.setText("gui_text")
    panel._filter_permission.setCurrentText("admin")
    panel._filter_minutes.setValue(30)

    panel._clear_filters()

    assert panel._filter_source.text() == ""
    assert panel._filter_permission.currentText() == "Any"
    assert panel._filter_minutes.value() == _FILTER_MINUTES_DEFAULT
    assert panel.row_count() == 1  # reloaded via refresh(), not filtered()


def test_permission_filter_offers_the_four_known_permission_levels(qapp):
    audit = _FakeAuditLogger([])
    panel = DeveloperPanel(audit)
    values = {panel._filter_permission.itemText(i) for i in range(panel._filter_permission.count())}
    assert values == {"Any", "safe", "confirm", "admin", "blocked"}


def test_error_type_filter_accepts_free_text_not_in_the_seed_list(qapp):
    audit = _FakeAuditLogger([_record()])
    panel = DeveloperPanel(audit)
    panel._filter_error_type.setCurrentText("some_future_error_type")
    panel._apply_filters()
    assert audit.filtered_calls[0]["error_type"] == "some_future_error_type"


def test_works_with_the_real_audit_logger(qapp, tmp_path):
    # Sanity check against the real AuditLogger shape, not just a fake.
    from jarvis.audit import AuditLogger
    from jarvis.models import CommandResult

    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    audit.log("jarvis отвори facebook", CommandResult(True, "Opening https://www.facebook.com"), dry_run=True, source="gui_text", latency_ms=8.0)

    panel = DeveloperPanel(audit)
    assert panel.row_count() == 1
    assert panel._table.item(0, 2).text() == "jarvis отвори facebook"
