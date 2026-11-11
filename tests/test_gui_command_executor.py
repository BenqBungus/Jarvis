from __future__ import annotations

import json
import pytest

from jarvis.audit import AuditLogger
from jarvis.gui.command_executor import CommandExecutor
from jarvis.models import CommandResult


class _FakeRouter:
    def __init__(self, responses=None, raise_on=None):
        self.calls: list[str] = []
        self._responses = responses or {}
        self._raise_on = raise_on

    def handle(self, text: str) -> CommandResult:
        self.calls.append(text)
        if self._raise_on and text == self._raise_on:
            raise RuntimeError("simulated router failure")
        return self._responses.get(text, CommandResult(True, f"handled: {text}"))


def _make_executor(tmp_path, **kwargs):
    router = kwargs.pop("router", None) or _FakeRouter()
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    executor = CommandExecutor(router=router, audit=audit, dry_run=True)
    executor.start()
    return executor, router, audit


@pytest.mark.parametrize("command", ["cancel task", "stop current task", "cancel current task",
                                      "local cancel current task", "Jarvis, stop current task", "local: stop task"])
def test_cancel_does_not_wait_in_queue_and_cancels_queued_actions(tmp_path, command):
    import threading

    started = threading.Event()
    release = threading.Event()

    class WaitingRouter(_FakeRouter):
        def handle(self, text):
            self.calls.append(text)
            if text == "long task":
                started.set()
                assert release.wait(3)
            return CommandResult(True, text)

    router = WaitingRouter()
    executor, _, _ = _make_executor(tmp_path, router=router)
    try:
        executor.submit("long task")
        assert started.wait(2)
        executor.submit("must not execute")
        result = executor.submit_blocking(command)
        assert result.metadata["cancel_requested"]
        release.set()
        assert executor.submit_blocking("new request").ok
        assert router.calls == ["long task", "new request"]
    finally:
        release.set()
        executor.stop()
        executor._thread.join(2)


def test_submit_blocking_returns_the_router_result(tmp_path):
    executor, router, _audit = _make_executor(tmp_path)
    result = executor.submit_blocking("jarvis отвори facebook")
    assert result.ok is True
    assert result.message == "handled: jarvis отвори facebook"
    assert "state_timeline" in result.metadata
    assert router.calls == ["jarvis отвори facebook"]
    executor.stop()


def test_submit_blocking_processes_jobs_in_order(tmp_path):
    executor, router, _audit = _make_executor(tmp_path)
    results = [executor.submit_blocking(f"cmd {i}") for i in range(5)]
    assert [r.message for r in results] == [f"handled: cmd {i}" for i in range(5)]
    assert router.calls == [f"cmd {i}" for i in range(5)]
    executor.stop()


def test_submit_blocking_survives_a_raising_router(tmp_path):
    router = _FakeRouter(raise_on="boom")
    executor, _router, _audit = _make_executor(tmp_path, router=router)
    result = executor.submit_blocking("boom")
    assert result.ok is False
    assert "internal error" in result.message.lower()
    # The executor thread must still be alive and serving new jobs.
    next_result = executor.submit_blocking("jarvis отвори facebook")
    assert next_result.ok is True
    executor.stop()


def test_submit_writes_to_audit_log(tmp_path):
    executor, _router, audit = _make_executor(tmp_path)
    executor.submit_blocking("jarvis увеличи звука")  # blocking submit also audits
    lines = audit.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["raw_text"] == "jarvis увеличи звука"
    assert record["ok"] is True
    assert record["source"] == "gui_voice"
    assert record["latency_ms"] >= 0
    executor.stop()


def test_submit_emits_result_ready_signal(tmp_path, pump_events):
    executor, _router, _audit = _make_executor(tmp_path)
    received = []
    executor.result_ready.connect(lambda source, text, result: received.append((source, text, result)))

    executor.submit("jarvis отвори facebook", source="button")

    assert pump_events(lambda: len(received) == 1)
    source, text, result = received[0]
    assert source == "button"
    assert text == "jarvis отвори facebook"
    assert result.ok is True
    assert result.message == "handled: jarvis отвори facebook"
    assert "session_id" in result.metadata
    executor.stop()


def test_stop_unblocks_the_worker_thread(tmp_path):
    executor, _router, _audit = _make_executor(tmp_path)
    executor.stop()
    executor._thread.join(timeout=2)
    assert not executor._thread.is_alive()


def test_realtime_tools_use_the_command_queue_and_audit_log(tmp_path, qapp):
    from jarvis.router import CommandRouter
    from jarvis.safety import SafetyPolicy
    from jarvis.windows_actions import WindowsActions

    router = CommandRouter(actions=WindowsActions(dry_run=True), safety=SafetyPolicy(auto_confirm=True), ai=None)
    executor, _, audit = _make_executor(tmp_path, router=router)
    try:
        result = executor.submit_tool_blocking("open_url", {"url": "https://example.com"})
        assert result["ok"]
        record = json.loads(audit.path.read_text(encoding="utf-8").strip())
        assert record["source"] == "gui_realtime"
        assert record["action"] == "open_url"
        assert record["dry_run"] is True
    finally:
        executor.stop()


def test_task_status_and_cancel_bypass_a_busy_executor(tmp_path, qapp):
    import threading

    entered, release = threading.Event(), threading.Event()

    class WaitingRouter(_FakeRouter):
        def handle(self, text):
            entered.set()
            assert release.wait(3)
            return CommandResult(True, "Finished test action")

    executor, _, audit = _make_executor(tmp_path, router=WaitingRouter())
    try:
        executor.submit("Read shop results")
        assert entered.wait(2)
        executor._report_progress("Step 2: reading prices")
        report = executor.submit_tool_blocking("get_active_task_status", {})
        status = report["metadata"]["task_status"]
        assert report["ok"]
        assert status["active"]
        assert status["title"] == "Read shop results"
        assert status["progress"] == "Step 2: reading prices"
        assert status["elapsed_seconds"] >= 0
        executor.submit_tool_blocking("cancel_task", {})
        assert executor.task_status_result().metadata["task_status"]["cancel_requested"]
        assert not executor.submit_tool_blocking("get_active_task_status", {"unexpected": True})["ok"]
        records = [json.loads(line) for line in audit.path.read_text(encoding="utf-8").splitlines()]
        assert any(record["action"] == "get_active_task_status" for record in records)
    finally:
        release.set()
        executor.stop()
        executor._thread.join(3)


def test_finished_task_status_is_preserved_without_claiming_it_is_active(tmp_path):
    executor, _, _ = _make_executor(tmp_path)
    try:
        assert not executor.task_status_result().metadata["task_status"]["active"]
        executor.submit_blocking("Read temperatures")
        status = executor.task_status_result().metadata["task_status"]
        assert not status["active"]
        assert status["last_task"]["title"] == "Read temperatures"
        assert status["last_task"]["ok"]
        assert status["last_task"]["message"] == "handled: Read temperatures"
    finally:
        executor.stop()


def test_plain_speech_status_bypasses_queue_and_preserves_last_result(tmp_path, qapp):
    import threading
    from jarvis.gui.command_executor import CommandJob
    import queue

    entered, release = threading.Event(), threading.Event()

    class WaitingRouter(_FakeRouter):
        def handle(self, text):
            entered.set()
            assert release.wait(5)
            return CommandResult(True, "Created notes", action="create_local_file",
                                 metadata={"completion_verified": True, "verification_scope": "existence_type_and_size"})

    executor, _, _ = _make_executor(tmp_path, router=WaitingRouter())
    try:
        executor.submit("Create notes")
        assert entered.wait(2)
        for phrase in ("What are you working on?", "Jarvis, task status", "local: Are you done?", "How is the task going?"):
            reply = queue.Queue()
            executor._enqueue(CommandJob(phrase, "voice", reply=reply))
            status = reply.get(timeout=0.5).metadata["task_status"]
            assert status["active"] and status["title"] == "Create notes"
            assert status["queued_entries"] == 0
    finally:
        release.set()
        executor.stop()
        executor._thread.join(3)
    last = executor.task_status_result().metadata["task_status"]["last_task"]
    assert last["completion_evidence"][0]["status"] == "verified"
    last["completion_evidence"][0]["status"] = "tampered"
    assert executor.task_status_result().metadata["task_status"]["last_task"]["completion_evidence"][0]["status"] == "verified"


def test_teach_mode_does_not_execute_status_shortcut(tmp_path, qapp):
    from jarvis.gui.command_executor import CommandJob
    executor = CommandExecutor(_FakeRouter(), AuditLogger(tmp_path / "audit.jsonl"))
    executor._enqueue(CommandJob("task status", "overlay_teach"))
    assert executor._jobs.qsize() == 1


def test_gui_registers_task_status_as_an_argument_free_safe_tool(tmp_path, qapp):
    from jarvis.router import CommandRouter
    from jarvis.safety import SafetyPolicy
    from jarvis.windows_actions import WindowsActions
    from jarvis.realtime import realtime_tool_schemas

    router = CommandRouter(actions=WindowsActions(dry_run=True), safety=SafetyPolicy(auto_confirm=False), ai=None)
    executor = CommandExecutor(router, AuditLogger(tmp_path / "audit.jsonl"), dry_run=True)
    tool = router.tools.get("get_active_task_status")
    assert tool.spec.permission == "safe"
    assert not tool.spec.requires_confirmation
    schema = next(item for item in realtime_tool_schemas(router.tools) if item["name"] == "get_active_task_status")
    assert schema["parameters"]["properties"] == {}
    assert schema["parameters"]["additionalProperties"] is False
    assert executor.submit_tool_blocking("get_active_task_status", {})["ok"]


def test_live_cancel_rejects_waiting_confirmation_without_running_action(tmp_path, qapp, pump_events):
    import threading

    from jarvis.gui.gui_safety import GuiSafetyPolicy
    from jarvis.router import CommandRouter
    from jarvis.tool_registry import ToolSpec
    from jarvis.user_settings import JarvisSettings
    from jarvis.windows_actions import WindowsActions

    safety = GuiSafetyPolicy(JarvisSettings())
    router = CommandRouter(actions=WindowsActions(dry_run=True), safety=safety, ai=None)
    calls = []
    router.tools.register(ToolSpec(name="test_disruptive_action", description="Test confirmation only",
                                  category="system", permission="confirm"),
                          lambda: calls.append(True) or CommandResult(True, "Executed"))
    executor, _, _ = _make_executor(tmp_path, router=router)
    executor.cancellation_requested.connect(safety.cancel_pending)
    results = []
    worker = threading.Thread(target=lambda: results.append(executor.submit_tool_blocking("test_disruptive_action", {})))
    worker.start()
    try:
        assert pump_events(lambda: bool(safety._dialogs))
        status = executor.submit_tool_blocking("get_active_task_status", {})
        assert status["metadata"]["task_status"]["active"]
        executor.submit_tool_blocking("cancel_task", {})
        assert pump_events(lambda: bool(results))
        assert not results[0]["ok"]
        assert results[0]["confirmed"] is False
        assert not calls
        assert not safety._dialogs
    finally:
        safety.shutdown()
        executor.stop()
        worker.join(2)
        executor._thread.join(2)
