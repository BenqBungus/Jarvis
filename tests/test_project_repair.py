import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from jarvis.models import CommandResult
from jarvis.project_changes import ProjectChanges
from jarvis.project_repair import ProjectRepair
from jarvis.project_workspace import ProjectWorkspace


def fixture_project(tmp_path, source="value = 1\n"):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "main.py").write_text(source)
    changes = ProjectChanges(ProjectWorkspace(root))
    changes.enabled = True
    return root, changes


def proposer(old="value = 1", new="value = 2"):
    def diagnose(evidence, reader):
        reader.read_file("main.py")
        reader.changes.propose(reader, [{"path": "main.py", "old_text": old, "new_text": new}], "Fix fixture value.")
        return CommandResult(True, "Prepared fixture repair.")
    return diagnose


def failed_check():
    return CommandResult(False, "syntax failed", metadata={"errors": [{"path": "main.py", "line": 1}]})


def test_syntax_repair_review_retest_and_undo(tmp_path):
    root, changes = fixture_project(tmp_path, "value =\n")
    session = ProjectRepair(changes, proposer("value =", "value = 2"))
    result = session.start(confirmed=True)
    assert result.ok and session.state == "awaiting_review"
    assert (root / "main.py").read_text() == "value =\n"
    assert not session.approve(session.proposal_id).ok
    assert session.state == "awaiting_review"
    result = session.approve(session.proposal_id, confirmed=True)
    assert result.ok and session.state == "passed"
    assert result.metadata["checks_run"] == 2
    assert "not prove" in result.message
    assert changes.undo(confirmed=True).ok
    assert (root / "main.py").read_text() == "value =\n"


def test_real_pytest_failure_repair_then_pass(tmp_path):
    root, changes = fixture_project(tmp_path)
    (root / "test_main.py").write_text("from main import value\ndef test_value():\n    assert value == 2\n")
    evidence = []
    def diagnose(output, reader):
        evidence.append(output)
        return proposer()(output, reader)
    session = ProjectRepair(changes, diagnose, profile="pytest", runtime=sys.executable)
    try:
        assert session.start(confirmed=True).ok
        assert "assert 1 == 2" in evidence[0]
        assert session.state == "awaiting_review"
        result = session.approve(session.proposal_id, confirmed=True)
        assert result.ok and session.state == "passed"
        assert "1 passed" in result.message
        assert [e["action"] for e in session.events if e["action"] != "project_tool"] == ["check", "apply", "check"]
    finally:
        session.cancel()


def test_no_consent_no_check_or_ai(tmp_path):
    root, changes = fixture_project(tmp_path)
    ai = Mock()
    session = ProjectRepair(changes, ai)
    session.checks.syntax = Mock()
    assert not session.start().ok
    session.checks.syntax.assert_not_called()
    ai.assert_not_called()


def test_limit_two_diagnoses_three_checks(tmp_path):
    root, changes = fixture_project(tmp_path)
    def diagnose(evidence, reader):
        value = int((root / "main.py").read_text().split("=")[1])
        return proposer(f"value = {value}", f"value = {value + 1}")(evidence, reader)
    session = ProjectRepair(changes, diagnose)
    session.checks.syntax = Mock(return_value=failed_check())
    assert session.start(confirmed=True).ok
    assert session.approve(session.proposal_id, confirmed=True).ok
    result = session.approve(session.proposal_id, confirmed=True)
    assert not result.ok and session.state == "stopped"
    assert session.diagnoses == 2 and session.check_count == 3
    assert changes.preview() is None


def test_cancel_while_diagnosing_discards_stale_proposal(tmp_path):
    root, changes = fixture_project(tmp_path)
    entered, release = threading.Event(), threading.Event()
    def diagnose(evidence, reader):
        entered.set()
        release.wait(5)
        return proposer()(evidence, reader)
    session = ProjectRepair(changes, diagnose)
    session.checks.syntax = Mock(return_value=failed_check())
    results = []
    worker = threading.Thread(target=lambda: results.append(session.start(confirmed=True)))
    worker.start()
    assert entered.wait(5)
    session.cancel()
    release.set()
    worker.join(5)
    assert not worker.is_alive()
    assert not results[0].ok and session.state == "cancelled"
    assert changes.preview() is None
    assert (root / "main.py").read_text() == "value = 1\n"


def test_changed_source_or_expired_approval_never_overwrites(tmp_path):
    root, changes = fixture_project(tmp_path)
    session = ProjectRepair(changes, proposer())
    session.checks.syntax = Mock(return_value=failed_check())
    assert session.start(confirmed=True).ok
    (root / "main.py").write_text("value = 99\n")
    assert not session.approve(session.proposal_id, confirmed=True).ok
    assert (root / "main.py").read_text() == "value = 99\n"
    assert session.check_count == 1


def test_expiration_and_wrong_proposal_id(tmp_path):
    root, changes = fixture_project(tmp_path)
    for expire in (False, True):
        session = ProjectRepair(changes, proposer())
        session.checks.syntax = Mock(return_value=failed_check())
        assert session.start(confirmed=True).ok
        if expire:
            session._deadline = 1
        assert not session.approve("wrong", confirmed=True).ok
        assert changes.preview() is None
        assert session.state == ("cancelled" if expire else "failed")


def test_infrastructure_failure_does_not_call_ai(tmp_path):
    root, changes = fixture_project(tmp_path)
    ai = Mock()
    session = ProjectRepair(changes, ai, profile="pytest", runtime="missing.exe")
    assert not session.start(confirmed=True).ok
    ai.assert_not_called()
    assert session.state == "stopped"


def test_ai_failure_discards_proposals_no_retry(tmp_path):
    root, changes = fixture_project(tmp_path)
    def failing(evidence, reader):
        proposer()(evidence, reader)
        return CommandResult(False, "API error")
    session = ProjectRepair(changes, failing)
    session.checks.syntax = Mock(return_value=failed_check())
    assert not session.start(confirmed=True).ok
    assert session.diagnoses == 1 and changes.preview() is None


def test_repeated_patch_stops_instead_of_looping(tmp_path):
    root, changes = fixture_project(tmp_path)
    session = ProjectRepair(changes, proposer())
    def failing_check():
        # Simulate project test code resetting a source fixture on every run.
        (root / "main.py").write_text("value = 1\n")
        return failed_check()
    session.checks.syntax = failing_check
    assert session.start(confirmed=True).ok
    result = session.approve(session.proposal_id, confirmed=True)
    assert not result.ok and "Repeated patch" in result.message
    assert changes.preview() is None and session.check_count == 2


def test_revocation_during_review_blocks_apply(tmp_path):
    root, changes = fixture_project(tmp_path)
    session = ProjectRepair(changes, proposer())
    session.checks.syntax = Mock(return_value=failed_check())
    assert session.start(confirmed=True).ok
    changes.revoke()
    assert not session.approve(session.proposal_id, confirmed=True).ok
    assert session.state == "cancelled" and session.check_count == 1
    assert (root / "main.py").read_text() == "value = 1\n"


def test_text_only_ai_adapter_uses_bounded_reader_no_image(tmp_path, monkeypatch):
    import openai
    from jarvis.ai_client import JarvisAI
    from jarvis.project_workspace import ProjectReader
    from jarvis.vision import project_analysis
    root, changes = fixture_project(tmp_path)
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    constructor = Mock(return_value=client)
    monkeypatch.setattr(openai, "OpenAI", constructor)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-placeholder")
    analyze = Mock(return_value=SimpleNamespace(status="completed", output_text="Review the patch.", id="fixture", usage=None))
    monkeypatch.setattr(project_analysis, "analyze_project", analyze)
    reader = ProjectReader(changes.workspace, changes=changes)
    result = JarvisAI().diagnose_project_check("fixture failure", reader)
    assert result.ok
    assert analyze.call_args.kwargs["reader"] is reader
    assert all(item["type"] == "input_text" for item in analyze.call_args.kwargs["content"])
    assert constructor.call_args.kwargs["max_retries"] == 0
