from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field

from PySide6.QtCore import QCoreApplication, QObject, Signal

from ..audio.text_to_speech import TextToSpeech
from ..audio.output_device import play_test_tone
from ..privacy import redact_sensitive_text

logger = logging.getLogger(__name__)


class QuitAwareWorker(QObject):
    """Base for objects whose background threads emit Qt signals or call back
    into the app. Once the application starts quitting -- or the Qt object is
    already gone -- late emissions and callbacks are dropped, so a finishing
    thread can never touch torn-down widgets or reopen audio during teardown
    (docs/STABILITY_HANDOFF_2026-09-16.md, item 2)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._quitting = threading.Event()
        app = QCoreApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._quitting.set)

    @property
    def quitting(self) -> bool:
        return self._quitting.is_set()

    def _emit(self, signal_name: str, *args) -> bool:
        if self._quitting.is_set():
            return False
        try:
            getattr(self, signal_name).emit(*args)
        except RuntimeError:  # the Qt object was deleted under a finishing thread
            self._quitting.set()
            return False
        return True

    def _callback(self, callback) -> None:
        if callback is not None and not self._quitting.is_set():
            callback()


@dataclass
class SpeechJob:
    text: str
    lang: str | None = None
    done: threading.Event = field(default_factory=threading.Event)
    spoken: bool = False
    tone: bool = False
    generation: int = 0
    started: bool = False


class SpeechService(QuitAwareWorker):
    """Funnels every spoken message through one queue so nothing ever calls
    TextToSpeech.speak() directly from multiple threads.

    TextToSpeech's internal lock prevents corruption but not blocking:
    speak() holds that lock through the whole runAndWait() playback, so two
    concurrent callers (e.g. a monitor alert landing while the GUI thread is
    reacting to a command result) would have one stall on lock.acquire() for
    the full duration of the other's speech. Routing everything through one
    consumer thread gives strict FIFO ordering and guarantees the GUI thread
    itself never blocks on speech.
    """

    playback_started = Signal(str)
    playback_finished = Signal(bool, str)

    def __init__(self, tts: TextToSpeech, mic_lock=None) -> None:
        super().__init__()
        self._tts = tts
        self._mic_lock = mic_lock
        self._jobs: "queue.Queue[SpeechJob | None]" = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-speech")
        self._stopped = threading.Event()
        self._idle = threading.Event()
        self._idle.set()
        self._pending = 0
        self._pending_lock = threading.Lock()
        self._generation = 0
        self._suspended = False

    def suspend(self) -> None:
        """Drop queued classic speech when a live call takes audio ownership."""
        with self._pending_lock:
            self._suspended = True
            self._generation += 1

    def resume(self) -> None:
        with self._pending_lock:
            if self._quitting.is_set():
                return  # never hand audio back to classic speech during teardown
            self._suspended = False

    def _job_current(self, job: SpeechJob) -> bool:
        with self._pending_lock:
            return not self._suspended and job.generation == self._generation

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        self._jobs.put(None)

    def request_speak(self, text: str, lang: str | None = None) -> SpeechJob | None:
        """Safe from any thread. Never blocks beyond a cheap queue.put()."""
        if text and text.strip() and not self._stopped.is_set():
            job = SpeechJob(text, lang)
            return job if self._enqueue(job) else None
        return None

    def request_tone(self) -> None:
        if not self._stopped.is_set():
            self._enqueue(SpeechJob("Speaker tone", tone=True))

    def _enqueue(self, job: SpeechJob) -> bool:
        with self._pending_lock:
            if self._suspended or self._stopped.is_set() or self._quitting.is_set():
                return False
            job.generation = self._generation
            self._pending += 1
            self._idle.clear()
            self._jobs.put(job)
            return True

    def wait_until_idle(self, stop_event: threading.Event | None = None) -> bool:
        while not self._idle.wait(0.05):
            if self._stopped.is_set() or (stop_event is not None and stop_event.is_set()):
                return False
        return not self._stopped.is_set()

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                return
            detail = ""
            acquired = False
            try:
                if self._mic_lock is not None:
                    while not self._stopped.is_set() and self._job_current(job):
                        acquired = self._mic_lock.acquire(timeout=0.05)
                        if acquired:
                            break
                with self._pending_lock:
                    job.started = (not self._stopped.is_set() and not self._suspended and not self._quitting.is_set()
                                   and job.generation == self._generation)
                if job.started:
                    self._emit("playback_started", job.text)
                    job.spoken = play_test_tone() if job.tone else self._tts.speak(job.text, lang=job.lang)
                    detail = ("Audio sent to the selected speaker." if job.spoken else
                              getattr(self._tts, "last_error", "") or "No audio was played. Check the voice provider and speaker output.")
            except Exception as exc:
                detail = redact_sensitive_text(str(exc)).text
                logger.warning("Speech playback failed: %s", detail)
            finally:
                if acquired:
                    self._mic_lock.release()
                job.done.set()
                with self._pending_lock:
                    self._pending -= 1
                    if self._pending == 0:
                        self._idle.set()
                if not self._stopped.is_set() and job.started:
                    self._emit("playback_finished", job.spoken, detail)

    def as_tts(self) -> "QueuedSpeaker":
        return QueuedSpeaker(self, enabled=self._tts.enabled)


class QueuedSpeaker:
    """Presents the same .enabled / .speak(text, lang=None) interface as
    TextToSpeech, but routes every call through a SpeechService queue
    instead of calling the engine directly.

    Use this (via SpeechService.as_tts()), not the raw TextToSpeech,
    anywhere something tts-shaped is expected -- e.g. VoiceAssistant(tts=
    ...) -- so a voice prompt like "please confirm on screen" stays
    serialized with command-result and monitor-alert speech instead of
    racing them for TextToSpeech's internal lock.
    """

    def __init__(self, speech_service: SpeechService, enabled: bool) -> None:
        self._speech_service = speech_service
        self.enabled = enabled

    def speak(self, text: str, lang: str | None = None) -> bool:
        if not self.enabled or not text or not text.strip():
            return False
        job = self._speech_service.request_speak(text, lang)
        if job is None:
            return False
        # Voice workers must wait for their reply before reopening the mic.
        while not job.done.wait(0.05):
            if self._speech_service._stopped.is_set():
                return False
        return job.spoken

    def wait_until_idle(self, stop_event: threading.Event | None = None) -> bool:
        return self._speech_service.wait_until_idle(stop_event)
