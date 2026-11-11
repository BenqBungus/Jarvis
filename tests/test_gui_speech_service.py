from __future__ import annotations

import threading
import time

from jarvis.gui.speech_service import SpeechService


class _FakeTts:
    def __init__(self, delay: float = 0.0, enabled: bool = True) -> None:
        self.enabled = enabled
        self.calls: list[tuple[str, str | None]] = []
        self._delay = delay
        self._lock = threading.Lock()

    def speak(self, text: str, lang: str | None = None) -> bool:
        with self._lock:
            self.calls.append((text, lang))
        if self._delay:
            time.sleep(self._delay)
        return True


def _wait_until(condition, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        time.sleep(0.01)
    return condition()


def test_request_speak_reaches_the_underlying_engine():
    tts = _FakeTts()
    service = SpeechService(tts)
    service.start()
    service.request_speak("hello", lang="en")
    assert _wait_until(lambda: tts.calls == [("hello", "en")])
    service.stop()


def test_request_speak_ignores_empty_text():
    tts = _FakeTts()
    service = SpeechService(tts)
    service.start()
    service.request_speak("")
    service.request_speak("   ")
    service.request_speak("real message")
    assert _wait_until(lambda: tts.calls == [("real message", None)])
    service.stop()


def test_concurrent_requests_are_spoken_in_fifo_order_not_interleaved():
    # This is the scenario TextToSpeech's own lock does NOT protect against:
    # multiple threads racing to speak. SpeechService must serialize them in
    # submission order via its single consumer thread.
    tts = _FakeTts(delay=0.02)
    service = SpeechService(tts)
    service.start()

    def submit(n: int) -> None:
        service.request_speak(f"message {n}")

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(3)]
    for i, thread in enumerate(threads):
        thread.start()
        thread.join()  # submit strictly in order 0, 1, 2 (join before next submit)

    assert _wait_until(lambda: len(tts.calls) == 3, timeout=3)
    assert [text for text, _lang in tts.calls] == ["message 0", "message 1", "message 2"]
    service.stop()


def test_a_raising_engine_does_not_kill_the_speech_thread():
    calls = {"n": 0}

    class FlakyTts:
        def speak(self, text: str, lang: str | None = None) -> bool:
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("simulated engine failure")
            return True

    service = SpeechService(FlakyTts())
    service.start()
    service.request_speak("first")  # raises internally, must not kill the worker
    service.request_speak("second")
    assert _wait_until(lambda: calls["n"] == 2)
    service.stop()


def test_stop_unblocks_the_worker_thread():
    service = SpeechService(_FakeTts())
    service.start()
    service.stop()
    service._thread.join(timeout=2)
    assert not service._thread.is_alive()


def test_live_call_discards_queued_classic_speech_even_after_call_ends():
    tts = _FakeTts()
    mic = threading.Lock()
    mic.acquire()
    service = SpeechService(tts, mic_lock=mic)
    service.start()
    job = service.request_speak("stale greeting")
    try:
        service.suspend()
        assert service.request_speak("during live call") is None
        service.resume()
        mic.release()
        assert job.done.wait(1)
        assert not job.started and not job.spoken
        assert tts.calls == []
        fresh = service.request_speak("new reply")
        assert fresh.done.wait(1)
        assert fresh.spoken
        assert tts.calls == [("new reply", None)]
    finally:
        if mic.locked():
            mic.release()
        service.stop()
        service._thread.join(timeout=2)


# --- as_tts() / QueuedSpeaker --------------------------------------------------


def test_as_tts_mirrors_the_underlying_engines_enabled_flag():
    assert SpeechService(_FakeTts(enabled=True)).as_tts().enabled is True
    assert SpeechService(_FakeTts(enabled=False)).as_tts().enabled is False


def test_queued_speaker_routes_through_the_service_not_the_engine_directly():
    tts = _FakeTts()
    service = SpeechService(tts)
    service.start()
    speaker = service.as_tts()

    speaker.speak("hello", lang="en")

    assert _wait_until(lambda: tts.calls == [("hello", "en")])
    service.stop()


def test_queued_speaker_disabled_never_reaches_the_engine():
    tts = _FakeTts(enabled=False)
    service = SpeechService(tts)
    service.start()
    speaker = service.as_tts()

    result = speaker.speak("hello")

    assert result is False
    time.sleep(0.05)  # give the worker a chance to run, in case of a bug
    assert tts.calls == []
    service.stop()


def test_queued_speaker_serializes_with_direct_request_speak_calls():
    # A voice prompt via VoiceAssistant(tts=speaker) and a command result via
    # request_speak() must land in the same FIFO queue, not race each other.
    tts = _FakeTts()
    service = SpeechService(tts)
    service.start()
    speaker = service.as_tts()

    speaker.speak("prompt")
    service.request_speak("result")

    assert _wait_until(lambda: tts.calls == [("prompt", None), ("result", None)])
    service.stop()


def test_voice_worker_waits_for_playback_completion_before_listening_again():
    released = threading.Event()
    entered = threading.Event()

    class BlockingTts(_FakeTts):
        def speak(self, text, lang=None):
            entered.set()
            return released.wait(2)

    service = SpeechService(BlockingTts())
    service.start()
    finished = threading.Event()
    thread = threading.Thread(target=lambda: (service.as_tts().speak("reply"), finished.set()))
    thread.start()
    try:
        assert entered.wait(1)
        assert not finished.is_set()
        released.set()
        assert finished.wait(1)
    finally:
        released.set()
        thread.join(2)
        service.stop()


def test_failed_playback_emits_actionable_error(qapp, pump_events):
    class FailedTts:
        last_error = "The selected speaker is disconnected."

        def speak(self, *args, **kwargs):
            return False

    service = SpeechService(FailedTts())
    results = []
    service.playback_finished.connect(lambda ok, message: results.append((ok, message)))
    service.start()
    try:
        service.request_speak("hello")
        assert pump_events(lambda: bool(results))
        assert results == [(False, FailedTts.last_error)]
    finally:
        service.stop()
