"""Real cross-component proof for the shared mic_lock design used in
app.py: a single threading.Lock() constructed once and passed into both
VoiceWorker and RealtimeVoiceWorker, with app.py wiring
`on_started=lambda: (..., voice_worker.pause())` /
`on_stopped=lambda: (..., voice_worker.resume())` so Realtime gets exclusive
mic access for the duration of a live call.

Unlike tests/test_gui_voice_worker.py and tests/test_gui_realtime_worker.py
(which test each side in isolation against its own fakes), this test runs
one real VoiceWorker thread and one real RealtimeVoiceWorker thread sharing
one real lock, and proves -- via a tracker shared across both fakes, not
each side's own private counter -- that they never hold "the microphone"
at the same wall-clock time.
"""

from __future__ import annotations

import asyncio
import threading
import time

from jarvis.audio.speech_to_text import RecognizedSpeech
from jarvis.gui.realtime_worker import RealtimeVoiceWorker
from jarvis.gui.voice_worker import VoiceWorker


class _MicActivityTracker:
    """Shared across both fakes -- deliberately not per-side, so a real
    overlap (the actual bug this test would catch) shows up as
    max_concurrent >= 2 regardless of which side caused it."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active = 0
        self.max_concurrent = 0

    def enter(self) -> None:
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)

    def exit(self) -> None:
        with self._lock:
            self._active -= 1


class _TrackedFakeStt:
    def __init__(self, tracker: _MicActivityTracker, phrases=None, listen_delay: float = 0.02) -> None:
        self.available = True
        self._tracker = tracker
        self._phrases = list(phrases or [])
        self._listen_delay = listen_delay
        self.calibrate_calls = 0
        self.listen_calls = 0

    def calibrate(self, duration: float = 0.5) -> None:
        self.calibrate_calls += 1

    def listen_once(self, timeout=None, phrase_time_limit=None):
        self._tracker.enter()
        try:
            self.listen_calls += 1
            time.sleep(self._listen_delay)
            if self._phrases:
                return self._phrases.pop(0)
            return None
        finally:
            self._tracker.exit()


class _FakeAssistant:
    def __init__(self) -> None:
        # VoiceWorker._run() checks self._assistant.tts.wait_until_idle
        # (via getattr with a None default) before each listen -- the
        # attribute must exist, even though this test has nothing that
        # actually speaks.
        self.tts = None

    def handle_utterance(self, text: str) -> None:
        pass


class _FakeRealtimeSessionHoldingMic:
    """Its run_stream() is where a real RealtimeVoiceSession would open the
    sounddevice input/output streams -- holding the tracker for the
    simulated call duration is what stands in for "the mic is in use"."""

    def __init__(self, tracker: _MicActivityTracker, hold_seconds: float = 0.15) -> None:
        self._tracker = tracker
        self._hold_seconds = hold_seconds

    def readiness(self):
        return {"ready": True, "missing": []}

    def set_input_muted(self, muted: bool) -> None:
        pass

    async def run_stream(self, *, tool_executor=None, on_state=None) -> None:
        self._tracker.enter()
        try:
            await asyncio.sleep(self._hold_seconds)
        finally:
            self._tracker.exit()


def test_voice_worker_and_realtime_worker_never_hold_the_shared_mic_lock_together(qapp, pump_events):
    mic_lock = threading.Lock()
    tracker = _MicActivityTracker()
    phrases = [RecognizedSpeech("jarvis test", "en-US") for _ in range(20)]
    stt = _TrackedFakeStt(tracker, phrases=phrases, listen_delay=0.02)
    voice_worker = VoiceWorker(stt, _FakeAssistant(), mic_lock)
    realtime_worker = RealtimeVoiceWorker(
        _FakeRealtimeSessionHoldingMic(tracker, hold_seconds=0.15),
        lambda name, args: {},
        on_started=voice_worker.pause,
        on_stopped=voice_worker.resume,
        mic_lock=mic_lock,
    )

    try:
        voice_worker.start()
        assert pump_events(lambda: stt.listen_calls >= 1, timeout=3)
        calls_before_realtime = stt.listen_calls

        assert realtime_worker.start() is True
        assert pump_events(lambda: not realtime_worker.running, timeout=3)

        # voice_worker must have actually resumed and kept listening after
        # the realtime call ended -- not just "never crashed".
        assert pump_events(lambda: stt.listen_calls >= calls_before_realtime + 3, timeout=3)
    finally:
        voice_worker.stop()

    assert tracker.max_concurrent == 1
