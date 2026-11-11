"""Voice teardown and language fences (docs/STABILITY_HANDOFF_2026-09-16.md,
items 2 and 3). The shared test QApplication is never actually quit here --
that would fire every aboutToQuit slot other tests connected -- so quitting is
simulated through the same event the aboutToQuit connection sets."""
from __future__ import annotations

import asyncio
import threading
import time

import shiboken6

from jarvis.audio.speech_to_text import RecognizedSpeech
from jarvis.gui import realtime_worker as realtime_worker_module
from jarvis.gui.realtime_worker import RealtimeVoiceWorker
from jarvis.gui.speech_service import SpeechService
from jarvis.gui.voice_worker import PushToTalk, VoiceConversation
from jarvis.models import CommandResult
from jarvis.voice_assistant import VoiceAssistant


def _wait_until(condition, timeout: float = 3.0) -> bool:
    deadline = time.time() + timeout
    while not condition() and time.time() < deadline:
        time.sleep(0.005)
    return condition()


class _Tts:
    enabled = True

    def __init__(self) -> None:
        self.spoken: list[tuple[str, str | None]] = []

    def speak(self, text, lang=None) -> bool:
        self.spoken.append((text, lang))
        return True


class _Stt:
    available = True

    def __init__(self, phrases=None) -> None:
        self._phrases = list(phrases or [])

    def calibrate(self, duration: float = 0.5) -> None:
        pass

    def listen_once(self, timeout=None, phrase_time_limit=None):
        return self._phrases.pop(0) if self._phrases else None


class _Session:
    """A Realtime session stand-in; run_stream only records that it ran."""

    def __init__(self, during_call=None) -> None:
        self.config = None
        self.calls = 0
        self._during_call = during_call

    def readiness(self) -> dict:
        return {"ready": True, "missing": []}

    def set_input_muted(self, muted: bool) -> None:
        pass

    def request_interrupt(self) -> None:
        pass

    async def run_stream(self, tool_executor=None, on_state=None) -> None:
        self.calls += 1
        if self._during_call is not None:
            self._during_call()


def _assistant(language: str) -> VoiceAssistant:
    return VoiceAssistant(None, _Stt(), _Tts(), dispatch=lambda text: CommandResult(True, "ok"),
                          spoken_language=language)


def test_late_signals_are_dropped_once_the_app_is_quitting(qapp):
    worker = RealtimeVoiceWorker(_Session(), lambda name, arguments: {})
    seen: list[str] = []
    worker.state_changed.connect(seen.append)
    assert not worker.quitting and worker._emit("state_changed", "listening")
    worker._quitting.set()
    worker._on_realtime_state("speaking", {})
    worker._emit("state_changed", "idle")
    assert seen == ["listening"]
    assert worker.start() is False  # no new call once quitting


def test_emitting_after_the_qt_object_is_deleted_does_not_raise(qapp):
    worker = PushToTalk(_Stt(), _assistant("en"), threading.Lock())
    shiboken6.delete(worker)
    assert worker._emit("state_changed", "idle") is False
    assert worker.quitting


def test_stop_while_the_call_is_starting_never_opens_the_session(qapp, monkeypatch):
    session = _Session()
    worker = RealtimeVoiceWorker(session, lambda name, arguments: {})
    real_run = asyncio.run

    def stop_then_run(coroutine):
        worker.stop()  # Stop lands after the start checks, before the loop exists
        return real_run(coroutine)

    monkeypatch.setattr(realtime_worker_module.asyncio, "run", stop_then_run)
    assert worker.start()
    assert _wait_until(lambda: not worker.running)
    assert session.calls == 0


def test_a_call_ending_after_quit_does_not_hand_audio_back(qapp):
    handed_back: list[bool] = []
    stopped: list[bool] = []
    worker = RealtimeVoiceWorker(_Session(), lambda name, arguments: {},
                                 on_stopped=lambda: handed_back.append(True))
    worker._session._during_call = worker._quitting.set  # the app quits mid-call
    worker.session_stopped.connect(lambda: stopped.append(True))
    assert worker.start()
    assert _wait_until(lambda: not worker.running)
    qapp.processEvents()
    assert handed_back == [] and stopped == []


def test_voice_conversation_does_not_resume_wake_word_after_quit(qapp):
    resumed: list[bool] = []
    conversation = VoiceConversation(_Stt([RecognizedSpeech("отвори youtube", "bg-BG")]), _assistant("bg"),
                                     threading.Lock(), on_stopped=lambda: resumed.append(True))
    conversation._quitting.set()
    assert conversation.trigger() is False
    assert resumed == []


def test_speech_service_takes_no_new_speech_and_keeps_audio_after_quit(qapp):
    service = SpeechService(_Tts())
    service._quitting.set()
    assert service.request_speak("Здравей") is None
    service.suspend()
    service.resume()
    assert service._suspended  # a finishing live call cannot hand speech back


def test_push_to_talk_says_it_heard_nothing_in_bulgarian(qapp):
    assistant = _assistant("bg")
    push_to_talk = PushToTalk(_Stt(), assistant, threading.Lock())
    push_to_talk.trigger()
    assert _wait_until(lambda: assistant.tts.spoken)
    assert assistant.tts.spoken == [("Не чух нищо.", "bg")]


def test_auto_language_no_speech_prompt_follows_the_last_command(qapp):
    fresh = _assistant("auto")
    fresh.speak_no_speech()
    assert fresh.tts.spoken[-1] == ("I did not hear anything.", "en")
    assistant = _assistant("auto")
    assistant.dispatch_command("отвори youtube")
    assistant.speak_no_speech()
    assert assistant.tts.spoken[-1] == ("Не чух нищо.", "bg")
