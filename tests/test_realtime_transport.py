from __future__ import annotations

import asyncio
import base64
import json

import pytest

from jarvis.audio.realtime_playback import RealtimePlayback
from jarvis.realtime import RealtimeVoiceSession


class Socket:
    def __init__(self, events):
        self.events = iter(events)
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return json.dumps(next(self.events))
        except StopIteration:
            raise StopAsyncIteration

    async def recv(self):
        return await self.__anext__()

    async def send(self, value):
        self.sent.append(json.loads(value))


class Speaker:
    def __init__(self):
        self.restarts = 0

    def abort(self, **kwargs):
        pass

    def start(self):
        self.restarts += 1

    def write(self, _chunk):
        raise AssertionError("WebSocket receiver must never block on speaker writes")


def test_session_waits_for_configuration_acknowledgement():
    socket = Socket([{"type": "session.created"}, {"type": "session.updated"}])
    asyncio.run(RealtimeVoiceSession()._wait_for_session(socket))


def test_bad_configuration_reports_error_instead_of_listening():
    socket = Socket([{"type": "error", "error": {"code": "bad_model", "message": "Unavailable model"}}])
    with pytest.raises(RuntimeError, match="bad_model"):
        asyncio.run(RealtimeVoiceSession()._wait_for_session(socket))


def test_barge_in_drops_buffered_and_late_audio_and_truncates_context():
    delta = {"type": "response.output_audio.delta", "item_id": "answer", "delta": base64.b64encode(b"\x01\x02" * 2400).decode()}
    socket = Socket([delta, {"type": "input_audio_buffer.speech_started"}, delta])
    playback = RealtimePlayback()
    speaker = Speaker()
    asyncio.run(RealtimeVoiceSession()._receive_events(socket, speaker, playback=playback, tool_executor=None, on_state=None))
    assert speaker.restarts == 1
    assert not playback.pending
    assert socket.sent == [{"type": "conversation.item.truncate", "item_id": "answer", "content_index": 0, "audio_end_ms": 0}]


def test_audio_done_does_not_claim_playback_has_finished():
    socket = Socket([
        {"type": "response.output_audio.delta", "item_id": "answer", "delta": base64.b64encode(b"\x01\x02" * 2400).decode()},
        {"type": "response.done", "response": {"status": "completed"}},
    ])
    states = []
    asyncio.run(RealtimeVoiceSession()._receive_events(socket, Speaker(), playback=RealtimePlayback(),
                tool_executor=None, on_state=lambda state, event: states.append(state)))
    assert states == ["speaking"]


def test_malformed_tool_arguments_are_not_executed():
    socket = Socket([])
    called = []
    asyncio.run(RealtimeVoiceSession()._maybe_execute_tool_call(socket, {"item": {
        "type": "function_call", "name": "disable_internet", "call_id": "1", "arguments": "broken",
    }}, tool_executor=lambda *args: called.append(args), on_state=None))
    assert not called
    assert json.loads(socket.sent[0]["item"]["output"])["ok"] is False


@pytest.mark.parametrize("interrupted", [False, True])
def test_cancelled_or_interrupted_responses_cannot_dispatch_tools(interrupted):
    events = [{"type": "response.created", "response": {"id": "old"}}]
    if interrupted:
        events.append({"type": "input_audio_buffer.speech_started"})
    events.append({"type": "response.done", "response": {"id": "old",
        "status": "completed" if interrupted else "cancelled", "output": [{
            "type": "function_call", "name": "open_url", "call_id": "call1", "arguments": "{}"}]}})
    calls = []
    session = RealtimeVoiceSession()

    async def dispatch(*args):
        calls.append(args)

    session._respond_to_tools = dispatch

    async def consume():
        tasks = set()
        await session._consume_events(Socket(events), Speaker(), playback=RealtimePlayback(),
                                      tool_executor=None, on_state=None, tool_tasks=tasks)
        if tasks:
            await asyncio.gather(*tasks)

    asyncio.run(consume())
    assert not calls


def test_server_disconnect_cancels_audio_sender_and_releases_devices(monkeypatch):
    import sys
    from types import SimpleNamespace

    socket = Socket([{"type": "session.updated"}])
    closed = []

    class Connection:
        async def __aenter__(self):
            return socket

        async def __aexit__(self, *args):
            closed.append("socket")

    def connect(url, *, additional_headers):
        return Connection()

    class Stream(Speaker):
        def __init__(self, **kwargs):
            super().__init__()
            self.callback = kwargs.get("callback")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            closed.append("audio")

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "websockets", SimpleNamespace(connect=connect))
    monkeypatch.setitem(
        sys.modules,
        "sounddevice",
        SimpleNamespace(
            RawInputStream=Stream,
            RawOutputStream=Stream,
            # run_stream() gates on readiness(), which now probes real
            # device availability via query_devices() -- fake one usable
            # input+output device so this stream-lifecycle test (unrelated
            # to readiness) isn't blocked by it.
            query_devices=lambda: [{"max_input_channels": 2, "max_output_channels": 2}],
        ),
    )
    monkeypatch.setattr("jarvis.realtime.resolve_output_device", lambda: None)
    asyncio.run(asyncio.wait_for(RealtimeVoiceSession().run_stream(), timeout=1))
    assert closed.count("audio") == 2
    assert closed[-1] == "socket"


async def consume_events(session, socket):
    tasks = set()
    await session._consume_events(socket, Speaker(), playback=RealtimePlayback(),
                                  tool_executor=None, on_state=None, tool_tasks=tasks)
    if tasks:
        await asyncio.gather(*tasks)


def test_busy_response_does_not_delay_tool_outputs_and_coalesces_spoken_followup():
    async def scenario():
        session = RealtimeVoiceSession()
        session._response_busy = True
        socket = Socket([])
        for call_id in ("one", "two"):
            await session._maybe_execute_tool_call(socket, {"item": {
                "type": "function_call", "name": "get_active_task_status", "call_id": call_id,
                "arguments": "{}",
            }}, tool_executor=lambda *_: {"ok": True}, on_state=None)
        assert [event["item"]["call_id"] for event in socket.sent] == ["one", "two"]
        assert session._pending_tool_response
        socket.events = iter([{"type": "response.done", "response": {"status": "completed"}}])
        await consume_events(session, socket)
        assert [event["type"] for event in socket.sent].count("response.create") == 1
        assert session._response_busy  # Reserve the response before the server acknowledges it.
        await session._flush_tool_response(socket)
        assert len(socket.sent) == 3

    asyncio.run(scenario())


def test_tool_summary_waits_for_user_speech_and_automatic_vad_response():
    async def scenario():
        session = RealtimeVoiceSession()
        socket = Socket([{"type": "input_audio_buffer.speech_started"}])
        await consume_events(session, socket)
        await session._request_tool_response(socket)
        assert not socket.sent
        socket.events = iter([{"type": "input_audio_buffer.speech_stopped"}])
        await consume_events(session, socket)
        await session._flush_tool_response(socket)
        assert not socket.sent
        socket.events = iter([{"type": "response.created", "response": {"id": "vad"}}])
        await consume_events(session, socket)
        assert not socket.sent
        socket.events = iter([{"type": "response.done", "response": {"id": "vad", "status": "completed"}}])
        await consume_events(session, socket)
        assert socket.sent == [{"type": "response.create"}]

    asyncio.run(scenario())


def test_response_collision_waits_for_current_response_instead_of_ending_call():
    async def scenario():
        session = RealtimeVoiceSession()
        socket = Socket([{"type": "error", "error": {"code": "conversation_already_has_active_response"}}])
        await consume_events(session, socket)
        assert not socket.sent  # No immediate retry loop.
        assert session._pending_tool_response
        socket.events = iter([{"type": "response.done", "response": {"status": "completed"}}])
        await consume_events(session, socket)
        assert socket.sent == [{"type": "response.create"}]

    asyncio.run(scenario())


@pytest.mark.parametrize("code", ["invalid_api_key", "insufficient_quota", "unknown_error"])
def test_other_live_errors_still_surface(code):
    socket = Socket([{"type": "error", "error": {"code": code, "message": "Cannot continue"}}])
    with pytest.raises(RuntimeError, match=code):
        asyncio.run(consume_events(RealtimeVoiceSession(), socket))


def test_failed_summary_send_releases_response_reservation():
    class DisconnectedSocket(Socket):
        async def send(self, value):
            raise ConnectionError("Disconnected")

    session = RealtimeVoiceSession()
    with pytest.raises(ConnectionError):
        asyncio.run(session._request_tool_response(DisconnectedSocket([])))
    assert session._pending_tool_response
    assert not session._response_busy


def test_long_tool_does_not_block_live_transcripts_status_or_cancellation():
    async def scenario():
        class LiveSocket(Socket):
            def __init__(self):
                super().__init__([])
                self.incoming = asyncio.Queue()
                self.outputs = asyncio.Queue()

            async def __anext__(self):
                event = await self.incoming.get()
                if event is None:
                    raise StopAsyncIteration
                return json.dumps(event)

            async def send(self, value):
                await super().send(value)
                event = json.loads(value)
                if event["type"] == "conversation.item.create":
                    await self.outputs.put(event["item"])

            async def tool_turn(self, name):
                await self.incoming.put({"type": "response.created", "response": {"id": name}})
                await self.incoming.put({"type": "response.done", "response": {
                    "id": name, "status": "completed", "output": [{"type": "function_call",
                    "name": name, "call_id": name, "arguments": "{}"}]}})

        socket = LiveSocket()
        started, release = asyncio.Event(), asyncio.Event()
        states = []

        async def execute(name, _arguments):
            if name == "run_autonomous_task":
                started.set()
                await release.wait()
                return {"ok": False, "cancelled": True}
            if name == "cancel_task":
                release.set()
                return {"ok": True}
            return {"ok": True, "active": not release.is_set(), "progress": "Checking sources"}

        session = RealtimeVoiceSession()
        receiver = asyncio.create_task(session._receive_events(socket, Speaker(), playback=RealtimePlayback(),
                                       tool_executor=execute, on_state=lambda state, event: states.append(state)))
        try:
            await socket.tool_turn("run_autonomous_task")
            await asyncio.wait_for(started.wait(), 1)
            await socket.incoming.put({"type": "conversation.item.input_audio_transcription.completed",
                                       "transcript": "How is it going?"})
            await socket.tool_turn("get_active_task_status")
            status = await asyncio.wait_for(socket.outputs.get(), 1)
            assert status["call_id"] == "get_active_task_status"
            assert json.loads(status["output"])["active"] is True
            assert "user_transcript" in states
            assert not release.is_set()
            await socket.tool_turn("cancel_task")
            outputs = [await asyncio.wait_for(socket.outputs.get(), 1) for _ in range(2)]
            assert {item["call_id"] for item in outputs} == {"cancel_task", "run_autonomous_task"}
        finally:
            release.set()
            await socket.incoming.put(None)
            await asyncio.wait_for(receiver, 1)

    asyncio.run(scenario())


@pytest.mark.parametrize("keyword", [False, True])
def test_manual_interrupt_stops_audio_drops_late_transcript_and_keeps_call_alive(keyword):
    async def scenario():
        session = RealtimeVoiceSession()
        playback, speaker = RealtimePlayback(), Speaker()
        session._active_response = "old"
        session._response_busy = True
        playback.enqueue("answer", 0, b"\x01\x20" * 2400)
        socket = Socket([])
        states = []
        callback = lambda state, event: states.append(state)
        if keyword:
            from types import SimpleNamespace
            session._playback = playback
            session._keyword_listener = SimpleNamespace(available=True, error="")
            session._keyword_heard(session._reply_generation)
        else:
            session.request_interrupt()
        watcher = asyncio.create_task(session._watch_playback(playback, callback, socket, speaker))
        try:
            for _ in range(20):
                if socket.sent:
                    break
                await asyncio.sleep(0.01)
            assert socket.sent[0] == {"type": "response.cancel", "response_id": "old"}
            assert socket.sent[1]["type"] == "conversation.item.truncate"
            assert not playback.pending
            assert speaker.restarts == 1
            assert "interrupted" in states
            socket.events = iter([
                {"type": "response.output_audio_transcript.done", "response_id": "old", "item_id": "answer", "transcript": "Stale greeting"},
                {"type": "error", "error": {"code": "response_cancel_not_active"}},
                {"type": "response.done", "response": {"id": "old", "status": "cancelled"}},
                {"type": "conversation.item.input_audio_transcription.completed", "transcript": "Next question"},
            ])
            await session._receive_events(socket, speaker, playback=playback, tool_executor=None, on_state=callback)
            assert "assistant_transcript_done" not in states
            assert "user_transcript" in states
            assert not session._response_busy
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

    asyncio.run(scenario())


def test_late_completion_of_interrupted_response_does_not_release_new_response_slot():
    session = RealtimeVoiceSession()
    socket = Socket([
        {"type": "response.created", "response": {"id": "old"}},
        {"type": "input_audio_buffer.speech_started"},
        {"type": "response.created", "response": {"id": "new"}},
        {"type": "response.done", "response": {"id": "old", "status": "cancelled"}},
    ])
    asyncio.run(consume_events(session, socket))
    assert session._active_response == "new"
    assert session._response_busy
