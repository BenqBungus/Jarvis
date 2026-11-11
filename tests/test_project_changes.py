import json
import os
import sys
import threading
from pathlib import Path
from unittest.mock import Mock

import pytest

from jarvis.project_workspace import ProjectWorkspace, ProjectReader
from jarvis.project_changes import ProjectChanges
from jarvis.project_checks import ProjectChecks


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "one.py").write_bytes(b"value = 1\r\n")
    (root / "two.py").write_text("other = 2\n", encoding="utf-8")
    workspace = ProjectWorkspace(root)
    changes = ProjectChanges(workspace)
    changes.enabled = True
    reader = ProjectReader(workspace, changes=changes)
    reader.read_file("one.py")
    reader.read_file("two.py")
    return root, workspace, changes, reader


def propose(changes, reader):
    return changes.propose(reader, [
        {"path": "one.py", "old_text": "value = 1", "new_text": "value = 3"},
        {"path": "two.py", "old_text": "other = 2", "new_text": "other = 4"},
    ], "Update the two fixture values.")


def test_multifile_preview_approval_apply_and_durable_undo(source):
    root, workspace, changes, reader = source
    preview = propose(changes, reader)
    assert "-value = 1" in preview["diff"] and "+other = 4" in preview["diff"]
    assert (root / "one.py").read_bytes() == b"value = 1\r\n"
    assert not changes.apply(preview["proposal_id"]).ok
    result = changes.apply(preview["proposal_id"], confirmed=True)
    assert result.ok and result.metadata["tests_run"] is False
    assert (root / "one.py").read_bytes() == b"value = 3\r\n"
    assert (root / "two.py").read_text() == "other = 4\n"
    assert not changes.preview()
    fresh = ProjectChanges(ProjectWorkspace(root))
    assert fresh.undo_available()
    assert not fresh.undo().ok
    assert fresh.undo(confirmed=True).ok
    assert (root / "one.py").read_bytes() == b"value = 1\r\n"
    assert not fresh.undo_available()


def test_conflicting_source_prevents_all_writes(source):
    root, workspace, changes, reader = source
    preview = propose(changes, reader)
    (root / "two.py").write_text("other = 200\n")
    result = changes.apply(preview["proposal_id"], confirmed=True)
    assert not result.ok
    assert (root / "one.py").read_bytes() == b"value = 1\r\n"
    assert (root / "two.py").read_text() == "other = 200\n"


def test_undo_does_not_overwrite_newer_edits(source):
    root, workspace, changes, reader = source
    preview = propose(changes, reader)
    assert changes.apply(preview["proposal_id"], confirmed=True).ok
    (root / "two.py").write_text("other = 1000\n")
    assert not changes.undo(confirmed=True).ok
    assert (root / "one.py").read_bytes() == b"value = 3\r\n"
    assert (root / "two.py").read_text() == "other = 1000\n"


def test_partial_write_failure_restores_already_replaced_file(source, monkeypatch):
    root, workspace, changes, reader = source
    preview = propose(changes, reader)
    original = changes._replace
    def replace(path, expected, replacement):
        if path == "two.py":
            raise OSError("fixture write failure")
        original(path, expected, replacement)
    monkeypatch.setattr(changes, "_replace", replace)
    result = changes.apply(preview["proposal_id"], confirmed=True)
    assert not result.ok and not result.metadata["recovery_needed"]
    assert (root / "one.py").read_bytes() == b"value = 1\r\n"
    assert (root / "two.py").read_text() == "other = 2\n"


@pytest.mark.parametrize("edit", [
    {"path": "../outside.py", "old_text": "x", "new_text": "y"},
    {"path": "one.py", "old_text": "not present", "new_text": "value = 3"},
    {"path": "one.py", "old_text": "value = 1", "new_text": "def broken(:"},
    {"path": "one.py", "old_text": "value = 1", "new_text": "password = fictional-private"},
])
def test_invalid_proposals_do_not_write(source, edit):
    root, workspace, changes, reader = source
    result = reader.execute("propose_project_edits", {"edits": [edit], "explanation": "Fixture"})
    assert "error" in result
    assert not changes.preview()
    assert (root / "one.py").read_bytes() == b"value = 1\r\n"


def test_unread_files_cannot_be_proposed(source):
    root, workspace, changes, reader = source
    (root / "unread.py").write_text("x = 1")
    with pytest.raises(ValueError, match="Read each"):
        changes.propose(reader, [{"path": "unread.py", "old_text": "x = 1", "new_text": "x = 2"}], "Fixture")


def test_opt_in_and_revoke(source):
    root, workspace, changes, reader = source
    changes.enabled = False
    with pytest.raises(ValueError, match="not enabled"):
        propose(changes, reader)
    changes.enabled = True
    preview = propose(changes, reader)
    changes.revoke()
    assert not changes.apply(preview["proposal_id"], confirmed=True).ok
    assert not changes.undo(confirmed=True).ok


def test_tampered_undo_cannot_escape_scope(source):
    root, workspace, changes, reader = source
    preview = propose(changes, reader)
    assert changes.apply(preview["proposal_id"], confirmed=True).ok
    path = root / ".jarvis-undo.json"
    journal = json.loads(path.read_text())
    journal["entries"][0]["path"] = "../outside.py"
    path.write_text(json.dumps(journal))
    assert not changes.undo_available()
    assert not changes.undo(confirmed=True).ok


def test_linked_undo_journal_rejected(source, tmp_path):
    root, workspace, changes, reader = source
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    try:
        os.link(outside, root / ".jarvis-undo.json")
    except OSError:
        pytest.skip("hard links unavailable")
    preview = propose(changes, reader)
    assert not changes.apply(preview["proposal_id"], confirmed=True).ok
    assert outside.read_text() == "{}"


def test_syntax_checks_without_executing_project(source):
    root, workspace, changes, reader = source
    (root / "trap.py").write_text("raise RuntimeError('must not run')\n")
    result = ProjectChecks(workspace).syntax()
    assert result.ok and result.metadata["executed"] is False
    (root / "trap.py").write_text("def broken(:\n")
    result = ProjectChecks(workspace).syntax()
    assert not result.ok
    assert result.metadata["errors"] == [{"path": "trap.py", "line": 1, "kind": "SyntaxError"}]


def test_pytest_requires_separate_approval(source, monkeypatch):
    root, workspace, changes, reader = source
    spawn = Mock(side_effect=AssertionError("No process allowed"))
    monkeypatch.setattr("jarvis.project_checks.subprocess.Popen", spawn)
    assert not ProjectChecks(workspace).pytest(sys.executable).ok
    spawn.assert_not_called()


def test_real_owned_pytest_process_exit_and_secret_free_environment(source, monkeypatch):
    root, workspace, changes, reader = source
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-do-not-pass")
    (root / "test_fixture.py").write_text("import os\ndef test_ok():\n    assert not os.getenv('OPENAI_API_KEY')\n")
    result = ProjectChecks(workspace).pytest(sys.executable, confirmed=True, timeout=20)
    assert result.ok, result.message
    assert result.metadata["exit_code"] == 0
    assert "1 passed" in result.message
    (root / "test_fixture.py").write_text("def test_fail():\n    assert False\n")
    result = ProjectChecks(workspace).pytest(sys.executable, confirmed=True, timeout=20)
    assert not result.ok and result.metadata["exit_code"] == 1


def test_owned_pytest_timeout(source):
    root, workspace, changes, reader = source
    (root / "test_wait.py").write_text("import time\ndef test_wait():\n    time.sleep(20)\n")
    result = ProjectChecks(workspace).pytest(sys.executable, confirmed=True, timeout=0.5)
    assert not result.ok and result.metadata["interrupted"]


def test_pytest_ignores_same_size_same_timestamp_stale_bytecode(source):
    import py_compile
    root, workspace, changes, reader = source
    module = root / "fixture_value.py"
    module.write_bytes(b"value = 1\n")
    original = module.stat()
    py_compile.compile(str(module), doraise=True)
    module.write_bytes(b"value = 2\n")
    os.utime(module, ns=(original.st_atime_ns, original.st_mtime_ns))
    (root / "test_current.py").write_text("from fixture_value import value\ndef test_current():\n    assert value == 2\n")
    result = ProjectChecks(workspace).pytest(sys.executable, confirmed=True, timeout=20)
    assert result.ok, result.message
    assert not list(root.glob(".jarvis-check-*"))


def test_owned_pytest_descendant_is_cleaned_up(source):
    import psutil
    root, workspace, changes, reader = source
    (root / "test_child.py").write_text(
        "import subprocess, sys, os\nfrom pathlib import Path\n"
        "def test_child():\n"
        "    p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, "
        "creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)\n"
        "    Path('child-pid.txt').write_text(str(p.pid))\n"
        "    assert p.poll() is None\n")
    result = ProjectChecks(workspace).pytest(sys.executable, confirmed=True, timeout=20)
    assert result.ok, result.message
    pid = int((root / "child-pid.txt").read_text())
    # Windows can retain a terminated process object briefly after job accounting
    # reaches zero; allow that object to disappear before asserting PID absence.
    import time
    deadline = time.monotonic() + 3
    while psutil.pid_exists(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not psutil.pid_exists(pid)


def test_model_can_only_prepare_not_apply_the_patch(source):
    from types import SimpleNamespace
    from jarvis.vision.project_analysis import analyze_project
    root, workspace, changes, _ = source
    reader = ProjectReader(workspace, changes=changes)
    client = Mock()
    def tool(name, args, call_id):
        item = SimpleNamespace(type="function_call", name=name, arguments=json.dumps(args), call_id=call_id)
        return SimpleNamespace(status="completed", output=[item], output_text="")
    client.responses.create.side_effect = [
        tool("read_project_file", {"path": "one.py", "start_line": 1}, "read"),
        tool("propose_project_edits", {"explanation": "Fixture update", "edits": [
            {"path": "one.py", "old_text": "value = 1", "new_text": "value = 2"}]}, "propose"),
        SimpleNamespace(status="completed", output=[], output_text="Review the proposed patch."),
    ]
    result = analyze_project(client, model="gpt-5.6-sol", content=[], instructions="", reader=reader)
    assert result.output_text.startswith("Review")
    assert changes.preview()
    assert (root / "one.py").read_bytes() == b"value = 1\r\n"
    names = {tool["name"] for tool in client.responses.create.call_args.kwargs["tools"]}
    assert "propose_project_edits" in names and "apply_project_patch" not in names
