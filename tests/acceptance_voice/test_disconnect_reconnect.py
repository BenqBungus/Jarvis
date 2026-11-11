"""Scenario 5 of 6: disconnect/reconnect. A dropped connection mid-call
must propagate as a clean, catchable failure, and a fresh run_stream() call
afterward must reconnect and reach a normal "listening" state with no
leftover state from the previous, dropped call. Deterministic/mocked only.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from jarvis.realtime import RealtimeVoiceConfig, RealtimeVoiceSession

from .fixtures import ScenarioSocket, StateRecorder, patch_realtime_transport, run_session


class _DroppingSocket(ScenarioSocket):
    """Behaves like a normal ScenarioSocket until its scripted events run
    out, then raises instead of ending the stream normally -- standing in
    for a real dropped connection (e.g. a network blip) rather than a
    graceful server-side close."""

    async def __anext__(self) -> str:
        try:
            return await super().__anext__()
        except StopAsyncIteration:
            raise ConnectionError("Connection dropped")

    async def recv(self) -> str:
        return await self.__anext__()


class _Connection:
    def __init__(self, socket: ScenarioSocket) -> None:
        self._socket = socket

    async def __aenter__(self) -> ScenarioSocket:
        return self._socket

    async def __aexit__(self, *args) -> None:
        pass


def _patch_transport_with_dropping_socket(monkeypatch, socket: _DroppingSocket) -> None:
    # Same sounddevice/env setup as patch_realtime_transport, but with
    # websockets.connect wired to this specific dropping socket instead of
    # a normal one -- websockets is imported lazily inside run_stream(), so
    # patching sys.modules (not a jarvis.realtime attribute) is required,
    # matching patch_realtime_transport's own approach.
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


class _FakeStream:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def abort(self, **kwargs):
        pass

    def start(self):
        pass


def test_a_dropped_connection_propagates_as_a_clean_catchable_failure(monkeypatch):
    socket = _DroppingSocket([{"type": "session.updated"}])
    _patch_transport_with_dropping_socket(monkeypatch, socket)

    with pytest.raises(ConnectionError, match="Connection dropped"):
        asyncio.run(asyncio.wait_for(RealtimeVoiceSession(RealtimeVoiceConfig(greeting="")).run_stream(), timeout=2))


def test_a_fresh_session_reconnects_cleanly_after_a_previous_disconnect(monkeypatch):
    config = RealtimeVoiceConfig(greeting="")

    # First call: connection drops.
    dropping_socket = _DroppingSocket([{"type": "session.updated"}])
    _patch_transport_with_dropping_socket(monkeypatch, dropping_socket)
    with pytest.raises(ConnectionError):
        asyncio.run(asyncio.wait_for(RealtimeVoiceSession(config).run_stream(), timeout=2))

    # Second call: a normal, independent, successful reconnect -- no
    # leftover interrupted-item/response state or stuck _response_busy from
    # the previous, dropped session (a fresh RealtimeVoiceSession instance
    # starts with clean state, and run_stream() itself also resets its own
    # turn-scoped bookkeeping at the top of every call).
    patch_realtime_transport(monkeypatch, [{"type": "session.updated"}])
    recorder = StateRecorder()
    second_session = run_session(config, on_state=recorder)

    assert "listening" in recorder.states()
    assert second_session._response_busy is False
    assert not second_session._interrupted_items
    assert not second_session._interrupted_responses
