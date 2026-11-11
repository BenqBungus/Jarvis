from __future__ import annotations

import asyncio
import base64
import json
import struct

from jarvis.realtime import RealtimeVoiceConfig, RealtimeVoiceSession, _pcm_level


def test_mute_blocks_capture_and_discards_queued_speech_even_after_unmute():
    session = RealtimeVoiceSession(RealtimeVoiceConfig())
    pcm = struct.pack("<hhhh", 12000, -12000, 8000, -8000)
    old = session._capture_chunk(pcm)
    assert session._outgoing_chunk(old) == pcm
    session.set_input_muted(True)
    assert session._input_level == 0
    assert session._outgoing_chunk(old) == bytes(len(pcm))
    muted = session._capture_chunk(pcm)
    assert muted[1] == bytes(len(pcm))
    session.set_input_muted(False)
    assert session._outgoing_chunk(old) == bytes(len(pcm))
    assert session._outgoing_chunk(muted) == bytes(len(pcm))
    assert session._outgoing_chunk(session._capture_chunk(pcm)) == pcm


def test_muted_wire_packets_are_silence_so_vad_can_finish_the_turn():
    async def run():
        session = RealtimeVoiceSession(RealtimeVoiceConfig())
        queue = asyncio.Queue()
        await queue.put(session._capture_chunk(b"\x01\x20" * 2400))
        session.set_input_muted(True)
        sent = []

        class Socket:
            async def send(self, packet):
                sent.append(json.loads(packet))
                raise asyncio.CancelledError()

        try:
            await session._send_audio(Socket(), queue)
        except asyncio.CancelledError:
            pass
        assert sent[0]["type"] == "input_audio_buffer.append"
        assert base64.b64decode(sent[0]["audio"]) == bytes(4800)

    asyncio.run(run())


def test_pcm_meter_is_silent_for_silence_and_clamps_loud_audio():
    assert _pcm_level(b"") == 0
    assert _pcm_level(bytes(4800)) == 0
    assert _pcm_level(b"x") == 0
    assert 0 < _pcm_level(struct.pack("<hh", 1000, -1000)) < 1
    assert _pcm_level(struct.pack("<hh", 32767, -32768)) == 1


def test_speaker_guard_blocks_playback_echo_and_discards_old_microphone_backlog(monkeypatch):
    from types import SimpleNamespace

    clock = [10.0]
    monkeypatch.setattr("jarvis.realtime.time.monotonic", lambda: clock[0])
    session = RealtimeVoiceSession(RealtimeVoiceConfig(speaker_guard=True))
    session._playback = SimpleNamespace(pending=False)
    pcm = b"\x01\x20" * 2400
    old = session._capture_chunk(pcm)
    session._playback.pending = True
    assert session._outgoing_chunk(old) == bytes(len(pcm))
    echo = session._capture_chunk(pcm)
    assert echo[1] == bytes(len(pcm))
    session._observe_output(pcm, 2400, SimpleNamespace(outputBufferDacTime=1.2, currentTime=1.0))
    session._playback.pending = False
    clock[0] = 10.59  # Output latency + audio duration + room echo tail.
    assert session._capture_chunk(pcm)[1] == bytes(len(pcm))
    clock[0] = 10.61
    assert session._outgoing_chunk(old) == bytes(len(pcm))
    assert session._outgoing_chunk(echo) == bytes(len(pcm))
    assert session._outgoing_chunk(session._capture_chunk(pcm)) == pcm


def test_headphones_keep_microphone_live_during_playback_but_respect_manual_mute():
    from types import SimpleNamespace

    session = RealtimeVoiceSession(RealtimeVoiceConfig(speaker_guard=False))
    session._playback = SimpleNamespace(pending=True)
    pcm = b"\x01\x20" * 2400
    assert session._outgoing_chunk(session._capture_chunk(pcm)) == pcm
    session.set_input_muted(True)
    assert session._capture_chunk(pcm)[1] == bytes(len(pcm))


def test_speaker_guard_still_feeds_local_keyword_but_manual_mute_does_not():
    from types import SimpleNamespace

    packets, mutes = [], []
    session = RealtimeVoiceSession(RealtimeVoiceConfig(speaker_guard=True))
    session._keyword_listener = SimpleNamespace(feed=lambda *args: packets.append(args), set_muted=mutes.append)
    session._playback = SimpleNamespace(pending=True)
    session._reply_generation = 7
    pcm = b"\x01\x20" * 2400
    assert session._capture_chunk(pcm)[1] == bytes(len(pcm))
    assert packets == [("microphone", pcm, 7)]
    session.set_input_muted(True)
    session._capture_chunk(pcm)
    assert len(packets) == 1
    assert mutes == [True]
    session.set_input_muted(False)
    session._playback.pending = False
    session._capture_chunk(pcm)
    assert len(packets) == 1  # No always-on wake listener when no reply is playing.


def test_keyword_hit_cannot_interrupt_a_new_reply_or_a_muted_or_ended_call():
    from types import SimpleNamespace

    session = RealtimeVoiceSession()
    session._keyword_listener = SimpleNamespace(available=True, set_muted=lambda _: None)
    session._playback = SimpleNamespace(pending=True)
    session._reply_generation = 2
    session._keyword_heard(1)
    assert not session._interrupt_requested.is_set()
    session.set_input_muted(True)
    session._keyword_heard(2)
    assert not session._interrupt_requested.is_set()
    session.set_input_muted(False)
    session._keyword_heard(2)
    assert session._interrupt_requested.is_set()
    session._interrupt_requested.clear()
    session._keyword_listener = None
    session._keyword_heard(2)
    assert not session._interrupt_requested.is_set()


def test_keyword_context_cleans_up_and_discards_callbacks_across_mute_or_session_end(monkeypatch):
    from types import SimpleNamespace

    class Listener:
        available = True

        def __init__(self, callback, _rate):
            self.callback = callback
            self.muted = False

        def set_muted(self, muted):
            self.muted = muted

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.available = False

    monkeypatch.setattr("jarvis.realtime.KeywordInterrupt", Listener)
    queued = []
    loop = SimpleNamespace(call_soon_threadsafe=queued.append)
    session = RealtimeVoiceSession()
    session._playback = SimpleNamespace(pending=True)
    with session._keyword_context(loop) as listener:
        listener.callback(0)
        session.set_input_muted(True)
        session.set_input_muted(False)
        queued.pop()()
        assert not session._interrupt_requested.is_set()
        listener.callback(0)
    queued.pop()()
    assert not session._interrupt_requested.is_set()
    assert session._keyword_listener is None
    assert not listener.available


def test_keyword_reference_uses_actual_output_pcm_and_dac_time():
    import time
    from types import SimpleNamespace

    packets = []
    session = RealtimeVoiceSession()
    session._keyword_listener = SimpleNamespace(feed=lambda *args: packets.append(args))
    pcm = b"\x01\x20" * 480
    before = time.monotonic()
    session._observe_output(pcm, 480, SimpleNamespace(outputBufferDacTime=1.2, currentTime=1))
    assert packets[0][:3] == ("speaker", pcm, 0)
    assert before + .19 <= packets[0][3] <= time.monotonic() + .21
