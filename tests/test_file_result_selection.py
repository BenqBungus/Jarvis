import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from jarvis.files import FileSearchService
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


@pytest.fixture
def files(tmp_path, monkeypatch):
    folder = tmp_path / "Documents"
    folder.mkdir()
    (folder / "Alpha.txt").write_text("alpha")
    (folder / "Beta.txt").write_text("beta")
    opened = []
    monkeypatch.setattr(os, "startfile", lambda path: opened.append(path))
    return FileSearchService(folders={"documents": folder}), folder, opened


def test_selection_matches_displayed_order_and_reports_launch_not_visible_window(files):
    service, folder, opened = files
    search = service.search(kind="file")
    assert search.metadata["selection_available"]
    assert [row["ordinal"] for row in search.metadata["file_results"]] == [1, 2]
    assert service.show_results().metadata["file_results"] == search.metadata["file_results"]
    assert opened == []
    result = service.open_result(2, search.metadata["search_id"])
    assert result.ok
    assert opened == [str(folder / "Beta.txt")]
    assert result.metadata["verification"] == "launch_request_accepted"
    assert result.metadata["window_verified"] is False


@pytest.mark.parametrize("number", [0, -1, 3, True, "2", None])
def test_invalid_ordinals_never_open(files, number):
    service, _, opened = files
    search = service.search(kind="file")
    assert not service.open_result(number, search.metadata["search_id"]).ok
    assert opened == []


def test_wrong_or_newer_search_id_cannot_select_a_different_file(files):
    service, _, opened = files
    first = service.search(kind="file")
    assert not service.open_result(1, "invented").ok
    second = service.search("Beta")
    assert not service.open_result(1, first.metadata["search_id"]).ok
    assert service.open_result(1, second.metadata["search_id"]).ok
    assert len(opened) == 1 and opened[0].endswith("Beta.txt")


@pytest.mark.parametrize("kind", ["invalid", "empty", "cancelled"])
def test_unsuccessful_search_invalidates_previous_selection(files, kind):
    service, _, opened = files
    old = service.search(kind="file")
    if kind == "invalid":
        service.search(extension="*.pdf")
    elif kind == "empty":
        service.search("no match anywhere")
    else:
        service.cancelled = lambda: True
        service.search(kind="file")
    assert not service.show_results().ok
    assert not service.open_result(1, old.metadata["search_id"]).ok
    assert opened == []


def test_expired_results_require_new_search(files, monkeypatch):
    service, _, opened = files
    search = service.search(kind="file")
    monkeypatch.setattr("jarvis.files.time.monotonic", lambda: service._saved_at + 300)
    assert not service.show_results().ok
    assert not service.open_result(1, search.metadata["search_id"]).ok
    assert opened == []


def test_replacement_file_is_not_opened(files):
    service, folder, opened = files
    search = service.search("Alpha.txt")
    (folder / "Alpha.txt").rename(folder / "Saved.txt")
    (folder / "Alpha.txt").write_text("replacement")
    result = service.open_result(1, search.metadata["search_id"])
    assert not result.ok and "replaced" in result.message
    assert opened == []


def test_missing_file_and_changed_parent_are_not_followed(files):
    service, folder, opened = files
    search = service.search("Alpha.txt")
    folder.rename(folder.with_name("Moved"))
    assert not service.open_result(1, search.metadata["search_id"]).ok
    assert opened == []


def test_executable_found_by_search_remains_blocked(files):
    service, folder, opened = files
    (folder / "App.exe").write_bytes(b"not a program")
    search = service.search(extension="exe")
    result = service.open_result(1, search.metadata["search_id"])
    assert not result.ok and result.permission == "blocked"
    assert opened == []


def test_cancel_and_dry_run_never_launch(files):
    service, _, opened = files
    search = service.search(kind="file")
    service.cancelled = lambda: True
    assert not service.open_result(1, search.metadata["search_id"]).ok
    service.cancelled = lambda: False
    service.dry_run = True
    assert service.open_result(1, search.metadata["search_id"]).ok
    assert opened == []


def test_output_metadata_cannot_mutate_selection(files):
    service, folder, opened = files
    search = service.search(kind="file")
    search.metadata["file_results"][0]["path"] = str(folder / "Beta.txt")
    shown = service.show_results()
    shown.metadata["file_results"][0]["path"] = str(folder / "Beta.txt")
    assert service.open_result(1, search.metadata["search_id"]).ok
    assert opened == [str(folder / "Alpha.txt")]


def test_previous_process_results_do_not_survive_restart(files):
    service, folder, opened = files
    search = service.search(kind="file")
    restarted = FileSearchService(folders={"documents": folder})
    assert not restarted.show_results().ok
    assert not restarted.open_result(1, search.metadata["search_id"]).ok
    assert opened == []


def test_new_search_during_old_traversal_wins(files):
    service, _, _ = files
    nested = []
    def cancel_check():
        if not nested:
            nested.append(None)
            nested[0] = service.search("Beta.txt")
        return False
    service.cancelled = cancel_check
    old = service.search(kind="file")
    assert old.ok and not old.metadata["selection_available"]
    assert service.show_results().metadata["search_id"] == nested[0].metadata["search_id"]
    assert not service.open_result(1, old.metadata["search_id"]).ok


@pytest.fixture
def router(files):
    service, _, _ = files
    ai = Mock()
    ai.parse_intent.side_effect = AssertionError("Local selection does not use AI")
    safety = SafetyPolicy()
    safety.confirm = Mock(side_effect=AssertionError("Approved document opening is safe"))
    router = CommandRouter(WindowsActions(), safety, ai=ai)
    router.files.folders = service.folders
    assert router.handle("local find files type txt").ok
    return router


@pytest.mark.parametrize("phrase", ["jarvis open file result 2", "local open the second file result",
                                    "local отвори втория файл"])
def test_local_selection_routes_use_the_observed_id(router, files, phrase):
    _, folder, opened = files
    result = router.handle(phrase)
    assert result.ok and result.action == "open_file_result"
    assert opened == [str(folder / "Beta.txt")]
    router.ai.parse_intent.assert_not_called()


@pytest.mark.parametrize("phrase", ["local open the second result", "jarvis open result 2", "local отвори втория резултат"])
def test_ambiguous_file_versus_web_selection_asks_before_opening(router, files, phrase):
    result = router.handle(phrase)
    assert not result.ok and result.metadata["clarification_required"]
    assert files[2] == []


def test_web_selection_without_file_context_is_not_intercepted(files):
    service, _, _ = files
    router = CommandRouter(WindowsActions(dry_run=True), SafetyPolicy())
    assert router.local_commands.resource_command("open the second result") is None


def test_recent_file_command_is_not_confused_with_a_search_result(router):
    assert router.local_commands.resource_command("отвори последния файл") is None
    assert router.local_commands.resource_command("open the last file") is None


def test_realtime_schema_requires_both_observed_selection_fields(router):
    from jarvis.realtime import realtime_tool_schemas
    spec = next(item for item in realtime_tool_schemas(router.tools) if item["name"] == "open_file_result")
    assert set(spec["parameters"]["required"]) == {"ordinal", "search_id"}
