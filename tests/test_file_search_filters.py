from datetime import datetime
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from jarvis.files import FileSearchService
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "Desktop"
    root.mkdir()
    (root / "Podcast").mkdir()
    (root / "Other").mkdir()
    for name, size, date in [
        ("Podcast/Notes.txt", 10, "2026-09-01T00:00:00"),
        ("Podcast/Report.PDF", 100, "2026-09-02T23:59:59"),
        ("Podcast/Report-old.pdf", 200, "2026-09-03T00:00:00"),
        ("Other/Podcast.txt", 1000, "2026-09-04T12:00:00"),
    ]:
        file = root / name
        file.write_bytes(b"a" * size)
        timestamp = datetime.fromisoformat(date).timestamp()
        os.utime(file, (timestamp, timestamp))
    return FileSearchService(folders={"desktop": root}), root


def names(result):
    assert result.ok, result.message
    return {row["name"] for row in result.metadata["file_results"]}


def test_extension_only_and_kind_filters(library):
    files, _ = library
    assert names(files.search(extension=".PDF")) == {"Report.PDF", "Report-old.pdf"}
    assert names(files.search("podcast", kind="folder")) == {"Podcast"}
    assert names(files.search("podcast", kind="file")) == {"Podcast.txt"}


def test_all_filters_are_combined_and_sizes_are_inclusive(library):
    files, _ = library
    result = files.search("report", extension="pdf", min_size_bytes=100, max_size_bytes=100,
                          modified_after="2026-09-02", modified_before="2026-09-02")
    assert names(result) == {"Report.PDF"}
    row = result.metadata["file_results"][0]
    assert row["size_bytes"] == 100
    assert row["modified_at"].startswith("2026-09-02T23:59:59")
    assert not result.metadata["content_read"]


def test_dates_include_entire_requested_day_not_next_day(library):
    files, _ = library
    assert names(files.search(kind="file", modified_after="2026-09-01", modified_before="2026-09-02")) == {"Notes.txt", "Report.PDF"}


def test_exact_matches_include_extension_and_fuzzy_suggestions_are_explicit(library):
    files, _ = library
    assert names(files.search("Report.PDF", match_mode="exact")) == {"Report.PDF"}
    assert names(files.search("Report", match_mode="exact")) == set()
    result = files.search("podcst", match_mode="fuzzy")
    assert names(result) == {"Podcast", "Podcast.txt"}
    assert all(0.75 <= row["match_score"] < 1 for row in result.metadata["file_results"])
    assert result.metadata["filters"]["match_mode"] == "fuzzy"
    assert "Approximate name matches" in result.message


def test_known_folder_subpath_and_different_case(library):
    files, root = library
    assert names(files.search(extension="txt", root="DESKTOP/Podcast")) == {"Notes.txt"}
    assert files._path("Desktop/Podcast/Notes.txt") == root / "Podcast/Notes.txt"


@pytest.mark.parametrize("arguments", [
    {}, {"query": "x"}, {"extension": "*.pdf"}, {"extension": "pdf,docx"},
    {"kind": "folder", "extension": "pdf"}, {"kind": "folder", "min_size_bytes": 0},
    {"query": "report", "min_size_bytes": -1}, {"query": "report", "max_size_bytes": True},
    {"query": "report", "min_size_bytes": 20, "max_size_bytes": 10},
    {"modified_after": "2026-09-31"}, {"modified_before": "yesterday"},
    {"modified_after": "2026-09-03", "modified_before": "2026-09-02"},
    {"query": "report", "match_mode": "regex"}, {"kind": "program"},
    {"query": "report", "max_entries": 0}, {"query": "report", "timeout": "3"},
    {"query": "report", "timeout": float("nan")}, {"query": None},
])
def test_invalid_filters_fail_without_searching(library, monkeypatch, arguments):
    files, _ = library
    monkeypatch.setattr(os, "scandir", lambda *args: pytest.fail("Invalid filters must not scan"))
    assert not files.search(**arguments).ok


def test_filters_never_read_file_contents_or_open_results(library, monkeypatch):
    files, _ = library
    monkeypatch.setattr(Path, "open", lambda *args, **kw: pytest.fail("No file contents should be read"))
    monkeypatch.setattr(os, "startfile", lambda *args: pytest.fail("No automatic opening"))
    assert names(files.search("report", extension="pdf")) == {"Report.PDF", "Report-old.pdf"}


def test_search_cancelled_and_limited_are_not_complete(library):
    files, _ = library
    files.cancelled = lambda: True
    result = files.search("report")
    assert not result.ok and result.metadata["cancelled"] and result.metadata["partial"]
    files.cancelled = lambda: False
    result = files.search("report", max_entries=1)
    assert result.ok and result.metadata["partial"]
    assert result.metadata["entries_checked"] == 1


def test_excluded_directories_make_scope_partial(library):
    files, root = library
    (root / ".private").mkdir()
    (root / ".private/Report.pdf").write_text("not inspected")
    result = files.search("report")
    assert result.metadata["partial"]
    assert result.metadata["skipped_paths"] == 1
    assert all(".private" not in row["path"] for row in result.metadata["file_results"])


def test_search_rejects_file_as_root(library):
    files, _ = library
    assert not files.search("report", root="Desktop/Podcast/Notes.txt").ok


@pytest.fixture
def router(library):
    files, _ = library
    ai = Mock()
    ai.parse_intent.side_effect = AssertionError("Local search must not use AI")
    safety = SafetyPolicy()
    safety.confirm = Mock(side_effect=AssertionError("Search is read-only"))
    router = CommandRouter(WindowsActions(), safety, ai=ai)
    router.files.folders = files.folders
    return router


@pytest.mark.parametrize("phrase,expected", [
    ("local find files type pdf in Desktop", {"Report.PDF", "Report-old.pdf"}),
    ('jarvis find folders named "Podcast" in Desktop', {"Podcast"}),
    ('jarvis find files matching "podcst" in Desktop', {"Podcast.txt"}),
    ("local find files type pdf after 2026-09-02 before 2026-09-02", {"Report.PDF"}),
    ('local find files type pdf min 0.1 KB max 100B in "Desktop/Podcast"', {"Report.PDF"}),
])
def test_local_filter_commands_execute_real_search(router, phrase, expected):
    result = router.handle(phrase)
    assert names(result) == expected
    assert result.action == "search_local_files"
    assert result.permission == "safe"
    router.ai.parse_intent.assert_not_called()


@pytest.mark.parametrize("phrase", [
    'find files named "unterminated', 'find files named "report" named "other"',
    "find files type pdf delete all", "find files min nonsense", "find files min 0.5 B",
    "find files in", "find folders type pdf",
])
def test_invalid_local_syntax_is_not_silently_ignored(router, phrase):
    assert not router.handle("local " + phrase).ok
    router.ai.parse_intent.assert_not_called()


def test_tool_schema_exposes_filters_and_realtime_uses_same_search(router):
    from jarvis.tool_registry import ToolCall
    from jarvis.realtime import realtime_tool_schemas
    spec = router.tools.get("search_local_files").spec
    parameters = {param.name for param in spec.parameters}
    assert {"extension", "kind", "modified_after", "modified_before", "min_size_bytes", "max_size_bytes", "match_mode"} <= parameters
    voice_schema = next(schema for schema in realtime_tool_schemas(router.tools) if schema["name"] == "search_local_files")
    assert set(voice_schema["parameters"]["properties"]) == parameters
    result = router.tools.execute(ToolCall("search_local_files", {"extension": "pdf", "max_size_bytes": 150}))
    assert names(result) == {"Report.PDF"}
