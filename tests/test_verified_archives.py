import struct
import zipfile
from unittest.mock import Mock

import pytest

from jarvis.local_file_actions import LocalFileActions
from jarvis.models import CommandResult
from jarvis.tool_registry import ToolCall, ToolParameter, ToolRegistry, ToolSpec
from jarvis.workflows import WorkflowRunner, WorkflowStep


@pytest.fixture
def archives(tmp_path):
    root = tmp_path / "documents"
    source = root / "Source"
    source.mkdir(parents=True)
    (source / "Empty").mkdir()
    (source / "notes.txt").write_bytes(b"original notes")
    return LocalFileActions(folders={"documents": root}), root


def make_zip(path, members=()):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, content in members:
            archive.writestr(name, content)


def assert_uncertain(result):
    assert not result.ok
    assert result.metadata["outcome_uncertain"]
    assert result.metadata["change_completed"] is None
    assert not result.metadata["completion_verified"]
    assert not result.metadata["retryable"]


@pytest.mark.parametrize("content", [b"", b"hello", b"a" * (128 * 1024 + 7)],
                         ids=["empty", "text", "multiple_chunks"])
def test_archive_roundtrip_verifies_contents_and_empty_directories(archives, content):
    files, root = archives
    name = "\u0411\u0435\u043b\u0435\u0436\u043a\u0438.txt"
    (root / "Source" / name).write_bytes(content)
    created = files.create_zip("Documents/Source", "Documents/bundle.zip")
    assert created.ok, created.message
    assert created.metadata["completion_verified"]
    assert created.metadata["archive_observation"]["crc_matches"]
    assert created.metadata["archive_observation"]["sha256_matches"]
    extracted = files.extract_zip("Documents/bundle.zip", "Documents/Restored")
    assert extracted.ok, extracted.message
    assert extracted.metadata["completion_verified"]
    assert extracted.metadata["extraction_observation"]["sha256_matches"]
    assert (root / "Restored/Source/Empty").is_dir()
    assert (root / "Restored/Source" / name).read_bytes() == content
    assert not list(root.glob(".jarvis-*"))


def test_empty_zip_and_implicit_directories_are_verified(archives):
    files, root = archives
    make_zip(root / "empty.zip")
    result = files.extract_zip("Documents/empty.zip", "Documents/EmptyOutput")
    assert result.ok and result.metadata["completion_verified"]
    assert result.metadata["extraction_observation"]["paths_including_root"] == 1
    make_zip(root / "implicit.zip", [("one/two/notes.txt", b"abc")])
    result = files.extract_zip("Documents/implicit.zip", "Documents/ImplicitOutput")
    assert result.ok and result.metadata["completion_verified"]
    assert result.metadata["extraction_observation"]["paths_including_root"] == 4
    assert (root / "ImplicitOutput/one/two/notes.txt").read_bytes() == b"abc"


@pytest.mark.parametrize("change", ["contents", "addition"])
def test_source_mutation_before_zip_publish_is_not_success(archives, monkeypatch, change):
    files, root = archives
    original = files._copy_stream
    def changing(*args, **kwargs):
        copied = original(*args, **kwargs)
        path = root / "Source" / ("notes.txt" if change == "contents" else "added.txt")
        path.write_bytes(b"user changes")
        return copied
    monkeypatch.setattr(files, "_copy_stream", changing)
    result = files.create_zip("Documents/Source", "Documents/bundle.zip")
    assert not result.ok and not result.metadata["retryable"]
    assert not (root / "bundle.zip").exists()
    assert not list(root.glob(".jarvis-*"))


@pytest.mark.parametrize("corruption", ["unreadable", "valid_wrong_contents", "extra_member"])
def test_published_zip_is_reopened_and_checked_not_deleted(archives, monkeypatch, corruption):
    files, root = archives
    publish = files._publish
    def changed(stage, target, deadline):
        publish(stage, target, deadline)
        if corruption == "unreadable":
            target.write_bytes(b"not a zip")
        elif corruption == "valid_wrong_contents":
            make_zip(target, [("Source/", b""), ("Source/Empty/", b""),
                              ("Source/notes.txt", b"x" * len(b"original notes"))])
        else:
            with zipfile.ZipFile(target, "a") as archive:
                archive.writestr("extra.txt", b"extra")
    monkeypatch.setattr(files, "_publish", changed)
    result = files.create_zip("Documents/Source", "Documents/bundle.zip")
    assert_uncertain(result)
    assert (root / "bundle.zip").exists()
    assert (root / "Source/notes.txt").read_bytes() == b"original notes"


@pytest.mark.parametrize("change", ["same_size", "missing_file", "extra_file", "missing_directory"])
def test_published_extraction_tree_is_checked_and_preserved(archives, monkeypatch, change):
    files, root = archives
    assert files.create_zip("Documents/Source", "Documents/bundle.zip").ok
    publish = files._publish
    def changed(stage, target, deadline):
        publish(stage, target, deadline)
        notes = target / "Source/notes.txt"
        if change == "same_size":
            notes.write_bytes(b"x" * notes.stat().st_size)
        elif change == "missing_file":
            notes.unlink()
        elif change == "extra_file":
            (target / "extra.txt").write_bytes(b"extra")
        else:
            (target / "Source/Empty").rmdir()
    monkeypatch.setattr(files, "_publish", changed)
    result = files.extract_zip("Documents/bundle.zip", "Documents/Restored")
    assert_uncertain(result)
    assert (root / "Restored").is_dir()
    assert (root / "bundle.zip").exists()


def test_zip_changed_while_extracting_is_not_published(archives, monkeypatch):
    files, root = archives
    make_zip(root / "bundle.zip", [("notes.txt", b"notes")])
    original = files._copy_stream
    def changing(*args, **kwargs):
        copied = original(*args, **kwargs)
        with (root / "bundle.zip").open("ab") as writer:
            writer.write(b"concurrent edit")
        return copied
    monkeypatch.setattr(files, "_copy_stream", changing)
    result = files.extract_zip("Documents/bundle.zip", "Documents/Restored")
    assert not result.ok and not result.metadata["retryable"]
    assert not (root / "Restored").exists()
    assert (root / "bundle.zip").read_bytes().endswith(b"concurrent edit")


@pytest.mark.parametrize("operation", ["create", "extract"])
def test_staging_verification_failure_never_publishes(archives, monkeypatch, operation):
    files, root = archives
    if operation == "create":
        monkeypatch.setattr(files, "_verify_archive", Mock(side_effect=zipfile.BadZipFile("CRC fixture")))
        result = files.create_zip("Documents/Source", "Documents/output.zip")
        destination = root / "output.zip"
    else:
        make_zip(root / "bundle.zip", [("notes.txt", b"notes")])
        monkeypatch.setattr(files, "_verify_extracted", Mock(side_effect=OSError("read failure fixture")))
        result = files.extract_zip("Documents/bundle.zip", "Documents/Restored")
        destination = root / "Restored"
    assert not result.ok and not result.metadata["retryable"]
    assert not destination.exists()
    assert not list(root.glob(".jarvis-*"))


@pytest.mark.parametrize("reason", ["cancelled", "deadline"])
def test_stop_during_postpublish_verification_preserves_output(archives, monkeypatch, reason):
    files, root = archives
    publish = files._publish
    def stopped(stage, target, deadline):
        publish(stage, target, deadline)
        if reason == "cancelled":
            files.cancelled = lambda: True
        else:
            monkeypatch.setattr("jarvis.local_file_actions.time.monotonic", lambda: deadline + 1)
    monkeypatch.setattr(files, "_publish", stopped)
    result = files.create_zip("Documents/Source", "Documents/bundle.zip")
    assert_uncertain(result)
    assert (root / "bundle.zip").exists()


def test_dry_run_never_writes_or_claims_verification(archives):
    files, root = archives
    make_zip(root / "bundle.zip", [("notes.txt", b"notes")])
    files.dry_run = True
    for result in (files.create_zip("Documents/Source", "Documents/preview.zip"),
                   files.extract_zip("Documents/bundle.zip", "Documents/Restored")):
        assert result.ok and result.metadata["dry_run"]
        assert not result.metadata["completion_verified"] and not result.metadata["change_completed"]
        assert WorkflowRunner.completion_status(result.ok, result.metadata) == "dry_run"
    assert not (root / "preview.zip").exists() and not (root / "Restored").exists()
    assert not list(root.glob(".jarvis-*"))


def test_implicit_directory_count_is_bounded_before_writing(archives, monkeypatch):
    files, root = archives
    make_zip(root / "bundle.zip", [("one/two/three/notes.txt", b"notes")])
    monkeypatch.setattr("jarvis.local_file_actions.MAX_ENTRIES", 4)
    result = files.extract_zip("Documents/bundle.zip", "Documents/Restored")
    assert not result.ok and "implicit directories" in result.message
    assert not (root / "Restored").exists()


def test_excessive_nesting_is_rejected_before_writing(archives):
    files, root = archives
    make_zip(root / "bundle.zip", [("a/" * 64 + "notes.txt", b"notes")])
    result = files.extract_zip("Documents/bundle.zip", "Documents/Restored")
    assert not result.ok and "nesting" in result.message
    assert not (root / "Restored").exists()


def test_zip64_locator_is_rejected_before_zipfile_allocation(archives, monkeypatch):
    files, root = archives
    make_zip(root / "bundle.zip")
    content = (root / "bundle.zip").read_bytes()
    locator = struct.pack("<4sLQL", b"PK\x06\x07", 0, 0, 1)
    (root / "bundle.zip").write_bytes(locator + content)
    opener = Mock(side_effect=AssertionError("ZIP64 must be rejected before allocation"))
    monkeypatch.setattr("jarvis.local_file_actions.zipfile.ZipFile", opener)
    result = files.extract_zip("Documents/bundle.zip", "Documents/Restored")
    assert not result.ok and "ZIP64" in result.message
    opener.assert_not_called()


@pytest.mark.parametrize("operation", ["create", "extract"])
def test_destination_race_never_overwrites_an_existing_output(archives, monkeypatch, operation):
    files, root = archives
    make_zip(root / "bundle.zip", [("notes.txt", b"notes")])
    publish = files._publish
    def raced(stage, target, deadline):
        target.write_bytes(b"user data")
        publish(stage, target, deadline)
    monkeypatch.setattr(files, "_publish", raced)
    if operation == "create":
        result = files.create_zip("Documents/Source", "Documents/output.zip")
        target = root / "output.zip"
    else:
        result = files.extract_zip("Documents/bundle.zip", "Documents/Restored")
        target = root / "Restored"
    assert_uncertain(result)
    assert target.read_bytes() == b"user data"
    assert not list(root.glob(".jarvis-*"))


@pytest.mark.parametrize("operation", ["create", "extract"])
@pytest.mark.parametrize("reason,flag", [("cancelled", "cancelled"), ("deadline", "budget_exhausted")])
def test_prepublication_stop_has_structured_status(archives, monkeypatch, operation, reason, flag):
    files, root = archives
    make_zip(root / "bundle.zip", [("notes.txt", b"notes")])
    if reason == "cancelled":
        files.cancelled = lambda: True
    else:
        monkeypatch.setattr("jarvis.local_file_actions.MAX_SECONDS", -1)
    if operation == "create":
        result = files.create_zip("Documents/Source", "Documents/output.zip")
        target = root / "output.zip"
    else:
        result = files.extract_zip("Documents/bundle.zip", "Documents/Restored")
        target = root / "Restored"
    assert not result.ok and result.metadata[flag]
    assert not result.metadata["retryable"]
    assert not target.exists()


def archive_registry(files):
    registry = ToolRegistry()
    parameters = (ToolParameter("source", "string", "Source"), ToolParameter("destination", "string", "Destination"))
    registry.register(ToolSpec("archive", "Archive", permission="confirm", parameters=parameters), files.create_zip)
    registry.register(ToolSpec("extract", "Extract", permission="confirm", parameters=parameters), files.extract_zip)
    return registry


def test_real_archive_workflow_records_verified_evidence(archives):
    files, root = archives
    registry = archive_registry(files)
    approvals = []
    result = WorkflowRunner(registry).run("archive roundtrip", [
        WorkflowStep("archive", ToolCall("archive", {"source": "Documents/Source", "destination": "Documents/bundle.zip"})),
        WorkflowStep("extract", ToolCall("extract", {"source": "Documents/bundle.zip", "destination": "Documents/Restored"})),
    ], confirm=lambda spec, call: approvals.append(spec.name) or True)
    assert result.ok and approvals == ["archive", "extract"]
    assert [item["status"] for item in result.metadata["completion_evidence"]] == ["verified", "verified"]
    assert (root / "Restored/Source/notes.txt").read_bytes() == b"original notes"


def test_uncertain_archive_stops_workflow_without_retry(archives, monkeypatch):
    files, root = archives
    make_zip(root / "bundle.zip", [("notes.txt", b"notes")])
    verify = files._verify_extracted
    def fail_after_publish(target, *args):
        if target == root / "Restored":
            raise OSError("postcheck denied")
        return verify(target, *args)
    monkeypatch.setattr(files, "_verify_extracted", fail_after_publish)
    extract = Mock(side_effect=files.extract_zip)
    monkeypatch.setattr(files, "extract_zip", extract)
    registry = archive_registry(files)
    later = Mock(return_value=CommandResult(True, "later"))
    registry.register(ToolSpec("later", "Later"), later)
    result = WorkflowRunner(registry).run("extract", [
        WorkflowStep("extract", ToolCall("extract", {"source": "Documents/bundle.zip", "destination": "Documents/Restored"})),
        WorkflowStep("later", ToolCall("later")),
    ], confirm=lambda *args: True, max_retries=3, retryable_tools={"extract"})
    assert not result.ok and result.metadata["outcome_uncertain"]
    assert result.metadata["completion_evidence"][0]["status"] == "not_verified"
    extract.assert_called_once()
    later.assert_not_called()
    assert (root / "Restored/notes.txt").read_bytes() == b"notes"
