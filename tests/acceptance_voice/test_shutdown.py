"""Scenario 6 of 6: shutdown. RealtimeVoiceWorker.stop() called mid-call
must end the background thread, release the shared mic lock, and let no
exception escape -- exercised at the GUI worker level (not just the
backend session), since that's where "the user closes the app / hangs up"
actually happens. Deterministic/mocked only.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types

from jarvis.gui.realtime_worker import RealtimeVoiceWorker
from jarvis.realtime import RealtimeVoiceConfig, RealtimeVoiceSession


class _NeverEndingSocket:
    """Yields exactly one session.updated event -- enough for run_stream()
    to complete its handshake and reach "listening" -- then behaves like an
    open, idle connection on which the server simply hasn't sent anything
    else yet: every later recv()/__anext__() call blocks until cancelled.
    Distinct from ScenarioSocket (which ends the call once its scripted
    events run out) -- shutdown specifically needs a call that is still
    genuinely in progress when .stop() is called, not one that already
    ended on its own."""

    def __init__(self) -> None:
        self._events = iter([{"type": "session.updated"}])
        self.sent: list[dict] = []

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        try:
            return json.dumps(next(self._events))
        except StopIteration:
            await asyncio.Event().wait()  # never resolves on its own; only cancellation ends this
            raise AssertionError("unreachable")

    async def recv(self) -> str:
        return await self.__anext__()

    async def send(self, value: str) -> None:
        self.sent.append(json.loads(value))


class _Connection:
    def __init__(self, socket: _NeverEndingSocket) -> None:
        self._socket = socket

    async def __aenter__(self) -> _NeverEndingSocket:
        return self._socket

    async def __aexit__(self, *args) -> None:
        pass


class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def abort(self, **kwargs):
        pass

    def start(self):
        pass


def _patch_transport_with_open_ended_socket(monkeypatch, socket: _NeverEndingSocket) -> None:
    # websockets is imported lazily inside run_stream(), so sys.modules must
    # be patched directly (matching fixtures.patch_realtime_transport and
    # test_disconnect_reconnect's own helper) rather than a jarvis.realtime
    # attribute.
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(
        sys.modules, "websockets", types.SimpleNamespace(connect=lambda url, **kwargs: _Connection(socket))
    )
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        types.SimpleNamespace(
            RawInputStream=lambda **kwargs: _FakeStream(),
            RawOutputStream=lambda **kwargs: _FakeStream(),
            query_devices=lambda: [{"max_input_channels": 2, "max_output_channels": 2}],
        ),
    )
    monkeypatch.setattr("jarvis.realtime.resolve_output_device", lambda: None)


def test_stop_ends_a_mid_call_session_cleanly_with_no_escaping_exception(qapp, pump_events, monkeypatch):
    _patch_transport_with_open_ended_socket(monkeypatch, _NeverEndingSocket())

    session = RealtimeVoiceSession(RealtimeVoiceConfig(greeting=""))
    stopped = []
    worker = RealtimeVoiceWorker(session, lambda *args: {}, on_stopped=lambda: stopped.append(True))
    states: list[str] = []
    worker.state_changed.connect(states.append)

    assert worker.start() is True
    assert pump_events(lambda: "listening" in states, timeout=3)  # genuinely mid-call, not still connecting

    worker.stop()

    assert pump_events(lambda: stopped == [True], timeout=3)
    assert pump_events(lambda: not worker.running, timeout=3)
    # A clean, user-initiated stop must never be reported as an error.
    assert states[-1] != "error"


def test_stop_releases_the_shared_mic_lock_for_a_waiting_classic_voice_worker(qapp, pump_events, monkeypatch):
    import threading

    _patch_transport_with_open_ended_socket(monkeypatch, _NeverEndingSocket())
    mic_lock = threading.Lock()

    session = RealtimeVoiceSession(RealtimeVoiceConfig(greeting=""))
    worker = RealtimeVoiceWorker(session, lambda *args: {}, mic_lock=mic_lock)
    states: list[str] = []
    worker.state_changed.connect(states.append)

    assert worker.start() is True
    assert pump_events(lambda: "listening" in states, timeout=3)
    # While the call is active, RealtimeVoiceWorker holds mic_lock for its
    # whole duration (see tests/test_gui_voice_realtime_mic_lock.py) -- a
    # classic-voice-style acquire attempt must not succeed yet.
    assert mic_lock.acquire(timeout=0.05) is False

    worker.stop()
    assert pump_events(lambda: not worker.running, timeout=3)

    # Once stopped, the lock must be released for someone else to use.
    assert mic_lock.acquire(timeout=1.0) is True
    mic_lock.release()
