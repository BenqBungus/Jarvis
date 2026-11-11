from types import SimpleNamespace

from jarvis.audio.realtime_playback import RealtimePlayback


def render(player, frames, delay=0.0):
    out = bytearray(frames * 2)
    player.callback(out, frames, SimpleNamespace(outputBufferDacTime=delay, currentTime=0), None)
    return bytes(out)


def test_interrupt_reports_heard_audio_not_received_audio():
    now = [10.0]
    player = RealtimePlayback(clock=lambda: now[0])
    player.enqueue("reply", 0, b"\x01\x02" * 24000)
    assert render(player, 480, delay=0.02) == b"\x01\x02" * 480
    now[0] += 0.03
    events = player.interrupt()
    assert events[0]["item_id"] == "reply"
    assert 9 <= events[0]["audio_end_ms"] <= 10
    assert render(player, 480) == bytes(960)
    assert not player.pending


def test_transcript_clock_survives_gaps_between_audio_deltas():
    now = [0.0]
    player = RealtimePlayback(clock=lambda: now[0])
    player.enqueue("reply", 0, b"\x01\x02" * 2400)
    render(player, 2400)
    now[0] = 1.0
    render(player, 480)
    assert not player.pending
    player.enqueue("reply", 0, b"\x01\x02" * 2400)
    assert player.interrupt()[0]["audio_end_ms"] == 100


def test_callback_exception_is_captured_as_playback_error_not_raised():
    # A PortAudio output callback must never raise back into the audio
    # driver -- callback() catches everything into .error for the session
    # loop to notice and act on (see RealtimeVoiceSession._watch_playback).
    # A bare SimpleNamespace() (missing outputBufferDacTime/currentTime)
    # raises AttributeError *inside* callback()'s own try block, which is
    # exactly what proves the guard actually catches real failures rather
    # than the call never reaching the guarded code at all.
    player = RealtimePlayback()
    player.enqueue("reply", 0, b"\x01\x02" * 100)
    out = bytearray(200)

    player.callback(out, 100, SimpleNamespace(), None)

    assert player.error is not None
    assert player.error.startswith("Speaker callback failed:")


def test_each_audio_item_is_truncated_independently():
    player = RealtimePlayback()
    player.enqueue("first", 0, b"\x01\x02" * 100)
    player.enqueue("second", 0, b"\x01\x02" * 100)
    assert [event["item_id"] for event in player.interrupt()] == ["first", "second"]


def test_drained_audio_needs_no_truncation():
    now = [0.0]
    player = RealtimePlayback(clock=lambda: now[0])
    player.enqueue("reply", 0, b"\x01\x02" * 240)
    render(player, 480)
    now[0] = 1.0
    assert player.interrupt() == []
