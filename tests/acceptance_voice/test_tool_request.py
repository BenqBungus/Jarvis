"""Scenario 4 of 6: tool request, success and failure. Deterministic/mocked
only.

Deliberately calls _respond_to_tools()/_maybe_execute_tool_call() directly
(the same entry points tests/test_realtime_transport.py's existing tool
tests already use) rather than driving this through a full run_stream()
call: _receive_events() cancels any still-pending tool task in its own
`finally` block once the event stream ends (by design, so a tool call never
outlives an already-ended call) -- scripting a full run_stream() socket to
reliably win that race would be inherently flaky, not a meaningful
acceptance signal.

The "tool executor raises" case below is a normal, expected outcome
(_maybe_execute_tool_call catches it and reports {"ok": False, ...} back to
the model as the function's own result) -- distinct from the separate
RealtimeVoiceWorker.tool_error_occurred *display* concern, which is already
covered end-to-end in tests/test_gui_realtime_tool_error_display.py and
reused here only to prove the two concerns connect correctly.
"""

from __future__ import annotations

import asyncio
import json

from jarvis.gui.realtime_worker import RealtimeVoiceWorker
from jarvis.realtime import RealtimeVoiceSession

from .fixtures import ScenarioSocket


def test_tool_call_round_trips_through_the_executor_and_requests_a_spoken_summary():
    async def scenario() -> None:
        session = RealtimeVoiceSession()
        socket = ScenarioSocket([])
        calls: list[tuple[str, dict]] = []

        def tool_executor(name: str, arguments: dict) -> dict:
            calls.append((name, arguments))
            return {"ok": True, "message": "Volume set to 30%."}

        await session._respond_to_tools(
            socket,
            [{"type": "function_call", "name": "set_volume", "call_id": "call-1", "arguments": '{"percent": 30}'}],
            tool_executor,
            on_state=None,
        )

        assert calls == [("set_volume", {"percent": 30})]
        outputs = [event for event in socket.sent if event.get("type") == "conversation.item.create"]
        assert len(outputs) == 1
        assert outputs[0]["item"]["call_id"] == "call-1"
        assert json.loads(outputs[0]["item"]["output"]) == {"ok": True, "message": "Volume set to 30%."}
        assert any(event.get("type") == "response.create" for event in socket.sent)

    asyncio.run(scenario())


def test_a_raising_tool_executor_reports_a_failed_result_not_a_crash():
    async def scenario() -> None:
        session = RealtimeVoiceSession()
        socket = ScenarioSocket([])

        def tool_executor(name: str, arguments: dict) -> dict:
            raise RuntimeError("device not found")

        await session._respond_to_tools(
            socket,
            [{"type": "function_call", "name": "set_volume", "call_id": "call-1", "arguments": "{}"}],
            tool_executor,
            on_state=None,
        )

        outputs = [event for event in socket.sent if event.get("type") == "conversation.item.create"]
        assert len(outputs) == 1
        output = json.loads(outputs[0]["item"]["output"])
        assert output["ok"] is False
        assert "device not found" in output["message"]
        # Still requests a spoken summary -- a failed tool is a normal
        # conversational outcome, not a session-ending error.
        assert any(event.get("type") == "response.create" for event in socket.sent)

    asyncio.run(scenario())


def test_invalid_tool_arguments_are_rejected_before_the_executor_ever_runs():
    async def scenario() -> None:
        session = RealtimeVoiceSession()
        socket = ScenarioSocket([])
        calls: list[tuple[str, dict]] = []

        await session._respond_to_tools(
            socket,
            [{"type": "function_call", "name": "set_volume", "call_id": "call-1", "arguments": "not json"}],
            lambda name, arguments: calls.append((name, arguments)),
            on_state=None,
        )

        assert not calls
        outputs = [event for event in socket.sent if event.get("type") == "conversation.item.create"]
        assert json.loads(outputs[0]["item"]["output"])["ok"] is False

    asyncio.run(scenario())


def test_a_worker_level_tool_error_still_reaches_the_ui_as_a_distinct_error(qapp, pump_events):
    """Connects this scenario file to the separate tool_error *display*
    concern (see module docstring) -- full coverage of that path lives in
    tests/test_gui_realtime_tool_error_display.py; this just proves the two
    don't silently drift apart."""
    from jarvis.gui.main_window import MainWindow

    window = MainWindow()
    worker = RealtimeVoiceWorker(object(), lambda *args: {})
    worker.tool_error_occurred.connect(window.show_tool_error)

    try:
        worker._on_realtime_state("tool_error", {"message": "Screen streaming was rejected: quota exceeded"})

        assert pump_events(
            lambda: window._feedback_text == "Screen streaming was rejected: quota exceeded", timeout=3
        )
        assert window._feedback_error is True
    finally:
        window.deleteLater()
