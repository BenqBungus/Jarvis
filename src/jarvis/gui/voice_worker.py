from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from ..audio.speech_to_text import SpeechToText
from ..voice_assistant import VoiceAssistant
from .speech_service import QuitAwareWorker

logger = logging.getLogger(__name__)

# Fallback for assistant stand-ins without speak_no_speech(); the real
# VoiceAssistant says this in the conversation language.
_NO_SPEECH_MESSAGE = "I did not hear anything."


def _say_no_speech(assistant) -> None:
    speak = getattr(assistant, "speak_no_speech", None)
    if callable(speak):
        speak()
    elif assistant.tts.enabled:
        assistant.tts.speak(_NO_SPEECH_MESSAGE)


class VoiceWorker(QuitAwareWorker):
    """Continuous wake-word listening loop, running off the GUI thread.
    Emits state_changed("idle" | "listening" | "processing") so the tray
    icon / mic-status label can reflect what the mic is doing.

    Uses a short (1s) listen timeout specifically so the loop re-acquires
    mic_lock frequently instead of holding it for the default 5s timeout --
    this bounds (does not eliminate) how long PushToTalk has to wait for the
    mic, since the two must never open sr.Microphone() at the same time.
    Once the app starts quitting the loop stops at its next check and late
    signals are dropped (QuitAwareWorker).
    """

    state_changed = Signal(str)
    transcript_heard = Signal(str)

    def __init__(
        self,
        stt: SpeechToText,
        assistant: VoiceAssistant,
        mic_lock: threading.Lock,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._stt = stt
        self._assistant = assistant
        self._mic_lock = mic_lock
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-voice")

    @property
    def available(self) -> bool:
        return self._stt.available

    def start(self) -> None:
        if not self._stt.available:
            logger.warning("Voice input is not available; continuous listening will not start.")
            return
        if self.quitting:
            return
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def pause(self) -> None:
        self._pause_event.set()
        self._emit("state_changed", "idle")

    def resume(self) -> None:
        self._pause_event.clear()

    def _stopping(self) -> bool:
        return self._stop_event.is_set() or self.quitting

    def _run(self) -> None:
        try:
            with self._mic_lock:
                self._stt.calibrate()
        except Exception:
            logger.exception("Microphone calibration failed")
            self._emit("state_changed", "unclear")
            return
        while not self._stopping():
            if self._pause_event.is_set():
                self._stop_event.wait(0.1)
                continue
            wait_for_speech = getattr(self._assistant.tts, "wait_until_idle", None)
            if wait_for_speech is not None and not wait_for_speech(self._stop_event):
                break
            self._emit("state_changed", "listening")
            try:
                with self._mic_lock:
                    if self._pause_event.is_set() or self._stopping():
                        continue
                    heard = self._stt.listen_once(timeout=1.0, phrase_time_limit=8.0)
            except Exception:
                logger.exception("Microphone capture failed")
                self._emit("state_changed", "unclear")
                self._stop_event.wait(1.0)
                continue
            if self._stopping():
                break
            if self._pause_event.is_set():
                continue
            if heard is None:
                continue
            self._emit("transcript_heard", heard.text)
            self._emit("state_changed", "processing")
            try:
                self._assistant.handle_utterance(heard.text)
            except Exception:  # pragma: no cover - defensive, mirrors BackgroundMonitor._run_loop
                logger.exception("Voice command handling failed")
        self._emit("state_changed", "idle")


class PushToTalk(QuitAwareWorker):
    """One-shot listen-and-dispatch that bypasses the wake-word gate
    entirely: a manual button press IS the deliberate-activation signal.
    Reuses the same VoiceAssistant (and therefore the same confirm_prompts,
    dispatch target, and TextToSpeech) as the continuous VoiceWorker, via
    VoiceAssistant.dispatch_command().
    """

    state_changed = Signal(str)
    transcript_heard = Signal(str)

    def __init__(
        self,
        stt: SpeechToText,
        assistant: VoiceAssistant,
        mic_lock: threading.Lock,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._stt = stt
        self._assistant = assistant
        self._mic_lock = mic_lock
        self._running_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._running_lock.locked()

    @property
    def available(self) -> bool:
        return self._stt.available

    def trigger(self) -> None:
        if not self._stt.available:
            logger.warning("Voice input is not available; push-to-talk ignored.")
            return
        if self.quitting or not self._running_lock.acquire(blocking=False):
            return
        threading.Thread(target=self._run, daemon=True, name="jarvis-push-to-talk").start()

    def _run(self) -> None:
        self._emit("state_changed", "listening")
        try:
            with self._mic_lock:
                heard = self._stt.listen_once(timeout=5.0, phrase_time_limit=8.0)
            if self.quitting:
                return
            if heard is None:
                _say_no_speech(self._assistant)
                return
            self._emit("transcript_heard", heard.text)
            self._emit("state_changed", "processing")
            self._assistant.dispatch_command(heard.text)
        except Exception:  # pragma: no cover - defensive, mirrors BackgroundMonitor._run_loop
            logger.exception("Push-to-talk command handling failed")
        finally:
            self._running_lock.release()
            self._emit("state_changed", "idle")


class VoiceConversation(QuitAwareWorker):
    """Short voice-first conversation loop.

    Unlike continuous wake-word listening, this is explicitly started by the
    user from the GUI, so every heard phrase is treated as intentional until
    the user says a stop phrase, presses Stop Listening, or the mic hears
    silence twice in a row.
    """

    state_changed = Signal(str)
    transcript_heard = Signal(str)

    def __init__(
        self,
        stt: SpeechToText,
        assistant: VoiceAssistant,
        mic_lock: threading.Lock,
        parent: QObject | None = None,
        max_turns: int = 12,
        on_started: Callable[[], None] | None = None,
        on_stopped: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._stt = stt
        self._assistant = assistant
        self._mic_lock = mic_lock
        self._max_turns = max(1, max_turns)
        self._stop_event = threading.Event()
        self._running_lock = threading.Lock()
        self._running = False
        self._on_started = on_started
        self._on_stopped = on_stopped

    @property
    def available(self) -> bool:
        return self._stt.available

    @property
    def running(self) -> bool:
        with self._running_lock:
            return self._running

    def trigger(self) -> bool:
        if not self._stt.available:
            logger.warning("Voice input is not available; voice conversation ignored.")
            return False
        with self._running_lock:
            if self._running or self.quitting:
                return False
            self._running = True
            self._stop_event.clear()
        self._callback(self._on_started)
        threading.Thread(target=self._run, daemon=True, name="jarvis-voice-conversation").start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        self._assistant.end_session()

    def _stopping(self) -> bool:
        return self._stop_event.is_set() or self.quitting

    def _run(self) -> None:
        missed = 0
        turns = 0
        self._assistant.start_session()
        try:
            while not self._stopping() and self._assistant.session_active() and turns < self._max_turns:
                self._emit("state_changed", "listening")
                with self._mic_lock:
                    heard = self._stt.listen_once(timeout=8.0, phrase_time_limit=14.0)
                if self._stopping():
                    break
                if heard is None:
                    missed += 1
                    self._emit("state_changed", "unclear")
                    if missed >= 2:
                        _say_no_speech(self._assistant)
                        break
                    continue
                missed = 0
                turns += 1
                self._emit("transcript_heard", heard.text)
                self._emit("state_changed", "processing")
                result = self._assistant.dispatch_command(heard.text)
                if result.message == "Voice session ended.":
                    break
        except Exception:  # pragma: no cover - defensive, mirrors VoiceWorker._run
            logger.exception("Voice conversation handling failed")
        finally:
            self._assistant.end_session()
            self._emit("state_changed", "idle")
            with self._running_lock:
                self._running = False
            # Never hand the microphone back to wake-word listening once quitting.
            self._callback(self._on_stopped)
