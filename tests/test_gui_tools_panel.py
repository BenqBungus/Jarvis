from __future__ import annotations

from jarvis.gui.tools_panel import ToolsPanel
from jarvis.tool_registry import ToolParameter, ToolSpec


class _FakeRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._specs = specs

    def list_specs(self) -> list[ToolSpec]:
        return list(self._specs)


def _specs() -> list[ToolSpec]:
    return [
        ToolSpec(name="open_url", description="Open a webpage.", permission="safe", category="web",
                 parameters=(ToolParameter("url", "string", "URL to open."),)),
        ToolSpec(name="restart", description="Restart Windows.", permission="confirm", category="power"),
        ToolSpec(name="disable_internet", description="Disable internet adapters.", permission="admin", category="network"),
        ToolSpec(name="set_volume", description="Set system volume.", permission="safe", category="system",
                 parameters=(
                     ToolParameter("percent", "integer", "Volume percentage."),
                     ToolParameter("display_name", "string", "Optional label.", required=False),
                 )),
    ]


def test_loads_all_specs_from_the_registry(qapp):
    panel = ToolsPanel(_FakeRegistry(_specs()))
    assert panel.tool_count() == 4
    assert panel.visible_row_count() == 4


def test_category_filter_narrows_visible_rows(qapp):
    panel = ToolsPanel(_FakeRegistry(_specs()))
    index = panel._category_filter.findText("power")
    assert index >= 0
    panel._category_filter.setCurrentIndex(index)
    assert panel.visible_row_count() == 1
    assert panel._table.item(0, 0).text() == "restart"


def test_all_category_shows_every_tool(qapp):
    panel = ToolsPanel(_FakeRegistry(_specs()))
    index = panel._category_filter.findText("power")
    panel._category_filter.setCurrentIndex(index)
    all_index = panel._category_filter.findText("All")
    panel._category_filter.setCurrentIndex(all_index)
    assert panel.visible_row_count() == 4


def test_table_columns_show_name_category_permission_description(qapp):
    panel = ToolsPanel(_FakeRegistry(_specs()))
    row_texts = {panel._table.item(row, 0).text(): row for row in range(panel._table.rowCount())}
    row = row_texts["open_url"]
    assert panel._table.item(row, 1).text() == "web"
    assert panel._table.item(row, 2).text() == "safe"
    assert panel._table.item(row, 3).text() == "Open a webpage."


def test_parameters_column_formats_required_and_optional(qapp):
    panel = ToolsPanel(_FakeRegistry(_specs()))
    row_texts = {panel._table.item(row, 0).text(): row for row in range(panel._table.rowCount())}
    row = row_texts["set_volume"]
    parameters_text = panel._table.item(row, 4).text()
    assert "percent (integer)" in parameters_text
    assert "display_name (string, optional)" in parameters_text


def test_parameters_column_shows_none_for_tools_without_parameters(qapp):
    panel = ToolsPanel(_FakeRegistry(_specs()))
    row_texts = {panel._table.item(row, 0).text(): row for row in range(panel._table.rowCount())}
    row = row_texts["restart"]
    assert panel._table.item(row, 4).text() == "(none)"


def test_table_is_read_only(qapp):
    from PySide6.QtWidgets import QAbstractItemView

    panel = ToolsPanel(_FakeRegistry(_specs()))
    assert panel._table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers


def test_works_with_the_real_tool_registry_shape(qapp):
    # Sanity check against the actual build_core_tool_registry() shape,
    # not just a fake -- construct a real ToolRegistry the same way
    # router.py does, without touching router.py itself.
    from jarvis.models import CommandResult
    from jarvis.tool_registry import build_core_tool_registry

    class _StubActions:
        @property
        def local_files(self):
            return self

        @property
        def folder_windows(self):
            return self

        def __getattr__(self, name):
            return lambda *args, **kwargs: CommandResult(True, f"stub:{name}")

    registry = build_core_tool_registry(_StubActions(), ai=None)
    panel = ToolsPanel(registry)
    assert panel.tool_count() > 20  # the real registry has ~30 tools
    assert panel.visible_row_count() == panel.tool_count()
