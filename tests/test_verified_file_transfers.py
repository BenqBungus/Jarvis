from unittest.mock import Mock
import os

import pytest

from jarvis.local_file_actions import LocalFileActions
from jarvis.models import CommandResult
from jarvis.rollback import RollbackManager
from jarvis.tool_registry import ToolCall, ToolParameter, ToolRegistry, ToolSpec
from jarvis.workflows import WorkflowRunner, WorkflowStep


@pytest.fixture
def transfers(tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "source.txt").write_bytes(b"source content")
    return LocalFileActions(folders={"documents": root}), root


@pytest.mark.parametrize("content", [b"", b"hello\n", b"a" * (128 * 1024 + 3)], ids=["empty", "text", "multiple_chunks"])
def test_copy_verifies_actual_destination_bytes(transfers, content):
    files, root = transfers
    (root / "source.txt").write_bytes(content)
    result = files.copy_local_file("Documents/source.txt", "Documents/copy.txt")
    assert result.ok and result.metadata["completion_verified"]
    assert result.metadata["copy_observation"]["sha256_matches"]
    assert result.metadata["copy_observation"]["size_bytes"] == len(content)
    assert WorkflowRunner.completion_status(result.ok, result.metadata) == "verified"
    assert (root / "copy.txt").read_bytes() == content
    assert not list(root.glob(".jarvis-*"))


def test_source_changed_mid_copy_is_not_published(transfers, monkeypatch):
    files, root = transfers
    original = files._copy_stream
    def changing(*args, **kwargs):
        copied = original(*args, **kwargs)
        (root / "source.txt").write_bytes(b"user changed source")
        return copied
    monkeypatch.setattr(files, "_copy_stream", changing)
    result = files.copy_local_file("Documents/source.txt", "Documents/copy.txt")
    assert not result.ok and not result.metadata["retryable"]
    assert not (root / "copy.txt").exists()
    assert (root / "source.txt").read_bytes() == b"user changed source"


def test_same_size_corruption_after_publish_is_not_success_or_auto_deleted(transfers, monkeypatch):
    files, root = transfers
    publish = files._publish
    def corrupted(stage, destination, deadline):
        publish(stage, destination, deadline)
        destination.write_bytes(b"x" * len(b"source content"))
    monkeypatch.setattr(files, "_publish", corrupted)
    result = files.copy_local_file("Documents/source.txt", "Documents/copy.txt")
    assert not result.ok and result.metadata["outcome_uncertain"]
    assert result.metadata["change_completed"] is None
    assert not result.metadata["completion_verified"] and not result.metadata["retryable"]
    assert (root / "copy.txt").exists()
    assert (root / "source.txt").read_bytes() == b"source content"


def test_copy_postcheck_error_keeps_destination_and_stops_workflow(transfers, monkeypatch):
    files, root = transfers
    monkeypatch.setattr(files, "_verify_copy", Mock(side_effect=OSError("fixture read denied")))
    registry = ToolRegistry()
    copy = Mock(side_effect=files.copy_local_file)
    later = Mock(return_value=CommandResult(True, "later"))
    registry.register(ToolSpec("copy", "Copy", permission="confirm", parameters=(
        ToolParameter("source", "string", "Source"), ToolParameter("destination", "string", "Destination"))), copy)
    registry.register(ToolSpec("later", "Later"), later)
    result = WorkflowRunner(registry).run("transfer", [
        WorkflowStep("copy", ToolCall("copy", {"source": "Documents/source.txt", "destination": "Documents/copy.txt"})),
        WorkflowStep("later", ToolCall("later")),
    ], confirm=lambda *args: True, max_retries=4, retryable_tools={"copy"})
    assert not result.ok
    copy.assert_called_once()
    later.assert_not_called()
    assert result.metadata["completion_evidence"][0]["status"] == "not_verified"
    assert result.metadata["outcome_uncertain"]
    assert (root / "copy.txt").read_bytes() == b"source content"


def test_move_and_restore_have_identity_evidence(transfers):
    files, root = transfers
    moved = files.move_local_path("Documents/source.txt", "Documents/moved.txt")
    assert moved.ok and moved.metadata["completion_verified"]
    assert moved.metadata["move_observation"]["destination_identity_matches"]
    assert moved.metadata["move_observation"]["source_absent"]
    entry = RollbackManager().peek()
    restored = files.restore_move(entry.payload)
    assert restored.ok and restored.metadata["completion_verified"]
    assert (root / "source.txt").exists() and not (root / "moved.txt").exists()


def test_noop_move_does_not_report_success_or_register_undo(transfers, monkeypatch):
    files, root = transfers
    monkeypatch.setattr(files, "_publish", lambda *args: None)
    result = files.move_local_path("Documents/source.txt", "Documents/moved.txt")
    assert not result.ok and result.metadata["outcome_uncertain"]
    assert not RollbackManager().load()
    assert (root / "source.txt").exists()


def test_replaced_move_destination_is_not_verified(transfers, monkeypatch):
    files, root = transfers
    publish = files._publish
    def replaced(stage, destination, deadline):
        publish(stage, destination, deadline)
        replacement = root / "replacement.txt"
        replacement.write_bytes(destination.read_bytes())
        os.replace(replacement, destination)
    monkeypatch.setattr(files, "_publish", replaced)
    result = files.move_local_path("Documents/source.txt", "Documents/moved.txt")
    assert not result.ok and result.metadata["outcome_uncertain"]
    assert not RollbackManager().load()
    assert (root / "moved.txt").exists()


def test_dry_run_transfer_is_not_verified(transfers):
    files, root = transfers
    files.dry_run = True
    for result in (files.copy_local_file("Documents/source.txt", "Documents/copy.txt"),
                   files.move_local_path("Documents/source.txt", "Documents/moved.txt")):
        assert result.ok and result.metadata["dry_run"]
        assert not result.metadata["completion_verified"]
        assert WorkflowRunner.completion_status(result.ok, result.metadata) == "dry_run"
    assert sorted(p.name for p in root.iterdir()) == ["source.txt"]


def test_real_copy_then_move_workflow_records_two_verified_steps(transfers):
    files, root = transfers
    registry = ToolRegistry()
    parameters = (ToolParameter("source", "string", "Source"), ToolParameter("destination", "string", "Destination"))
    registry.register(ToolSpec("copy", "Copy", permission="confirm", parameters=parameters), files.copy_local_file)
    registry.register(ToolSpec("move", "Move", permission="confirm", parameters=parameters), files.move_local_path)
    approvals = []
    def confirm(spec, call):
        approvals.append(spec.name)
        return True
    result = WorkflowRunner(registry).run("organize fixture", [
        WorkflowStep("Copy fixture", ToolCall("copy", {"source": "Documents/source.txt", "destination": "Documents/copy.txt"})),
        WorkflowStep("Move fixture", ToolCall("move", {"source": "Documents/copy.txt", "destination": "Documents/final.txt"})),
    ], confirm=confirm)
    assert result.ok and approvals == ["copy", "move"]
    assert [item["status"] for item in result.metadata["completion_evidence"]] == ["verified", "verified"]
    assert (root / "final.txt").read_bytes() == (root / "source.txt").read_bytes()
    assert not (root / "copy.txt").exists()
