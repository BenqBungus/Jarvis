"""Scenario 1 of 6 from docs/CLAUDE_WORK_HANDOFF.md's opt-in acceptance
list: greeting. Deterministic/mocked only -- see fixtures.py.
"""

from __future__ import annotations

from jarvis.realtime import RealtimeVoiceConfig

from .fixtures import StateRecorder, patch_realtime_transport, run_session


def test_session_greets_exactly_once_on_connect(monkeypatch):
    socket = patch_realtime_transport(monkeypatch, [{"type": "session.updated"}])
    recorder = StateRecorder()

    run_session(RealtimeVoiceConfig(greeting="Hello Berk, how can I help you?"), on_state=recorder)

    greetings = [event for event in socket.sent if event.get("type") == "response.create"]
    assert len(greetings) == 1
    assert greetings[0]["response"]["instructions"] == "Greet the user with exactly: Hello Berk, how can I help you?"
    assert greetings[0]["response"]["tool_choice"] == "none"


def test_no_greeting_is_sent_when_none_is_configured(monkeypatch):
    socket = patch_realtime_transport(monkeypatch, [{"type": "session.updated"}])

    run_session(RealtimeVoiceConfig(greeting=""))

    assert not any(event.get("type") == "response.create" for event in socket.sent)


def test_a_second_connection_does_not_replay_a_stale_greeting(monkeypatch):
    """Each run_stream() call sends its own greeting exactly once -- a
    second, independent session (e.g. after a reconnect) must not somehow
    carry over or duplicate the first session's greeting response."""
    config = RealtimeVoiceConfig(greeting="Hello Berk, how can I help you?")

    first_socket = patch_realtime_transport(monkeypatch, [{"type": "session.updated"}])
    run_session(config)
    first_greetings = [e for e in first_socket.sent if e.get("type") == "response.create"]
    assert len(first_greetings) == 1

    second_socket = patch_realtime_transport(monkeypatch, [{"type": "session.updated"}])
    run_session(config)
    second_greetings = [e for e in second_socket.sent if e.get("type") == "response.create"]
    assert len(second_greetings) == 1
    assert second_socket is not first_socket
