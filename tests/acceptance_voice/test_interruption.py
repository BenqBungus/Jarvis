"""Scenario 3 of 6: interruption. Mid-reply, a scripted automatic-VAD
"speech_started" fires; conversation.item.truncate must be sent, buffered
audio must be dropped, and any further audio for the truncated item/
response must never be enqueued into playback (no stale audio plays).
Deterministic/mocked only.

Deliberately does not assert on response.cancel presence/absence for this
automatic-VAD path -- see the "automatic barge-in asymmetry" observation
in docs/claude/VOICE_STATUS.md. That is left open, not locked in either way
by this test.
"""

from __future__ import annotations

import base64

from jarvis.realtime import RealtimeVoiceConfig

from .fixtures import StateRecorder, patch_realtime_transport, run_session

_AUDIO_CHUNK = base64.b64encode(b"\x01\x02" * 2400).decode()


def test_automatic_barge_in_truncates_and_drops_buffered_audio(monkeypatch):
    events = [
        {"type": "session.updated"},
        {"type": "response.created", "response": {"id": "r1"}},
        {
            "type": "response.output_audio.delta",
            "item_id": "answer",
            "content_index": 0,
            "response_id": "r1",
            "delta": _AUDIO_CHUNK,
        },
        {"type": "input_audio_buffer.speech_started"},
    ]
    socket = patch_realtime_transport(monkeypatch, events)
    recorder = StateRecorder()

    session = run_session(RealtimeVoiceConfig(greeting=""), on_state=recorder)

    truncate_messages = [event for event in socket.sent if event.get("type") == "conversation.item.truncate"]
    assert len(truncate_messages) == 1
    assert truncate_messages[0]["item_id"] == "answer"
    assert "interrupted" in recorder.states()
    assert not session._playback.pending


def test_audio_arriving_after_the_interrupt_for_the_same_item_is_never_enqueued(monkeypatch):
    events = [
        {"type": "session.updated"},
        {"type": "response.created", "response": {"id": "r1"}},
        {
            "type": "response.output_audio.delta",
            "item_id": "answer",
            "content_index": 0,
            "response_id": "r1",
            "delta": _AUDIO_CHUNK,
        },
        {"type": "input_audio_buffer.speech_started"},
        # A late delta for the same (now-interrupted) item/response, as if
        # the server hadn't yet noticed the interrupt -- this must be
        # dropped, not played.
        {
            "type": "response.output_audio.delta",
            "item_id": "answer",
            "content_index": 0,
            "response_id": "r1",
            "delta": _AUDIO_CHUNK,
        },
    ]
    patch_realtime_transport(monkeypatch, events)

    session = run_session(RealtimeVoiceConfig(greeting=""))

    assert not session._playback.pending
