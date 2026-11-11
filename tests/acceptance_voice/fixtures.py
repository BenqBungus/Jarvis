"""Deterministic, fully-mocked fixtures for the acceptance_voice scenario
suite. No real microphone, no real network, no real OpenAI cost -- these
replace `websockets`/`sounddevice` at the module level the same way
tests/test_realtime_transport.py's
test_server_disconnect_cancels_audio_sender_and_releases_devices already
proves works for a real `run_stream()` call, so a scenario here exercises
the actual public entry point, not an internal method in isolation.

Written as reusable *data* (ScenarioSocket takes a plain list of server
event dicts) specifically so a later, separate, opt-in real-hardware
acceptance suite can replay the same scenario event lists against a real
`websockets`/`sounddevice` pair instead of these fakes -- the scenario
*shape* doesn't change, only what's underneath it.
"""

from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

from jarvis.realtime import RealtimeVoiceConfig, RealtimeVoiceSession


class ScenarioSocket:
    """Feeds a scripted list of server event dicts to whatever calls
    `.recv()` / iterates the socket, and records every client message sent
    back for assertions."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.events = iter(events)
        self.sent: list[dict[str, Any]] = []

    def __aiter__(self) -> "ScenarioSocket":
        return self

    async def __anext__(self) -> str:
        try:
            return json.dumps(next(self.events))
        except StopIteration:
            raise StopAsyncIteration

    async def recv(self) -> str:
        return await self.__anext__()

    async def send(self, value: str) -> None:
        self.sent.append(json.loads(value))

    def sent_types(self) -> list[str]:
        return [event.get("type", "") for event in self.sent]


class _FakeAudioStream:
    """Stands in for both sd.RawInputStream and sd.RawOutputStream -- real
    run_stream() never calls .write() on either (both are fully
    callback-driven), so this only needs to track open/close and never
    actually move audio."""

    def __init__(self, **kwargs: Any) -> None:
        self.callback = kwargs.get("callback")
        self.started = True
        self.closed = False

    def __enter__(self) -> "_FakeAudioStream":
        return self

    def __exit__(self, *args: Any) -> None:
        self.closed = True

    def abort(self, **kwargs: Any) -> None:
        pass

    def start(self) -> None:
        self.started = True


class _FakeConnection:
    def __init__(self, socket: ScenarioSocket) -> None:
        self._socket = socket
        self.closed = False

    async def __aenter__(self) -> ScenarioSocket:
        return self._socket

    async def __aexit__(self, *args: Any) -> None:
        self.closed = True


def patch_realtime_transport(monkeypatch, events: list[dict[str, Any]]) -> ScenarioSocket:
    """Wires a ScenarioSocket in place of a real websocket, and a pair of
    _FakeAudioStreams in place of real sounddevice streams, so
    RealtimeVoiceSession.run_stream() can be called for real without ever
    touching a real microphone/speaker or making a real network request."""
    socket = ScenarioSocket(events)
    connection = _FakeConnection(socket)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "websockets", types.SimpleNamespace(connect=lambda url, **kwargs: connection))
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        types.SimpleNamespace(
            RawInputStream=_FakeAudioStream,
            RawOutputStream=_FakeAudioStream,
            # run_stream() gates itself on readiness(), which now calls
            # _audio_devices_available() (a real PortAudio device-table
            # query) -- a fake input+output device here keeps that gate
            # passing without touching any real audio hardware.
            query_devices=lambda: [{"max_input_channels": 2, "max_output_channels": 2}],
        ),
    )
    monkeypatch.setattr("jarvis.realtime.resolve_output_device", lambda: None)
    return socket


def run_session(config: RealtimeVoiceConfig | None = None, *, on_state=None, tool_executor=None,
                timeout: float = 2.0, memory=None, memory_enabled=None):
    """Runs a real RealtimeVoiceSession.run_stream() to completion (the
    session ends on its own once the ScenarioSocket's scripted events run
    out) against whatever patch_realtime_transport() already wired up.
    `memory`/`memory_enabled` pass straight through to RealtimeVoiceSession,
    for scenarios that need to assert on conversation-history commit
    behavior rather than just the live event sequence."""
    session = RealtimeVoiceSession(config, memory=memory, memory_enabled=memory_enabled)
    asyncio.run(asyncio.wait_for(session.run_stream(tool_executor=tool_executor, on_state=on_state), timeout=timeout))
    return session


class StateRecorder:
    """on_state callback that records (state, event) pairs in order, plus
    convenience accessors matching what a scenario actually wants to
    assert -- the observable sequence, not internal call counts."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, state: str, event: dict[str, Any]) -> None:
        self.events.append((state, dict(event)))

    def states(self) -> list[str]:
        return [state for state, _event in self.events]
