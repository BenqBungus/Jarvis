from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from jarvis.audit import AuditLogger
from jarvis.gui.activity_center import ActivityCenter
from jarvis.gui.command_executor import CommandExecutor
from jarvis.gui.overlay import OverlayWidget
from jarvis.models import CommandResult
from jarvis.rollback import RollbackManager
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


def test_overlay_enter_dispatches_chosen_mode_without_opening_microphone(qapp):
    widget = OverlayWidget()
    calls = []
    widget.command_submitted.connect(lambda *args: calls.append(args))
    widget.mode.setCurrentIndex(1)
    widget.command_input.setText("звук на 30")
    QTest.keyClick(widget.command_input, Qt.Key.Key_Return)
    assert calls == [("звук на 30", "overlay_local")]
    assert widget.command_input.text() == ""
    widget.toggle()
    QTest.keyClick(widget, Qt.Key.Key_Escape)
    qapp.processEvents()
    assert not widget.isVisible()


def test_activity_view_uses_recorded_reasons_not_generated_explanations(qapp, tmp_path):
    audit = AuditLogger(tmp_path / "audit.jsonl")
    audit.log("отвори документ", CommandResult(True, "Launch accepted", action="open_local_path",
              metadata={"intent_reason": "User requested the observed document", "verification": "launch_request_accepted"}), False)
    center = ActivityCenter(audit, RollbackManager(tmp_path / "rollback.json"))
    center.refresh()
    assert "User requested the observed document" in center.detail.toPlainText()
    assert "launch_request_accepted" in center.detail.toPlainText()
    assert not center.undo_button.isEnabled()


def test_undo_center_passes_snapshot_and_only_allows_latest_action(qapp, tmp_path):
    rollback = RollbackManager(tmp_path / "rollback.json")
    rollback.push("Old", "volume", {"percent": 10})
    rollback.push("Latest", "volume", {"percent": 20})
    center = ActivityCenter(AuditLogger(tmp_path / "audit.jsonl"), rollback)
    calls = []
    center.undo_requested.connect(calls.append)
    center.refresh()
    center.undo_list.setCurrentRow(1)
    center.undo_button.click()
    assert calls == [rollback.peek().timestamp]
    assert not center.undo_button.isEnabled()


def test_local_and_teaching_overlay_jobs_share_audit_without_ai(qapp, pump_events, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    router = CommandRouter(WindowsActions(dry_run=True), SafetyPolicy(auto_confirm=False))
    monkeypatch.setattr(router, "handle", lambda *_: (_ for _ in ()).throw(AssertionError("Not general routing")))
    audit = AuditLogger(tmp_path / "audit.jsonl")
    executor = CommandExecutor(router, audit, dry_run=True)
    executor.start()
    results = []
    executor.result_ready.connect(lambda *args: results.append(args))
    try:
        executor.submit("звук на 30", "overlay_local")
        executor.submit("volume", "overlay_teach")
        assert pump_events(lambda: len(results) == 2)
        assert all(item[2].ok for item in results)
        records = [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]
        assert [record["source"] for record in records] == ["gui_overlay_local", "gui_overlay_teach"]
    finally:
        executor.stop()
        executor._thread.join(2)


def test_repetition_suggestions_never_enable_or_execute_anything(tmp_path):
    from jarvis.automation_suggestions import suggest_repetitions

    audit = AuditLogger(tmp_path / "audit.jsonl")
    for _ in range(3):
        audit.log("volume 30", CommandResult(True, "Verified", action="set_volume",
                  metadata={"tool_arguments": {"percent": 30}}), False)
        audit.log("volume 40", CommandResult(True, "Test", action="set_volume",
                  metadata={"tool_arguments": {"percent": 40}}), True)
        audit.log("restart", CommandResult(True, "Requested", action="restart", permission="confirm",
                  metadata={"tool_arguments": {}}), False)
    before = audit.path.read_bytes()
    suggestions = suggest_repetitions(audit.recent())
    assert len(suggestions) == 1
    assert suggestions[0]["arguments"] == {"percent": 30}
    assert suggestions[0]["count"] == 3
    assert suggestions[0]["enabled"] is False
    assert audit.path.read_bytes() == before
