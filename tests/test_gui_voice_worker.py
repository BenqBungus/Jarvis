from __future__ import annotations

import threading
import time

from jarvis.audio.speech_to_text import RecognizedSpeech
from jarvis.gui.voice_worker import PushToTalk, VoiceConversation, VoiceWorker


class _FakeStt:
    def __init__(self, phrases=None, available: bool = True, listen_delay: float = 0.0) -> None:
        self.available = available
        self._phrases = list(phrases or [])
        self.calibrate_calls = 0
        self.listen_calls = 0
        self._listen_delay = listen_delay
        self._active = 0
        self.max_concurrent = 0
        self._active_lock = threading.Lock()

    def calibrate(self, duration: float = 0.5) -> None:
        self.calibrate_calls += 1

    def listen_once(self, timeout=None, phrase_time_limit=None):
        with self._active_lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
        self.listen_calls += 1
        if self._listen_delay:
            time.sleep(self._listen_delay)
        with self._active_lock:
            self._active -= 1
        if self._phrases:
            return self._phrases.pop(0)
        return None


class _FakeTts:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.spoken: list[str] = []

    def speak(self, text, lang=None) -> bool:
        self.spoken.append(text)
        return True


class _FakeAssistant:
    def __init__(self, tts=None) -> None:
        self.tts = tts or _FakeTts()
        self.handled: list[str] = []
        self.dispatched: list[str] = []
        self.raise_on_handle = False
        self._session_active = False

    def handle_utterance(self, text: str):
        self.handled.append(text)
        if self.raise_on_handle:
            raise RuntimeError("simulated handler failure")

    def dispatch_command(self, text: str, lang=None):
        self.dispatched.append(text)
        if "спри" in text or "stop" in text:
            self.end_session()
            from jarvis.models import CommandResult

            return CommandResult(True, "Voice session ended.")
        from jarvis.models import CommandResult

        return CommandResult(True, f"handled: {text}")

    def start_session(self) -> None:
        self._session_active = True

    def end_session(self) -> None:
        self._session_active = False

    def session_active(self) -> bool:
        return self._session_active


def _wait_until(condition, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        time.sleep(0.005)
    return condition()


# --- VoiceWorker -------------------------------------------------------------


def test_start_does_nothing_when_stt_unavailable(qapp):
    stt = _FakeStt(available=False)
    worker = VoiceWorker(stt, _FakeAssistant(), threading.Lock())
    worker.start()
    assert not worker._thread.is_alive()
    assert stt.calibrate_calls == 0


def test_start_calibrates_before_listening(qapp):
    stt = _FakeStt(phrases=[])
    worker = VoiceWorker(stt, _FakeAssistant(), threading.Lock())
    worker.start()
    assert _wait_until(lambda: stt.calibrate_calls == 1)
    worker.stop()


def test_continuous_loop_dispatches_each_heard_phrase(qapp):
    phrases = [RecognizedSpeech("jarvis отвори facebook", "bg-BG"), RecognizedSpeech("jarvis увеличи звука", "bg-BG")]
    stt = _FakeStt(phrases=phrases)
    assistant = _FakeAssistant()
    worker = VoiceWorker(stt, assistant, threading.Lock())
    worker.start()
    assert _wait_until(lambda: len(assistant.handled) == 2)
    assert assistant.handled == ["jarvis отвори facebook", "jarvis увеличи звука"]
    worker.stop()


def test_state_changes_emit_listening_then_processing(qapp, pump_events):
    stt = _FakeStt(phrases=[RecognizedSpeech("jarvis отвори facebook", "bg-BG")])
    worker = VoiceWorker(stt, _FakeAssistant(), threading.Lock())
    states: list[str] = []
    worker.state_changed.connect(states.append)
    worker.start()
    assert pump_events(lambda: "processing" in states, timeout=3)
    assert states[0] == "listening"
    worker.stop()


def test_voice_worker_emits_heard_transcript(qapp, pump_events):
    stt = _FakeStt(phrases=[RecognizedSpeech("jarvis отвори facebook", "bg-BG")])
    worker = VoiceWorker(stt, _FakeAssistant(), threading.Lock())
    transcripts: list[str] = []
    worker.transcript_heard.connect(transcripts.append)
    worker.start()
    assert pump_events(lambda: transcripts == ["jarvis отвори facebook"], timeout=3)
    worker.stop()


def test_stop_ends_the_thread_and_eventually_emits_idle(qapp, pump_events):
    stt = _FakeStt(phrases=[])
    worker = VoiceWorker(stt, _FakeAssistant(), threading.Lock())
    states: list[str] = []
    worker.state_changed.connect(states.append)
    worker.start()
    assert pump_events(lambda: "listening" in states)
    worker.stop()
    assert pump_events(lambda: states and states[-1] == "idle", timeout=3)
    worker._thread.join(timeout=2)
    assert not worker._thread.is_alive()


def test_a_raising_handler_does_not_kill_the_loop(qapp):
    stt = _FakeStt(phrases=[RecognizedSpeech("jarvis boom", "en-US"), RecognizedSpeech("jarvis отвори facebook", "bg-BG")])
    assistant = _FakeAssistant()
    assistant.raise_on_handle = True
    worker = VoiceWorker(stt, assistant, threading.Lock())
    worker.start()
    assert _wait_until(lambda: len(assistant.handled) == 2)
    worker.stop()


def test_voice_worker_can_pause_and_resume_without_restarting_thread(qapp):
    stt = _FakeStt(phrases=[], listen_delay=0.01)
    assistant = _FakeAssistant()
    worker = VoiceWorker(stt, assistant, threading.Lock())

    worker.start()
    assert _wait_until(lambda: stt.listen_calls >= 1)
    worker.pause()
    calls_after_pause = stt.listen_calls
    time.sleep(0.15)
    assert stt.listen_calls == calls_after_pause
    stt._phrases.append(RecognizedSpeech("jarvis resumed", "en-US"))
    worker.resume()
    assert _wait_until(lambda: assistant.handled == ["jarvis resumed"])
    worker.stop()
    worker._thread.join(timeout=2)


# --- PushToTalk ---------------------------------------------------------------


def test_push_to_talk_does_nothing_when_stt_unavailable(qapp):
    stt = _FakeStt(available=False)
    ptt = PushToTalk(stt, _FakeAssistant(), threading.Lock())
    ptt.trigger()
    assert stt.listen_calls == 0


def test_push_to_talk_dispatches_heard_text(qapp):
    stt = _FakeStt(phrases=[RecognizedSpeech("отвори facebook", "bg-BG")])
    assistant = _FakeAssistant()
    ptt = PushToTalk(stt, assistant, threading.Lock())
    ptt.trigger()
    assert _wait_until(lambda: assistant.dispatched == ["отвори facebook"])


def test_push_to_talk_emits_heard_transcript(qapp, pump_events):
    stt = _FakeStt(phrases=[RecognizedSpeech("отвори facebook", "bg-BG")])
    ptt = PushToTalk(stt, _FakeAssistant(), threading.Lock())
    transcripts: list[str] = []
    ptt.transcript_heard.connect(transcripts.append)
    ptt.trigger()
    assert pump_events(lambda: transcripts == ["отвори facebook"], timeout=3)


def test_push_to_talk_speaks_no_speech_message_when_nothing_heard(qapp):
    stt = _FakeStt(phrases=[])
    tts = _FakeTts()
    assistant = _FakeAssistant(tts=tts)
    ptt = PushToTalk(stt, assistant, threading.Lock())
    ptt.trigger()
    assert _wait_until(lambda: len(tts.spoken) == 1)
    assert "hear" in tts.spoken[0].lower()
    assert assistant.dispatched == []


def test_push_to_talk_emits_listening_then_processing_then_idle(qapp, pump_events):
    stt = _FakeStt(phrases=[RecognizedSpeech("отвори facebook", "bg-BG")])
    ptt = PushToTalk(stt, _FakeAssistant(), threading.Lock())
    states: list[str] = []
    ptt.state_changed.connect(states.append)
    ptt.trigger()
    assert pump_events(lambda: states[-3:] == ["listening", "processing", "idle"], timeout=3)


def test_push_to_talk_emits_idle_even_when_dispatch_raises(qapp, pump_events):
    def _raising_dispatch(text, lang=None):
        raise RuntimeError("boom")

    stt = _FakeStt(phrases=[RecognizedSpeech("отвори facebook", "bg-BG")])
    assistant = _FakeAssistant()
    assistant.dispatch_command = _raising_dispatch
    ptt = PushToTalk(stt, assistant, threading.Lock())
    states: list[str] = []
    ptt.state_changed.connect(states.append)
    ptt.trigger()
    assert pump_events(lambda: states and states[-1] == "idle", timeout=3)


# --- Shared mic lock -----------------------------------------------------------


def test_voice_worker_and_push_to_talk_never_access_the_mic_concurrently(qapp):
    # Both share one SpeechToText/lock, mirroring real usage in app.py.
    # If they ever call listen_once() at the same instant, max_concurrent > 1.
    stt = _FakeStt(phrases=[RecognizedSpeech("jarvis отвори facebook", "bg-BG")] * 5, listen_delay=0.02)
    mic_lock = threading.Lock()
    assistant = _FakeAssistant()
    worker = VoiceWorker(stt, assistant, mic_lock)
    ptt = PushToTalk(stt, assistant, mic_lock)

    worker.start()
    for _ in range(3):
        ptt.trigger()
        time.sleep(0.01)

    assert _wait_until(lambda: stt.listen_calls >= 5, timeout=5)
    worker.stop()

    assert stt.max_concurrent == 1


# --- Voice conversation -------------------------------------------------------


def test_voice_conversation_dispatches_multiple_phrases_without_wake_word(qapp):
    stt = _FakeStt(
        phrases=[
            RecognizedSpeech("сравни rtx 4060 и 4070", "bg-BG"),
            RecognizedSpeech("коя е по-добра за игри", "bg-BG"),
            RecognizedSpeech("спри да слушаш", "bg-BG"),
        ]
    )
    assistant = _FakeAssistant()
    conversation = VoiceConversation(stt, assistant, threading.Lock())

    conversation.trigger()

    assert _wait_until(lambda: assistant.dispatched[-1:] == ["спри да слушаш"], timeout=3)
    assert assistant.dispatched == [
        "сравни rtx 4060 и 4070",
        "коя е по-добра за игри",
        "спри да слушаш",
    ]
    assert assistant.session_active() is False


def test_voice_conversation_emits_heard_transcripts(qapp, pump_events):
    stt = _FakeStt(
        phrases=[
            RecognizedSpeech("сравни rtx 4060 и 4070", "bg-BG"),
            RecognizedSpeech("спри да слушаш", "bg-BG"),
        ]
    )
    conversation = VoiceConversation(stt, _FakeAssistant(), threading.Lock())
    transcripts: list[str] = []
    conversation.transcript_heard.connect(transcripts.append)

    conversation.trigger()

    assert pump_events(lambda: transcripts == ["сравни rtx 4060 и 4070", "спри да слушаш"], timeout=3)


def test_voice_conversation_stops_after_repeated_silence(qapp, pump_events):
    stt = _FakeStt(phrases=[])
    tts = _FakeTts()
    assistant = _FakeAssistant(tts=tts)
    conversation = VoiceConversation(stt, assistant, threading.Lock())
    states: list[str] = []
    conversation.state_changed.connect(states.append)

    conversation.trigger()

    assert pump_events(lambda: states and states[-1] == "idle", timeout=3)
    assert assistant.dispatched == []
    assert tts.spoken == ["I did not hear anything."]


def test_voice_conversation_calls_started_and_stopped_callbacks(qapp, pump_events):
    stt = _FakeStt(phrases=[RecognizedSpeech("спри да слушаш", "bg-BG")])
    started: list[bool] = []
    stopped: list[bool] = []
    conversation = VoiceConversation(
        stt,
        _FakeAssistant(),
        threading.Lock(),
        on_started=lambda: started.append(True),
        on_stopped=lambda: stopped.append(True),
    )

    assert conversation.trigger() is True

    assert started == [True]
    assert pump_events(lambda: stopped == [True], timeout=3)
    assert conversation.running is False


def test_voice_conversation_trigger_returns_false_when_already_running(qapp):
    stt = _FakeStt(phrases=[], listen_delay=0.1)
    conversation = VoiceConversation(stt, _FakeAssistant(), threading.Lock())

    assert conversation.trigger() is True
    assert conversation.trigger() is False

    conversation.stop()
