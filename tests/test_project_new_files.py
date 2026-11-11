import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jarvis.models import CommandResult
from jarvis.project_changes import ProjectChanges
from jarvis.project_repair import ProjectRepair
from jarvis.project_workspace import ProjectReader, ProjectWorkspace


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "main.py").write_text("value = 1\n")
    changes = ProjectChanges(ProjectWorkspace(root))
    changes.enabled = True
    reader = ProjectReader(changes.workspace, changes=changes)
    reader.list_files(".")
    reader.read_file("main.py")
    return root, changes, reader


def propose(changes, reader, *, mixed=False):
    edits = [{"path": "main.py", "old_text": "value = 1", "new_text": "value = 2"}] if mixed else []
    return changes.propose(reader, edits, "Add a fixture module.",
                           [{"path": "helper.py", "content": "answer = 42\n"}])


def test_mixed_patch_preview_apply_and_durable_undo(project):
    root, changes, reader = project
    preview = propose(changes, reader, mixed=True)
    assert preview["created_files"] == ["helper.py"]
    assert "--- /dev/null" in preview["diff"] and "+answer = 42" in preview["diff"]
    assert not (root / "helper.py").exists()
    assert not changes.apply(preview["proposal_id"]).ok
    assert changes.apply(preview["proposal_id"], confirmed=True).ok
    assert (root / "helper.py").read_text() == "answer = 42\n"
    assert (root / "main.py").read_text() == "value = 2\n"
    assert not list(root.glob(".jarvis-edit-*"))
    fresh = ProjectChanges(ProjectWorkspace(root))
    assert fresh.undo_available()
    assert not fresh.undo().ok
    assert fresh.undo(confirmed=True).ok
    assert not (root / "helper.py").exists()
    assert (root / "main.py").read_text() == "value = 1\n"


def test_missing_destination_is_not_a_read_scope_escape(project):
    root, changes, reader = project
    with pytest.raises(FileNotFoundError):
        changes.workspace.path("helper.py")
    assert changes.workspace.path("helper.py", allow_missing_leaf=True) == root / "helper.py"
    with pytest.raises(FileNotFoundError):
        changes.workspace.path("missing/helper.py", allow_missing_leaf=True)
    with pytest.raises(ValueError):
        changes.workspace.path("../helper.py", allow_missing_leaf=True)


@pytest.mark.parametrize("path,content", [
    ("../outside.py", "pass"), ("missing/child.py", "pass"), ("config.json", "{}"),
    ("CON.py", "pass"), ("helper.py ", "pass"), ("helper.py.", "pass"),
    ("hello?.py", "pass"), ("helper.py:ads", "pass"), ("helper.exe", "binary"),
    ("helper.py", "def broken(:"), ("data.json", "{broken}"),
    ("helper.txt", "password = fictional-private"), ("helper.txt", "binary\x00"),
])
def test_bad_new_file_is_rejected_without_writes(project, path, content):
    root, changes, reader = project
    result = reader.execute("propose_project_edits", {"edits": [], "explanation": "Fixture.",
        "new_files": [{"path": path, "content": content}]})
    assert "error" in result
    assert changes.preview() is None
    assert sorted(p.name for p in root.iterdir()) == ["main.py"]


def test_list_destination_required_and_existing_files_not_creations(project):
    root, changes, reader = project
    fresh_reader = ProjectReader(changes.workspace, changes=changes)
    with pytest.raises(ValueError, match="List the destination"):
        propose(changes, fresh_reader)
    with pytest.raises(ValueError, match="already exists"):
        changes.propose(reader, [], "Fixture", [{"path": "main.py", "content": "value = 2"}])


def test_new_destination_appearing_after_preview_is_preserved(project):
    root, changes, reader = project
    preview = propose(changes, reader, mixed=True)
    (root / "helper.py").write_text("user = 99\n")
    result = changes.apply(preview["proposal_id"], confirmed=True)
    assert not result.ok
    assert (root / "helper.py").read_text() == "user = 99\n"
    assert (root / "main.py").read_text() == "value = 1\n"
    assert not list(root.glob(".jarvis-edit-*"))


def test_atomic_create_never_overwrites_even_identical_racing_destination(project, monkeypatch):
    root, changes, reader = project
    preview = propose(changes, reader)
    publish = os.link
    def racing_publish(source, target):
        target.write_text("answer = 42\n")
        publish(source, target)
    monkeypatch.setattr("jarvis.project_changes.os.link", racing_publish)
    result = changes.apply(preview["proposal_id"], confirmed=True)
    assert not result.ok
    assert (root / "helper.py").read_text() == "answer = 42\n"
    assert result.metadata["recovery_needed"] == ["helper.py"]


def test_failure_after_creation_rolls_back_own_changes(project, monkeypatch):
    root, changes, reader = project
    preview = propose(changes, reader, mixed=True)
    create = changes._create
    def fail_after_publish(*args):
        create(*args)
        raise OSError("fixture failure after publish")
    monkeypatch.setattr(changes, "_create", fail_after_publish)
    result = changes.apply(preview["proposal_id"], confirmed=True)
    assert not result.ok and not result.metadata["recovery_needed"]
    assert not (root / "helper.py").exists()
    assert (root / "main.py").read_text() == "value = 1\n"


@pytest.mark.parametrize("replace_identity", [False, True])
def test_undo_preserves_modified_or_replaced_created_file(project, replace_identity):
    root, changes, reader = project
    preview = propose(changes, reader, mixed=True)
    assert changes.apply(preview["proposal_id"], confirmed=True).ok
    created = root / "helper.py"
    if replace_identity:
        replacement = root / "replacement.py"
        replacement.write_bytes(created.read_bytes())
        os.replace(replacement, created)
    else:
        created.write_text("answer = 100\n")
    assert not changes.undo(confirmed=True).ok
    assert created.exists()
    assert (root / "main.py").read_text() == "value = 2\n"


def test_undo_accepts_already_deleted_created_file(project):
    root, changes, reader = project
    preview = propose(changes, reader, mixed=True)
    assert changes.apply(preview["proposal_id"], confirmed=True).ok
    (root / "helper.py").unlink()
    assert changes.undo(confirmed=True).ok
    assert (root / "main.py").read_text() == "value = 1\n"


def test_empty_file_and_existing_subfolder(project):
    root, changes, reader = project
    (root / "modules").mkdir()
    reader.list_files("modules")
    preview = changes.propose(reader, [], "Create empty fixture module.", [{"path": "modules/empty.py", "content": ""}])
    assert "new empty file" in preview["diff"]
    assert changes.apply(preview["proposal_id"], confirmed=True).ok
    assert (root / "modules/empty.py").read_bytes() == b""
    assert changes.undo(confirmed=True).ok
    assert (root / "modules").is_dir() and not (root / "modules/empty.py").exists()


def test_duplicate_case_and_six_file_limit(project):
    root, changes, reader = project
    for files in ([{"path": "HELPER.py", "content": ""}, {"path": "helper.py", "content": ""}],
                  [{"path": f"helper{i}.py", "content": ""} for i in range(7)]):
        with pytest.raises(ValueError):
            changes.propose(reader, [], "Fixture", files)
        assert changes.preview() is None


def test_tampered_creation_journal_cannot_escape_or_change_identity_shape(project):
    root, changes, reader = project
    preview = propose(changes, reader)
    assert changes.apply(preview["proposal_id"], confirmed=True).ok
    journal_path = root / ".jarvis-undo.json"
    original = json.loads(journal_path.read_text())
    for field, value in (("path", "../outside.py"), ("created_identity", [True, 1]), ("after_sha256", "z" * 64)):
        tampered = json.loads(json.dumps(original))
        tampered["entries"][0][field] = value
        journal_path.write_text(json.dumps(tampered))
        assert not changes.undo_available()
        assert not changes.undo(confirmed=True).ok
    assert (root / "helper.py").exists()


def test_tool_loop_proposes_new_module_but_never_creates_it(project):
    from jarvis.vision.project_analysis import analyze_project
    root, changes, _ = project
    reader = ProjectReader(changes.workspace, changes=changes)
    client = Mock()
    def tool(name, arguments, call_id):
        return SimpleNamespace(status="completed", output_text="", output=[SimpleNamespace(
            type="function_call", name=name, arguments=json.dumps(arguments), call_id=call_id)])
    client.responses.create.side_effect = [
        tool("list_project_files", {"path": "."}, "list"),
        tool("propose_project_edits", {"edits": [], "explanation": "Fixture module.",
            "new_files": [{"path": "helper.py", "content": "answer = 42\n"}]}, "preview"),
        SimpleNamespace(status="completed", output_text="Review the new module.", output=[]),
    ]
    assert analyze_project(client, model="gpt-5.6-sol", content=[], instructions="", reader=reader).output_text
    assert changes.preview()["created_files"] == ["helper.py"]
    assert not (root / "helper.py").exists()


def test_real_repair_fixes_missing_module_with_reviewed_creation(project):
    root, changes, reader = project
    (root / "test_feature.py").write_text("from helper import answer\ndef test_answer():\n    assert answer == 42\n")
    def diagnose(evidence, fresh_reader):
        assert "ModuleNotFoundError" in evidence
        fresh_reader.list_files(".")
        propose(changes, fresh_reader)
        return CommandResult(True, "Review missing module fixture.")
    session = ProjectRepair(changes, diagnose, profile="pytest", runtime=sys.executable)
    try:
        assert session.start(confirmed=True).ok
        assert session.state == "awaiting_review" and not (root / "helper.py").exists()
        assert session.approve(session.proposal_id, confirmed=True).ok
        assert session.state == "passed" and session.check_count == 2
        assert changes.undo(confirmed=True).ok
        assert not (root / "helper.py").exists()
    finally:
        session.cancel()
