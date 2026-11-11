from __future__ import annotations

import asyncio
from contextlib import AbstractContextManager, nullcontext
import logging
import threading
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal

from ..realtime import RealtimeToolExecutor, RealtimeVoiceSession
from ..privacy import redact_sensitive_text
from .speech_service import QuitAwareWorker

logger = logging.getLogger(__name__)


class _ReleaseOnExit:
    def __init__(self, release: Callable[[], None]) -> None:
        self._release = release

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._release()


class RealtimeVoiceWorker(QuitAwareWorker):
    """Runs OpenAI Realtime voice in a background thread for the GUI. Late
    events after the app starts quitting are dropped (QuitAwareWorker)."""

    state_changed = Signal(str)
    detail_changed = Signal(str)
    tool_error_occurred = Signal(str)
    user_transcript_received = Signal(str)
    assistant_transcript_received = Signal(str)
    transcript_completed = Signal(str, str)
    session_stopped = Signal()
    audio_level_changed = Signal(float)
    input_muted_changed = Signal(bool)
    keyword_interrupt_changed = Signal(bool, str)

    def __init__(
        self,
        session: RealtimeVoiceSession,
        tool_executor: RealtimeToolExecutor,
        *,
        on_started: Callable[[], None] | None = None,
        on_stopped: Callable[[], None] | None = None,
        mic_lock: AbstractContextManager | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._tool_executor = tool_executor
        self._on_started = on_started
        self._on_stopped = on_stopped
        self._mic_lock = mic_lock
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._running = False
        self._stop_requested = threading.Event()
        self._transcripts: dict[str, str] = {}

    @property
    def running(self) -> bool:
        with self._lock:
            return self._running

    def start(self) -> bool:
        if self.quitting:
            return False
        status = self._session.readiness()
        if not status["ready"]:
            self._emit("detail_changed", "Realtime voice is not ready. Missing: " + ", ".join(status["missing"]))
            self._emit("state_changed", "error")
            return False
        with self._lock:
            if self._running:
                return False
            self._running = True
            self._stop_requested.clear()
            self._transcripts.clear()
            self._thread = threading.Thread(target=self._run_thread, daemon=True, name="jarvis-realtime-voice")
        self.set_input_muted(False)
        self._callback(self._on_started)
        self._thread.start()
        return True

    def configure(self, config) -> bool:
        with self._lock:
            if self._running:
                return False
            self._session.config = config
        return True

    def update_live_config(self, config) -> bool:
        """A running call switches language at once; otherwise the next call
        uses `config`. True when a call was running."""
        with self._lock:
            running = self._running
            if not running:
                self._session.config = config
        if running:
            self._session.update_live_config(config)
        return running

    def set_input_muted(self, muted: bool) -> None:
        self._session.set_input_muted(muted)
        self._emit("input_muted_changed", muted)

    def input_muted(self) -> bool:
        return bool(self._session.input_muted)

    def is_speaking(self) -> bool:
        """A running call is playing Jarvis's reply."""
        return self.running and self._session.is_speaking()

    def interrupt_speech(self) -> None:
        if self.running:
            self._session.request_interrupt()

    def stop(self) -> None:
        self._stop_requested.set()
        loop = self._loop
        task = self._task
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # Session already closed between the snapshots above.

    def _run_thread(self) -> None:
        self._emit("state_changed", "connecting")
        failed = False
        try:
            mic_context = self._wait_for_mic_context()
            if mic_context is None:
                return
            with mic_context:
                if self._stop_requested.is_set() or self.quitting:
                    return
                asyncio.run(self._run_session())
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover - depends on live network/audio devices.
            failed = True
            message = redact_sensitive_text(str(exc)).text
            logger.warning("Realtime voice worker failed: %s", message)
            self._emit("detail_changed", message)
            self._emit("state_changed", "error")
        finally:
            with self._lock:
                self._running = False
                self._loop = None
                self._task = None
            # No hand-back of the microphone/speaker to classic voice once quitting.
            self._callback(self._on_stopped)
            if not failed:
                self._emit("state_changed", "idle")
            self._emit("session_stopped")

    def _wait_for_mic_context(self) -> AbstractContextManager | None:
        if self._mic_lock is None:
            return nullcontext()
        acquire = getattr(self._mic_lock, "acquire", None)
        release = getattr(self._mic_lock, "release", None)
        if not callable(acquire) or not callable(release):
            return self._mic_lock

        while not self._stop_requested.is_set():
            try:
                acquired = bool(acquire(timeout=0.1))
            except TypeError:
                acquired = bool(acquire(False))
                if not acquired:
                    self._stop_requested.wait(0.1)
            if acquired:
                return _ReleaseOnExit(release)
        return None

    async def _run_session(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        # stop() sets the flag before reading _loop/_task; checking after
        # publishing them closes the window where a Stop pressed while the call
        # was starting found nothing to cancel and the microphone stayed open.
        if self._stop_requested.is_set() or self.quitting:
            return
        await self._session.run_stream(
            tool_executor=self._tool_executor,
            on_state=self._on_realtime_state,
        )

    def _on_realtime_state(self, state: str, event: dict[str, Any]) -> None:
        if state == "keyword_interrupt_status":
            detail = str(event.get("detail", ""))
            self._emit("keyword_interrupt_changed", bool(event.get("available")), detail)
            if detail:
                self._emit("detail_changed", detail)
            return
        if state == "tool_error":
            # Emits both signals deliberately: detail_changed keeps today's
            # behavior working unchanged for whoever is already connected to
            # it (app.py, which Claude cannot edit); tool_error_occurred is
            # the new, distinct signal a caller can use to render this as a
            # persistent error rather than routine, auto-clearing status
            # text. See docs/claude/INTEGRATION_REQUESTS.md for the one-line
            # app.py wiring this needs to actually reach MainWindow.
            message = redact_sensitive_text(str(event.get("message", "Tool request failed"))).text
            self._emit("detail_changed", message)
            self._emit("tool_error_occurred", message)
            return
        if state == "audio_level":
            self._emit("audio_level_changed", max(float(event.get("input", 0)), float(event.get("output", 0))))
            return
        if state in {"assistant_transcript_delta", "assistant_transcript_done"}:
            key = str(event.get("item_id", "current"))
            if state == "assistant_transcript_delta":
                self._transcripts[key] = self._transcripts.get(key, "") + str(event.get("delta", ""))
                self._emit("assistant_transcript_received", self._transcripts[key])
            else:
                text = str(event.get("transcript") or self._transcripts.get(key, ""))
                self._transcripts.pop(key, None)
                self._emit("assistant_transcript_received", text)
                self._emit("transcript_completed", "Jarvis", text)
            return
        if state == "user_transcript":
            text = str(event.get("transcript", "")).strip()
            if text:
                self._emit("detail_changed", text)
                self._emit("user_transcript_received", text)
                self._emit("transcript_completed", "You", text)
            return
        mapped = _map_state(state)
        self._emit("state_changed", mapped)
        detail = _detail_for_state(state, event)
        if detail:
            self._emit("detail_changed", detail)
            if state == "user_transcript":
                self._emit("user_transcript_received", detail)
            elif state == "assistant_transcript_delta":
                self._emit("assistant_transcript_received", detail)


def _map_state(state: str) -> str:
    if state in {"connecting", "listening", "thinking", "speaking", "interrupted", "error"}:
        return state
    if state == "tool_call":
        return "thinking"
    if state == "user_transcript":
        return "listening"
    if state == "assistant_transcript_delta":
        return "speaking"
    return state


def _detail_for_state(state: str, event: dict[str, Any]) -> str:
    if state == "tool_call":
        return f"Running tool: {event.get('name', 'unknown')}"
    if state == "user_transcript":
        return str(event.get("transcript", "")).strip()
    if state == "assistant_transcript_delta":
        return str(event.get("delta", "")).strip()
    if state == "error":
        error = event.get("error", event)
        return str(error)
    return ""
