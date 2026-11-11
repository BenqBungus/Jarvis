from unittest.mock import Mock

import pytest

from jarvis.local_file_actions import LocalFileActions
from jarvis.models import CommandResult
from jarvis.safety import SafetyPolicy
from jarvis.router import CommandRouter
from jarvis.windows_actions import WindowsActions
from jarvis.tool_registry import ToolCall, ToolParameter, ToolRegistry, ToolSpec
from jarvis.user_settings import JarvisSettings
from jarvis.workflows import AdaptiveWorkflowDecision, WorkflowRunner, WorkflowStep


def test_inspection_reads_only_metadata_and_handles_missing(tmp_path, monkeypatch):
    target = tmp_path / "Report.txt"
    target.write_bytes(b"example")
    files = LocalFileActions(folders={"documents": tmp_path})
    monkeypatch.setattr(type(target), "open", Mock(side_effect=AssertionError("Do not read contents")))
    result = files.inspect_local_path("Documents/Report.txt")
    assert result.ok and result.metadata["exists"]
    assert result.metadata["kind"] == "file" and result.metadata["size_bytes"] == 7
    assert not result.metadata["content_read"]
    assert result.metadata["modified_at"].endswith("+00:00")
    folder = files.inspect_local_path("Documents")
    assert folder.ok and folder.metadata["kind"] == "folder"
    assert folder.metadata["size_bytes"] is None
    missing = files.inspect_local_path("Documents/Absent.txt")
    assert missing.ok and missing.metadata["exists"] is False


@pytest.mark.parametrize("path", ["Documents/.ssh/item", "Documents/.env", r"\\server\share\file",
                                 r"C:\Windows\win.ini", "Documents/file.txt:stream"])
def test_inspection_does_not_bypass_protected_path_rules(tmp_path, path):
    assert not LocalFileActions(folders={"documents": tmp_path}).inspect_local_path(path).ok


def test_inspection_rejects_links(tmp_path, monkeypatch):
    import stat
    from types import SimpleNamespace
    files = LocalFileActions(folders={"documents": tmp_path})
    original = type(tmp_path).lstat
    def attributes(path, *args, **kwargs):
        if path.name == "linked":
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(type(tmp_path), "lstat", attributes)
    assert not files.inspect_local_path("Documents/linked/file.txt").ok


def test_real_folder_and_utf8_creation_have_bounded_postconditions(tmp_path):
    files = LocalFileActions(folders={"documents": tmp_path})
    folder = files.create_local_folder("Documents/Work")
    assert folder.ok and folder.metadata["completion_verified"]
    assert folder.metadata["verification_scope"] == "existence_and_type"
    existing = files.create_local_folder("Documents/Work")
    assert existing.ok and existing.metadata["completion_verified"] and not existing.metadata["created"]
    text = "caf\u00e9\n"
    file = files.create_local_file("Documents/Work/Plan.txt", text)
    assert file.ok and file.metadata["completion_verified"]
    assert file.metadata["path_observation"]["size_bytes"] == len(text.encode("utf-8"))
    assert file.metadata["verification_scope"] == "existence_type_and_size"


def test_dry_run_never_claims_creation_verified(tmp_path):
    files = LocalFileActions(dry_run=True, folders={"documents": tmp_path})
    for result in (files.create_local_folder("Documents/New"), files.create_local_file("Documents/New.txt")):
        assert result.ok and result.metadata["dry_run"]
        assert not result.metadata["completion_verified"]
    assert not list(tmp_path.iterdir())


def test_failed_postcheck_does_not_retry_or_erase_created_file(tmp_path, monkeypatch):
    files = LocalFileActions(folders={"documents": tmp_path})
    monkeypatch.setattr(files, "inspect_local_path", lambda path: CommandResult(False, "Access denied"))
    result = files.create_local_file("Documents/Keep.txt", "keep")
    assert not result.ok and result.metadata["outcome_uncertain"]
    assert (tmp_path / "Keep.txt").read_text() == "keep"


def registry_for(first):
    registry = ToolRegistry()
    operation = Mock(return_value=first)
    later = Mock(return_value=CommandResult(True, "later"))
    registry.register(ToolSpec("close_app", "Close one app", permission="confirm"), operation)
    registry.register(ToolSpec("later", "Another step"), later)
    return registry, operation, later


@pytest.mark.parametrize("metadata", [{"exit_verified": False, "close_requested": True},
                                      {"window_closed": False}, {"completion_verified": False},
                                      {"outcome_uncertain": True}])
@pytest.mark.parametrize("adaptive", [False, True])
def test_uncertain_success_stops_workflow_without_repeating(metadata, adaptive):
    registry, operation, later = registry_for(CommandResult(True, "Request accepted", metadata=metadata))
    runner = WorkflowRunner(registry)
    audit = Mock()
    runner.on_step_result = audit
    if adaptive:
        decide = Mock(side_effect=[AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("close_app")),
                                   AdaptiveWorkflowDecision("finish", message="Everything is done")])
        result = runner.run_adaptive("test", "close then do more", decide_next=decide, confirm=lambda *a: True)
        assert decide.call_count == 1
    else:
        result = runner.run("test", [WorkflowStep("close", ToolCall("close_app")),
                                     WorkflowStep("more", ToolCall("later"))],
                            confirm=lambda *a: True, max_retries=3, retryable_tools={"close_app"})
    assert not result.ok
    operation.assert_called_once()
    later.assert_not_called()
    assert result.metadata["completion_evidence"][0]["status"] == "not_verified"
    assert not audit.call_args.args[1].ok
    assert result.metadata["workflow_recovery"]["recommended_action"] == "inspect_result_or_ask_user_do_not_repeat"


def test_verified_close_can_proceed():
    registry, _, later = registry_for(CommandResult(True, "Exited", metadata={"exit_verified": True}))
    result = WorkflowRunner(registry).run("test", [WorkflowStep("close", ToolCall("close_app")),
                                         WorkflowStep("more", ToolCall("later"))], confirm=lambda *a: True)
    assert result.ok and later.call_count == 1
    assert [item["status"] for item in result.metadata["completion_evidence"]] == ["verified", "reported"]


def test_adaptive_cannot_finish_without_evidence_except_explicit_preview():
    for preview in (False, True):
        result = WorkflowRunner(ToolRegistry()).run_adaptive("test", "create my folder",
            decide_next=lambda _: AdaptiveWorkflowDecision("finish", message="Done"), preview=preview)
        assert result.ok is preview
        assert ("Dry-run preview" in result.message) is preview


@pytest.mark.parametrize("phrase", ["inspect path", "check path", "file info", "folder info"])
def test_local_and_voice_tool_can_inspect_without_confirmation(tmp_path, monkeypatch, phrase):
    actions = WindowsActions()
    actions.local_files.folders = {"documents": tmp_path}
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("Read-only tool must not prompt")))
    router = CommandRouter(actions, SafetyPolicy(), settings=JarvisSettings())
    result = router.local_commands.resource_command(f'{phrase} "Documents/Missing.txt"')
    assert result.ok and result.metadata["exists"] is False
    spec = router.tools.get("inspect_local_path").spec
    assert spec.permission == "safe" and not spec.requires_confirmation


def test_real_multi_step_creation_is_verified_without_cloud(tmp_path, monkeypatch):
    actions = WindowsActions()
    actions.local_files.folders = {"documents": tmp_path}
    router = CommandRouter(actions, SafetyPolicy(), settings=JarvisSettings(safety={"full_access_local": True}))
    monkeypatch.setattr("builtins.input", Mock(side_effect=AssertionError("Full access should preauthorize")))
    decisions = iter([
        AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("create_local_folder", {"path": "Documents/Project"})),
        AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("create_local_file", {"path": "Documents/Project/Notes.txt", "content": "Meeting notes"})),
        AdaptiveWorkflowDecision("finish", message="Project folder and notes created"),
    ])
    result = router.workflow_runner.run_adaptive("project", "create folder and notes", decide_next=lambda _: next(decisions),
        confirm=lambda spec, call: router.safety.confirm("Run adaptive workflow step: " + spec.name, "Test fixture"))
    assert result.ok
    assert (tmp_path / "Project/Notes.txt").read_text() == "Meeting notes"
    assert [item["status"] for item in result.metadata["completion_evidence"]] == ["verified", "verified"]
