"""Scenario 2 of 6: ten alternating turns (user speaks, assistant replies,
repeated) survive one continuous run_stream() call without state desync --
no stuck _response_busy, no duplicate response.create, every turn's
transcript attributed to the right speaker. Deterministic/mocked only.
"""

from __future__ import annotations

from jarvis.realtime import RealtimeVoiceConfig

from .fixtures import StateRecorder, patch_realtime_transport, run_session


def _turn_events(index: int) -> list[dict]:
    return [
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "transcript": f"user turn {index}",
        },
        {"type": "response.created", "response": {"id": f"r{index}"}},
        {
            "type": "response.output_audio_transcript.done",
            "item_id": f"item{index}",
            "transcript": f"assistant turn {index}",
        },
        {"type": "response.done", "response": {"id": f"r{index}", "status": "completed", "output": []}},
    ]


def test_ten_turns_complete_without_state_desync(monkeypatch):
    events = [{"type": "session.updated"}]
    for index in range(1, 11):
        events.extend(_turn_events(index))
    patch_realtime_transport(monkeypatch, events)
    recorder = StateRecorder()

    session = run_session(RealtimeVoiceConfig(greeting=""), on_state=recorder)

    # Every turn reached a stable, idle-ish handoff: _response_busy never
    # got stuck True and the active response id was cleared each time.
    assert session._response_busy is False
    assert session._active_response == ""

    thinking_count = recorder.states().count("thinking")
    listening_count = recorder.states().count("listening")
    assert thinking_count == 10
    # run_stream() itself emits one "listening" the moment the stream opens
    # (before any turn happens), plus one clean handoff back to listening
    # after each of the 10 completed turns.
    assert listening_count == 11


def test_each_turns_transcript_is_attributed_to_the_correct_speaker(monkeypatch):
    events = [{"type": "session.updated"}]
    for index in range(1, 11):
        events.extend(_turn_events(index))
    patch_realtime_transport(monkeypatch, events)
    recorder = StateRecorder()

    run_session(RealtimeVoiceConfig(greeting=""), on_state=recorder)

    user_transcripts = [event["transcript"] for state, event in recorder.events if state == "user_transcript"]
    assistant_transcripts = [
        event["transcript"] for state, event in recorder.events if state == "assistant_transcript_done"
    ]
    assert user_transcripts == [f"user turn {i}" for i in range(1, 11)]
    assert assistant_transcripts == [f"assistant turn {i}" for i in range(1, 11)]
