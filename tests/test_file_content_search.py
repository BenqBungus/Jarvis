import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from jarvis.content_search import TextContentSearch
from jarvis.files import FileSearchService
from jarvis.realtime import realtime_tool_schemas
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.tool_registry import ToolCall
from jarvis.windows_actions import WindowsActions


@pytest.fixture
def library(tmp_path, monkeypatch):
    root = tmp_path / "Documents"
    root.mkdir()
    (root / "Nested").mkdir()
    (root / "Notes.txt").write_text("My Gaming Mouse review", encoding="utf-8")
    (root / "Nested/Review.MD").write_text("A GAMING MOUSE comparison", encoding="utf-8-sig")
    (root / "Table.csv").write_text("item,price\ngaming mouse,40", encoding="utf-16")
    (root / "Unrelated.txt").write_text("A different topic", encoding="utf-8")
    opened = Mock()
    monkeypatch.setattr(os, "startfile", opened)
    return FileSearchService(folders={"documents": root}), root, opened


def names(result):
    assert result.ok, result.message
    return {row["name"] for row in result.metadata["file_results"]}


def test_literal_case_insensitive_recursive_search_and_private_result_cache(library):
    files, _, opened = library
    result = files.search(root="Documents", content="gaming mouse")
    assert names(result) == {"Notes.txt", "Review.MD", "Table.csv"}
    assert result.metadata["content_read"]
    assert result.metadata["search_kind"] == "content"
    assert result.metadata["content_files_read"] == 4
    assert "My Gaming Mouse review" not in str(result)
    assert "comparison" not in str(result)
    assert not result.metadata["partial"]
    opened.assert_not_called()
    shown = files.show_results()
    assert shown.metadata["search_kind"] == "content"
    assert not shown.metadata["content_read"]
    assert shown.metadata["file_results"] == result.metadata["file_results"]
    assert files.open_result(1, result.metadata["search_id"]).ok
    opened.assert_called_once()


def test_content_and_name_filters_are_combined(library):
    files, _, _ = library
    assert names(files.search(query="notes", root="Documents", content="gaming mouse", extension="txt")) == {"Notes.txt"}
    assert names(files.search(root="Documents/Nested", content="gaming mouse")) == {"Review.MD"}
    assert names(files.search(root="Documents", content="gaming.*mouse")) == set()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "utf-16", "utf-16-be"])
def test_unicode_and_supported_encodings(library, encoding):
    files, root, _ = library
    text = "\u041f\u0440\u043e\u0446\u0435\u0441\u043e\u0440"
    data = text.encode(encoding)
    if encoding == "utf-16-be":
        data = b"\xfe\xff" + data
    (root / "Bulgarian.txt").write_bytes(data)
    assert names(files.search(root="Documents", content=text.lower())) == {"Bulgarian.txt"}


@pytest.mark.parametrize("arguments", [
    {"content": "mouse"}, {"content": "mouse", "root": " "},
    {"content": "", "root": "Documents"}, {"content": "x", "root": "Documents"},
    {"content": "x" * 201, "root": "Documents"}, {"content": False, "root": "Documents"},
    {"content": "mouse", "root": "Documents", "kind": "folder"},
    {"content": "mouse", "root": "Documents", "extension": "pdf"},
    {"content": "mouse", "root": "Documents", "extension": "docx"},
])
def test_invalid_content_search_does_not_scan_and_invalidates_old_selection(library, monkeypatch, arguments):
    files, _, _ = library
    old = files.search(query="notes")
    monkeypatch.setattr(os, "scandir", lambda *a: pytest.fail("Must not scan"))
    assert not files.search(**arguments).ok
    assert not files.open_result(1, old.metadata["search_id"]).ok


@pytest.mark.parametrize("name", [".env.txt", "credentials.txt", "api-key.txt", "settings.md", "secrets/report.txt",
                                      ".ssh/report.txt", "AppData/report.txt", "Windows/report.txt"])
def test_sensitive_paths_are_never_read_or_traversed(library, monkeypatch, name):
    files, root, _ = library
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("gaming mouse", encoding="utf-8")
    original = Path.open

    def guarded(path, *args, **kwargs):
        assert path != target, "Sensitive file was read"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded)
    result = files.search(root="Documents", content="gaming mouse")
    assert names(result) == {"Notes.txt", "Review.MD", "Table.csv"}
    assert result.metadata["partial"]
    if target.parent != root:
        assert not files.search(root=str(target.parent), content="gaming mouse").ok


def test_unsupported_binary_oversized_and_detected_secret_documents_are_skipped(library):
    files, root, _ = library
    for name, data in {"Binary.txt": b"gaming mouse\x00", "Unknown.txt": b"gaming mouse\xff",
                       "PDF.pdf": b"gaming mouse", "Report.txt": b"gaming mouse password=example-only-password",
                       "Large.txt": b"gaming mouse" + b"x" * TextContentSearch.MAX_FILE_BYTES}.items():
        (root / name).write_bytes(data)
    result = files.search(root="Documents", content="gaming mouse")
    assert names(result) == {"Notes.txt", "Review.MD", "Table.csv"}
    assert result.metadata["skipped_paths"] == 5
    assert result.metadata["partial"]
    assert "example-only-password" not in str(result)


def test_chunk_boundary_and_file_size_boundary(library):
    files, root, _ = library
    payload = b"x" * 65530 + b"gaming mouse"
    payload += b"x" * (TextContentSearch.MAX_FILE_BYTES - len(payload))
    (root / "Boundary.txt").write_bytes(payload)
    result = files.search(query="boundary", root="Documents", content="gaming mouse")
    assert names(result) == {"Boundary.txt"}
    assert result.metadata["content_bytes_read"] == TextContentSearch.MAX_FILE_BYTES


def test_total_budget_stops_with_partial_results(library, monkeypatch):
    files, _, _ = library
    monkeypatch.setattr(TextContentSearch, "MAX_TOTAL_BYTES", 64)
    result = files.search(root="Documents", content="gaming mouse")
    assert result.ok and result.metadata["partial"]
    assert result.metadata["content_bytes_read"] <= 64


def test_deadline_during_read_reports_partial(library, monkeypatch):
    files, _, _ = library
    original = TextContentSearch.matches

    def expired(reader, path, attrs):
        reader.deadline = 0
        return original(reader, path, attrs)

    monkeypatch.setattr(TextContentSearch, "matches", expired)
    result = files.search(root="Documents", content="gaming mouse")
    assert result.ok and result.metadata["partial"]
    assert not result.metadata["content_read"]
    assert not result.metadata["selection_available"]


def test_unreadable_file_is_not_reported_as_complete(library, monkeypatch):
    files, root, _ = library
    original = Path.open

    def denied(path, *args, **kwargs):
        if path == root / "Notes.txt":
            raise PermissionError("Access denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied)
    result = files.search(root="Documents", content="gaming mouse")
    assert names(result) == {"Review.MD", "Table.csv"}
    assert result.metadata["partial"]


def test_explicit_subfolder_does_not_read_siblings(library, monkeypatch):
    files, root, _ = library
    original = Path.open

    def scoped(path, *args, **kwargs):
        assert path.parent == root / "Nested"
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", scoped)
    assert names(files.search(root="Documents/Nested", content="gaming mouse")) == {"Review.MD"}


def test_drive_and_home_roots_are_rejected_without_enumeration(library, monkeypatch):
    files, root, _ = library
    monkeypatch.setattr(os, "scandir", lambda *a: pytest.fail("Too broad a content scope"))
    assert not files.search(root=root.anchor, content="gaming mouse").ok
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: root))
    assert not files.search(root="Documents", content="gaming mouse").ok


def test_name_search_after_content_search_clears_content_origin(library, monkeypatch):
    files, _, _ = library
    assert files.search(root="Documents", content="gaming mouse").ok
    monkeypatch.setattr(Path, "open", lambda *a, **kw: pytest.fail("No implicit content reading"))
    result = files.search(query="notes")
    assert names(result) == {"Notes.txt"}
    assert not result.metadata["content_read"]
    assert files.show_results().metadata["search_kind"] == "filename"


def test_cancellation_during_read_disables_selection(library, monkeypatch):
    files, _, _ = library
    original = TextContentSearch.matches

    def cancelling(reader, path, attrs):
        files.cancelled = lambda: True
        reader.cancel_requested = files.cancelled
        return original(reader, path, attrs)

    monkeypatch.setattr(TextContentSearch, "matches", cancelling)
    result = files.search(root="Documents", content="gaming mouse")
    assert not result.ok and result.metadata["cancelled"]
    assert not result.metadata["selection_available"]
    assert not files.show_results().ok


def test_replaced_file_between_stat_and_open_is_not_searched(library, monkeypatch):
    files, root, _ = library
    original = Path.open

    def replace(path, *args, **kwargs):
        if path == root / "Notes.txt" and args == ("rb",):
            path.unlink()
            with original(path, "wb") as stream:
                stream.write(b"gaming mouse in replacement")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", replace)
    result = files.search(query="notes", root="Documents", content="gaming mouse")
    assert names(result) == set()
    assert result.metadata["partial"]


@pytest.fixture
def router(library):
    files, _, _ = library
    safety = SafetyPolicy()
    safety.confirm = Mock(side_effect=AssertionError("Read-only explicit search"))
    ai = Mock()
    ai.parse_intent.side_effect = AssertionError("No cloud parsing")
    router = CommandRouter(WindowsActions(), safety, ai=ai)
    router.files.folders = files.folders
    return router


@pytest.mark.parametrize("phrase", [
    'Jarvis, find files containing "gaming mouse" in Documents',
    'local search files in Documents containing "gaming mouse"',
    'Jarvis, find files containing gaming mouse in Documents',
])
def test_local_commands_search_real_contents_without_cloud(router, phrase):
    assert names(router.handle(phrase)) == {"Notes.txt", "Review.MD", "Table.csv"}
    router.ai.parse_intent.assert_not_called()


def test_local_content_search_requires_scope_and_preserves_filters(router):
    result = router.handle('local find files containing "gaming mouse"')
    assert not result.ok and result.metadata["clarification_required"]
    assert names(router.handle('local find files containing "gaming mouse" in Documents type txt named Notes')) == {"Notes.txt"}
    assert not router.handle('local find files containing "mouse" containing "other" in Documents').ok


def test_realtime_schema_and_execution_share_content_search(router):
    schema = next(item for item in realtime_tool_schemas(router.tools) if item["name"] == "search_local_files")
    assert "content" in schema["parameters"]["properties"]
    result = router.tools.execute(ToolCall("search_local_files", {"content": "gaming mouse", "root": "Documents"}))
    assert names(result) == {"Notes.txt", "Review.MD", "Table.csv"}
    assert result.permission == "safe"
