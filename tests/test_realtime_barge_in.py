"""Barge-in on laptop speakers (audio/barge_in.py and RealtimeVoiceSession):
talking over Jarvis stops the reply and the words get through."""
from __future__ import annotations

import math
import struct

import pytest

from jarvis.audio.barge_in import BargeInDetector, pcm_rms
from jarvis.realtime import RealtimeVoiceConfig, RealtimeVoiceSession
from jarvis.user_settings import JarvisSettings

RATE = 24000


def tone(amplitude: float, seconds: float = 0.1, frequency: float = 220.0) -> bytes:
    count = int(RATE * seconds)
    return struct.pack(f"<{count}h", *(int(amplitude * math.sin(2 * math.pi * frequency * i / RATE))
                                       for i in range(count)))


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _speak(detector: BargeInDetector, clock: Clock, output: float, mic: float, chunks: int) -> list[bool]:
    """Jarvis plays `output` while the microphone hears `mic`, 100 ms at a time."""
    hits = []
    for _ in range(chunks):
        for _ in range(5):  # the speaker side runs in 20 ms blocks
            detector.speaker(tone(output, 0.02), clock.now)
            clock.now += 0.02
        hits.append(detector.microphone(tone(mic), 0.1))
    return hits


def test_rms_of_a_sine():
    assert pcm_rms(tone(10000)) == pytest.approx(10000 / math.sqrt(2), rel=0.02)
    assert pcm_rms(b"") == 0.0 and pcm_rms(b"\x00") == 0.0


def test_echo_alone_never_interrupts_and_teaches_the_coupling():
    clock = Clock()
    detector = BargeInDetector(clock=clock)
    hits = _speak(detector, clock, output=9000, mic=3000, chunks=40)  # Jarvis's own voice at 1/3 level
    assert not any(hits)
    assert detector.coupling == pytest.approx(1 / 3, abs=0.08)


def test_talking_clearly_over_jarvis_interrupts_within_a_third_of_a_second():
    clock = Clock()
    detector = BargeInDetector(clock=clock)
    _speak(detector, clock, output=9000, mic=3000, chunks=40)
    hits = _speak(detector, clock, output=9000, mic=12000, chunks=4)
    assert hits.index(True) <= 2  # three 100 ms chunks of speech


def test_a_single_loud_click_is_not_speech():
    clock = Clock()
    detector = BargeInDetector(clock=clock)
    _speak(detector, clock, output=9000, mic=3000, chunks=30)
    hits = _speak(detector, clock, output=9000, mic=15000, chunks=1) + _speak(detector, clock, 9000, 3000, 6)
    assert not any(hits)


def test_speaking_in_a_pause_between_sentences_interrupts():
    clock = Clock()
    detector = BargeInDetector(clock=clock)
    _speak(detector, clock, output=0, mic=100, chunks=20)  # quiet room, Jarvis between sentences
    assert any(_speak(detector, clock, output=0, mic=2500, chunks=4))


class FakePlayback:
    pending = True


def _session(clock: Clock) -> RealtimeVoiceSession:
    session = RealtimeVoiceSession(RealtimeVoiceConfig(speaker_guard=True, barge_in=True))
    session._playback = FakePlayback()
    session._barge_in = BargeInDetector(clock=clock)
    return session


def test_the_session_stops_the_reply_and_sends_what_was_said():
    clock = Clock()
    session = _session(clock)
    detector = session._barge_in
    for _ in range(30):  # Jarvis talking, the person silent: everything gated
        for _ in range(5):
            detector.speaker(tone(9000, 0.02), clock.now)
            clock.now += 0.02
        epoch, chunk = session._capture_chunk(tone(3000))
        assert chunk == bytes(len(chunk))
    assert not session._interrupt_requested.is_set()
    chunks = []
    for _ in range(3):  # the person talks over Jarvis
        for _ in range(5):
            detector.speaker(tone(9000, 0.02), clock.now)
            clock.now += 0.02
        chunks.append(session._capture_chunk(tone(12000)))
    assert session._interrupt_requested.is_set()
    epoch, chunk = chunks[-1]
    assert len(chunk) > len(tone(12000)) and any(chunk)  # pre-roll plus the current chunk
    assert session._outgoing_chunk((epoch, chunk)) == chunk
    _epoch, following = session._capture_chunk(tone(8000))
    assert any(following)  # the input stays open while the person talks
    session._reply_generation += 1  # the next reply starts: back to half-duplex
    _epoch, gated = session._capture_chunk(tone(8000))
    assert gated == bytes(len(gated))


def test_muted_microphone_never_barges_in():
    clock = Clock()
    session = _session(clock)
    session.set_input_muted(True)
    for _ in range(10):
        session._barge_in.speaker(tone(9000, 0.1), clock.now)
        clock.now += 0.1
        session._capture_chunk(tone(15000))
    assert not session._interrupt_requested.is_set()


def test_the_call_reports_speaking_and_mute_for_the_password_voice(qapp):
    from jarvis.gui.realtime_worker import RealtimeVoiceWorker

    session = RealtimeVoiceSession(RealtimeVoiceConfig())
    worker = RealtimeVoiceWorker(session, lambda *args: {})
    assert not session.is_speaking() and not worker.input_muted()
    session._playback = FakePlayback()
    worker.set_input_muted(True)
    assert session.is_speaking() and worker.input_muted()
    assert not worker.is_speaking()  # no call is running
    worker._running = True
    assert worker.is_speaking()


def test_settings_choose_the_mode(monkeypatch):
    import jarvis.realtime as realtime

    monkeypatch.setattr(realtime, "output_is_headphones", lambda: True)
    assert not RealtimeVoiceConfig.from_settings(
        JarvisSettings(openai={"realtime_speaker_guard": "auto"})).speaker_guard
    monkeypatch.setattr(realtime, "output_is_headphones", lambda: False)
    config = RealtimeVoiceConfig.from_settings(JarvisSettings(openai={"realtime_speaker_guard": "auto"}))
    assert config.speaker_guard and config.barge_in
    assert not RealtimeVoiceConfig.from_settings(JarvisSettings(openai={"realtime_barge_in": False})).barge_in
    assert RealtimeVoiceConfig.from_settings(JarvisSettings()).speaker_guard  # unchanged default


def test_headphone_names():
    from jarvis.audio import output_device

    for name, expected in (("Headphones (Realtek(R) Audio)", True), ("Headset Earphone (WH-1000XM4)", True),
                           ("Galaxy Buds2 Pro", True), ("Speakers (Realtek(R) Audio)", False), ("", False)):
        original = output_device.output_name
        output_device.output_name = lambda device=None, value=name: value
        try:
            assert output_device.output_is_headphones() is expected, name
        finally:
            output_device.output_name = original


def test_settings_page_saves_the_mode_and_the_switch(qapp, tmp_path):
    import json

    from jarvis.gui.settings_page import SettingsPage

    page = SettingsPage(JarvisSettings(openai={"realtime_speaker_guard": True}), settings_path=tmp_path / "s.json")
    assert page._live_audio_mode.currentData() is True and page._barge_in_switch.isChecked()
    page._live_audio_mode.setCurrentIndex(page._live_audio_mode.findData("auto"))
    page._barge_in_switch.setChecked(False)
    page._on_save()
    saved = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))["openai"]
    assert saved["realtime_speaker_guard"] == "auto" and saved["realtime_barge_in"] is False
