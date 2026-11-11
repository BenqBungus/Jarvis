from __future__ import annotations

import asyncio
import threading
import time

from jarvis.gui.realtime_worker import RealtimeVoiceWorker


class _FakeRealtimeSession:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready
        self.run_calls = 0
        self.muted = False

    def set_input_muted(self, muted):
        self.muted = muted

    def readiness(self):
        return {
            "ready": self.ready,
            "missing": [] if self.ready else ["OPENAI_API_KEY"],
        }

    async def run_stream(self, *, tool_executor=None, on_state=None):
        self.run_calls += 1
        if on_state is not None:
            on_state("listening", {})
            on_state("user_transcript", {"transcript": "hello"})
            on_state("speaking", {})
        await asyncio.sleep(0.01)


def test_realtime_worker_reports_missing_requirements(qapp, pump_events):
    worker = RealtimeVoiceWorker(_FakeRealtimeSession(ready=False), lambda name, args: {})
    states: list[str] = []
    details: list[str] = []
    worker.state_changed.connect(states.append)
    worker.detail_changed.connect(details.append)

    assert worker.start() is False

    assert "error" in states
    assert "OPENAI_API_KEY" in details[-1]


def test_realtime_worker_runs_session_and_emits_states(qapp, pump_events):
    session = _FakeRealtimeSession(ready=True)
    started: list[bool] = []
    stopped: list[bool] = []
    worker = RealtimeVoiceWorker(
        session,
        lambda name, args: {},
        on_started=lambda: started.append(True),
        on_stopped=lambda: stopped.append(True),
    )
    states: list[str] = []
    details: list[str] = []
    user_transcripts: list[str] = []
    worker.state_changed.connect(states.append)
    worker.detail_changed.connect(details.append)
    worker.user_transcript_received.connect(user_transcripts.append)

    assert worker.start() is True

    assert pump_events(lambda: stopped == [True], timeout=3)
    assert pump_events(lambda: states and states[-1] == "idle", timeout=3)
    assert started == [True]
    assert session.run_calls == 1
    assert "connecting" in states
    assert "listening" in states
    assert "speaking" in states
    assert "hello" in details
    assert user_transcripts == ["hello"]


class _FailingRealtimeSession(_FakeRealtimeSession):
    """Simulates the real fail-fast path: a genuine output-stream failure
    surfaces as _watch_playback raising RuntimeError inside run_stream(),
    which _run_thread's except Exception handler must turn into a clean
    error state rather than a hang or an unhandled crash."""

    async def run_stream(self, *, tool_executor=None, on_state=None):
        self.run_calls += 1
        raise RuntimeError(
            "Speaker callback failed: output device disconnected, key sk-abcdefghijklmnopqrstuvwx leaked"
        )


def test_realtime_worker_ends_the_call_cleanly_when_the_output_stream_fails(qapp, pump_events):
    session = _FailingRealtimeSession(ready=True)
    stopped: list[bool] = []
    worker = RealtimeVoiceWorker(session, lambda name, args: {}, on_stopped=lambda: stopped.append(True))
    states: list[str] = []
    details: list[str] = []
    worker.state_changed.connect(states.append)
    worker.detail_changed.connect(details.append)

    assert worker.start() is True

    assert pump_events(lambda: states[-1:] == ["error"] if states else False, timeout=3)
    assert pump_events(lambda: stopped == [True], timeout=3)
    assert pump_events(lambda: not worker.running, timeout=3)
    assert details
    assert "[REDACTED_SECRET]" in details[-1]
    assert "sk-" not in details[-1]


def test_realtime_worker_waits_for_shared_mic_lock(qapp, pump_events):
    session = _FakeRealtimeSession(ready=True)
    mic_lock = threading.Lock()
    mic_lock.acquire()
    worker = RealtimeVoiceWorker(session, lambda name, args: {}, mic_lock=mic_lock)

    try:
        assert worker.start() is True
        time.sleep(0.05)
        assert session.run_calls == 0
    finally:
        mic_lock.release()

    assert pump_events(lambda: session.run_calls == 1, timeout=3)
    assert pump_events(lambda: not worker.running, timeout=3)


def test_realtime_worker_can_stop_while_waiting_for_shared_mic_lock(qapp, pump_events):
    session = _FakeRealtimeSession(ready=True)
    mic_lock = threading.Lock()
    mic_lock.acquire()
    worker = RealtimeVoiceWorker(session, lambda name, args: {}, mic_lock=mic_lock)

    try:
        assert worker.start() is True
        worker.stop()
        assert pump_events(lambda: not worker.running, timeout=3)
        assert session.run_calls == 0
    finally:
        mic_lock.release()


def test_transcript_deltas_keep_spaces_and_do_not_change_voice_state(qapp):
    worker = RealtimeVoiceWorker(_FakeRealtimeSession(), lambda *args: {})
    transcripts, states, completed = [], [], []
    worker.assistant_transcript_received.connect(transcripts.append)
    worker.state_changed.connect(states.append)
    worker.transcript_completed.connect(lambda role, text: completed.append((role, text)))
    worker._on_realtime_state("assistant_transcript_delta", {"item_id": "a", "delta": "Hello "})
    worker._on_realtime_state("assistant_transcript_delta", {"item_id": "a", "delta": "Berk"})
    worker._on_realtime_state("assistant_transcript_done", {"item_id": "a", "transcript": "Hello Berk"})
    assert transcripts[-1] == "Hello Berk"
    assert completed == [("Jarvis", "Hello Berk")]
    assert states == []


def test_meter_updates_do_not_change_transport_state(qapp):
    worker = RealtimeVoiceWorker(_FakeRealtimeSession(), lambda *args: {})
    levels, states = [], []
    worker.audio_level_changed.connect(levels.append)
    worker.state_changed.connect(states.append)
    worker._on_realtime_state("audio_level", {"input": .2, "output": .7})
    assert levels == [.7]
    assert states == []


def test_keyword_status_is_not_forwarded_as_an_unknown_voice_state(qapp):
    worker = RealtimeVoiceWorker(_FakeRealtimeSession(), lambda *args: {})
    statuses, states, details = [], [], []
    worker.keyword_interrupt_changed.connect(lambda ready, detail: statuses.append((ready, detail)))
    worker.state_changed.connect(states.append)
    worker.detail_changed.connect(details.append)
    worker._on_realtime_state("keyword_interrupt_status", {"available": True, "detail": ""})
    worker._on_realtime_state("keyword_interrupt_status", {"available": False, "detail": "Use headphones"})
    assert statuses == [(True, ""), (False, "Use headphones")]
    assert details == ["Use headphones"]
    assert states == []


def test_mute_is_acknowledged_after_transport_is_updated(qapp):
    session = _FakeRealtimeSession()
    worker = RealtimeVoiceWorker(session, lambda *args: {})
    acknowledgements = []
    worker.input_muted_changed.connect(lambda muted: acknowledgements.append((muted, session.muted)))
    worker.set_input_muted(True)
    worker.set_input_muted(False)
    assert acknowledgements == [(True, True), (False, False)]


def test_tool_failure_does_not_claim_live_transport_has_disconnected(qapp):
    worker = RealtimeVoiceWorker(_FakeRealtimeSession(), lambda *args: {})
    states, details, tool_errors = [], [], []
    worker.state_changed.connect(states.append)
    worker.detail_changed.connect(details.append)
    worker.tool_error_occurred.connect(tool_errors.append)
    worker._on_realtime_state("tool_error", {"message": "Tool output could not be sent"})
    assert not states
    assert details == ["Tool output could not be sent"]
    # detail_changed keeps firing unchanged (nothing connected to it today
    # should regress); tool_error_occurred is the new, additive signal a
    # caller can use to render this as a persistent error instead.
    assert tool_errors == ["Tool output could not be sent"]
