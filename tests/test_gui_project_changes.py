import sys
import time
from unittest.mock import Mock

from PySide6.QtWidgets import QMessageBox

from jarvis.gui.project_changes import ProjectChangesDialog
from jarvis.models import CommandResult
from jarvis.project_changes import ProjectChanges
from jarvis.project_workspace import ProjectReader, ProjectWorkspace


def prepare(tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "main.py").write_text("value = 1\n")
    changes = ProjectChanges(ProjectWorkspace(root))
    changes.enabled = True
    reader = ProjectReader(changes.workspace, changes=changes)
    reader.read_file("main.py")
    changes.propose(reader, [{"path": "main.py", "old_text": "value = 1", "new_text": "value = 2"}], "Update fixture.")
    return root, changes


def wait(qapp, predicate):
    end = time.monotonic() + 5
    while not predicate() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert predicate()


def test_apply_requires_confirmation_and_automatically_checks_syntax(qapp, tmp_path, monkeypatch):
    root, changes = prepare(tmp_path)
    panel = ProjectChangesDialog(changes)
    reports = []
    panel.verification_changed.connect(reports.append)
    try:
        assert "-value = 1" in panel.diff.toPlainText()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
        panel.apply_patch()
        assert (root / "main.py").read_text() == "value = 1\n"
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        panel.apply_patch()
        wait(qapp, lambda: not panel.running)
        assert (root / "main.py").read_text() == "value = 2\n"
        assert "Syntax check: 1 passed" in panel.report.toPlainText()
        assert reports and "No project code was executed" in reports[-1]
        panel.undo_patch()
        assert (root / "main.py").read_text() == "value = 1\n"
    finally:
        panel.shutdown()


def test_pytest_consent_no_never_starts_process(qapp, tmp_path, monkeypatch):
    root, changes = prepare(tmp_path)
    panel = ProjectChangesDialog(changes)
    start = Mock()
    monkeypatch.setattr(panel, "_start_check", start)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    try:
        panel.profile.setCurrentIndex(1)
        panel.runtime.setText(sys.executable)
        panel.run_check()
        start.assert_not_called()
    finally:
        panel.shutdown()


def test_check_stdout_stays_local_without_separate_consent(qapp, tmp_path, monkeypatch):
    root, changes = prepare(tmp_path)
    panel = ProjectChangesDialog(changes)
    reports = []
    panel.verification_changed.connect(reports.append)
    result = CommandResult(False, "pytest exit code: 1\nPRIVATE-FIXTURE-OUTPUT", metadata={"profile": "pytest", "exit_code": 1})
    try:
        panel._show_result(result)
        assert "PRIVATE-FIXTURE" in panel.report.toPlainText()
        assert "PRIVATE-FIXTURE" not in reports[-1]
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        panel.share_output.setChecked(True)
        panel._show_result(result)
        assert "PRIVATE-FIXTURE" in reports[-1]
    finally:
        panel.shutdown()


def test_revoked_project_cannot_apply_or_run(qapp, tmp_path):
    root, changes = prepare(tmp_path)
    panel = ProjectChangesDialog(changes)
    try:
        changes.revoke()
        panel.refresh()
        assert not panel.apply_button.isEnabled() and not panel.check_button.isEnabled()
        panel.apply_patch()
        panel.run_check()
        assert not panel.running
        assert (root / "main.py").read_text() == "value = 1\n"
    finally:
        panel.shutdown()


def test_gui_repair_has_session_and_patch_consent_and_retests(qapp, tmp_path, monkeypatch):
    root, changes = prepare(tmp_path)
    changes.discard()
    (root / "main.py").write_text("value =\n")
    ai = Mock()
    def diagnose(evidence, reader):
        assert "SyntaxError" in evidence
        reader.read_file("main.py")
        changes.propose(reader, [{"path": "main.py", "old_text": "value =", "new_text": "value = 2"}], "Fix fixture syntax.")
        return CommandResult(True, "Review fixture syntax fix.")
    ai.diagnose_project_check.side_effect = diagnose
    panel = ProjectChangesDialog(changes, ai=ai)
    try:
        assert panel.repair_button.isEnabled()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
        panel.start_repair()
        assert panel.repair is None
        ai.diagnose_project_check.assert_not_called()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        panel.start_repair()
        wait(qapp, lambda: not panel.running)
        assert panel.session_active and panel.repair.state == "awaiting_review"
        assert not panel.check_button.isEnabled() and not panel.undo_button.isEnabled()
        assert panel.apply_button.isEnabled()
        assert "awaiting review" in panel.session_status.text()
        assert not panel.share_output.isChecked()
        assert (root / "main.py").read_text() == "value =\n"
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
        panel.apply_patch()
        assert panel.repair.state == "awaiting_review"
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        panel.apply_patch()
        wait(qapp, lambda: not panel.running)
        assert panel.repair.state == "passed" and not panel.session_active
        assert "Selected check passed" in panel.report.toPlainText()
        ai.diagnose_project_check.assert_called_once()
    finally:
        panel.shutdown()


def test_closing_repair_review_cancels_and_discards(qapp, tmp_path):
    from jarvis.project_repair import ProjectRepair
    root, changes = prepare(tmp_path)
    changes.discard()
    def diagnose(evidence, reader):
        reader.read_file("main.py")
        changes.propose(reader, [{"path": "main.py", "old_text": "value = 1", "new_text": "value = 2"}], "Fixture.")
        return CommandResult(True, "Fixture.")
    panel = ProjectChangesDialog(changes)
    panel.repair = ProjectRepair(changes, diagnose)
    panel.repair.checks.syntax = Mock(return_value=CommandResult(False, "Fixture", metadata={"errors": ["fixture"]}))
    try:
        panel.repair.start(confirmed=True)
        panel.refresh()
        panel.reject()
        assert not panel.session_active and changes.preview() is None
        assert panel.repair.state == "cancelled"
        panel.apply_patch()
        assert (root / "main.py").read_text() == "value = 1\n"
    finally:
        panel.shutdown()


def test_new_file_review_labels_creation_and_undo_removes_it(qapp, tmp_path, monkeypatch):
    root, changes = prepare(tmp_path)
    changes.discard()
    reader = ProjectReader(changes.workspace, changes=changes)
    reader.list_files(".")
    changes.propose(reader, [], "Create fixture module.", [{"path": "helper.py", "content": "value = 42\n"}])
    panel = ProjectChangesDialog(changes)
    confirmations = []
    def approve(parent, title, text, *args):
        confirmations.append(text)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", approve)
    try:
        assert "/dev/null" in panel.diff.toPlainText()
        panel.apply_patch()
        wait(qapp, lambda: not panel.running)
        assert "CREATE helper.py" in confirmations[0]
        assert (root / "helper.py").read_text() == "value = 42\n"
        assert "Syntax check: 1 passed" in panel.report.toPlainText()
        panel.undo_patch()
        assert "remove unchanged files" in confirmations[1]
        assert not (root / "helper.py").exists()
    finally:
        panel.shutdown()
