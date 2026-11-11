"""Gmail-flavored voice acceptance scenarios (docs/GMAIL_CLAUDE_HANDOFF.md
Priority 3, design notes in docs/claude/GMAIL_VOICE_STATUS.md).

Uses a mocked tool_executor shaped exactly like the real gmail_* tool outputs
Codex's gmail.py/realtime.tool_executor_from_router() actually produce
(confirmed by reading that code directly) -- never a real GmailService or
router, which stay Codex's to test. Deterministic/mocked only: no real
mailbox, microphone, or paid provider call.

Tool-call mechanics (search/read/advise, denial, expiry, the private-content
session flag) are exercised via direct _maybe_execute_tool_call/
_respond_to_tools calls, matching tests/acceptance_voice/test_tool_request.py's
own documented reasoning: _receive_events() cancels any still-pending tool
task once the event stream ends, so scripting a full run_stream() socket to
reliably win that race would be flaky, not a meaningful signal. Interruption
is exercised through a full scripted run_session(), matching
test_interruption.py, since that mechanism is genuinely about the live event
stream, not the tool call itself -- and is already proven content-agnostic
(it keys off item_id/response_id, never message content).
"""

from __future__ import annotations

import asyncio
import base64
import json

from jarvis.realtime import RealtimeVoiceConfig, RealtimeVoiceSession

from .fixtures import StateRecorder, patch_realtime_transport, run_session


class _RecordingSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, value: str) -> None:
        self.sent.append(json.loads(value))


def _function_call(name: str, arguments: dict, call_id: str = "call-1") -> dict:
    return {"type": "function_call", "name": name, "call_id": call_id, "arguments": json.dumps(arguments)}


# --- Realistic mocked gmail_* tool outputs, matching gmail.py's actual shapes ---


def _search_result(selection_id: str, spoken: str) -> dict:
    return {
        "ok": True,
        "message": "BEGIN_UNTRUSTED_WEB_CONTENT gmail_headers\n" + spoken + "\nEND_UNTRUSTED_WEB_CONTENT gmail_headers",
        "metadata": {"private_content": True, "read_only": True, "tool_category": "gmail",
                     "selection_id": selection_id, "count": 2, "gmail_spoken_text": spoken},
    }


def _read_result(spoken: str, *, business: bool = False) -> dict:
    return {
        "ok": True,
        "message": "AI analysis (not shown to the user directly in this test).",
        "metadata": {"private_content": True, "tool_category": "gmail", "business_advice": business,
                     "gmail_spoken_text": spoken},
    }


def _denied_result(name: str) -> dict:
    # Matches RealtimeVoiceSession.tool_executor_from_router's own denial
    # branch exactly (realtime.py): built before GmailService ever runs, so
    # metadata is empty -- confirmed by reading models.CommandResult's
    # metadata default (an empty dict) and tool_executor_from_router's
    # inline CommandResult(...) call, which passes no metadata kwarg.
    return {"ok": False, "message": f"{name} cancelled.", "confirmed": False,
            "requires_confirmation": True, "metadata": {}}


def _expired_selection_result() -> dict:
    # Matches GmailService.read()'s real GmailError message and _result()'s
    # unconditional private_content=True (gmail.py).
    return {"ok": False, "message": "Gmail selection changed or expired. Search again; no email was read.",
            "metadata": {"private_content": True, "read_only": True}}


def _dispatch(session: RealtimeVoiceSession, name: str, arguments: dict, result: dict, call_id: str = "call-1") -> _RecordingSocket:
    socket = _RecordingSocket()
    asyncio.run(session._maybe_execute_tool_call(
        socket, {"item": _function_call(name, arguments, call_id)},
        tool_executor=lambda _name, _arguments: result, on_state=None,
    ))
    return socket


def _spoken_of(socket: _RecordingSocket) -> str:
    output = json.loads(socket.sent[0]["item"]["output"])
    return output["metadata"]["gmail_spoken_text"]


# --- Search unread mail ---


def test_search_unread_mail_in_english():
    session = RealtimeVoiceSession()
    spoken = "1. Board meeting | ceo@example.com | Tue. 2. Invoice due | billing@example.com | Wed."
    socket = _dispatch(session, "gmail_search", {"query": "in:inbox is:unread", "limit": 5},
                       _search_result("sel-en", spoken))

    output = json.loads(socket.sent[0]["item"]["output"])
    assert output["ok"] is True
    assert output["metadata"]["selection_id"] == "sel-en"
    assert _spoken_of(socket) == spoken
    assert session._session_touched_private_content is True


def test_search_unread_mail_in_bulgarian():
    # Tool-call mechanics don't depend on conversation_language -- BG/EN
    # coverage here proves the same private-content plumbing holds regardless
    # of which language the surrounding conversation is configured for.
    session = RealtimeVoiceSession(RealtimeVoiceConfig(conversation_language="bg"))
    spoken = "1. Заседание на борда | ceo@example.com | вт. 2. Фактура | billing@example.com | ср."
    socket = _dispatch(session, "gmail_search", {"query": "in:inbox is:unread", "limit": 5},
                       _search_result("sel-bg", spoken))

    assert _spoken_of(socket) == spoken
    assert session._session_touched_private_content is True
    assert session.config.conversation_language == "bg"


# --- Select email 2, summarize, then request business advice on the same selection ---


def test_select_email_2_then_summarize_then_request_business_advice():
    session = RealtimeVoiceSession()
    search_socket = _dispatch(session, "gmail_search", {"query": "in:inbox"}, _search_result("sel-1", "1. ... 2. ..."))
    selection_id = json.loads(search_socket.sent[0]["item"]["output"])["metadata"]["selection_id"]
    assert selection_id == "sel-1"

    summarize_socket = _dispatch(
        session, "gmail_summarize", {"selection_id": selection_id, "ordinal": 2},
        _read_result("The invoice is due Wednesday for $200."), call_id="call-2",
    )
    assert _spoken_of(summarize_socket) == "The invoice is due Wednesday for $200."
    assert session._session_touched_private_content is True

    advise_socket = _dispatch(
        session, "gmail_advise", {"selection_id": selection_id, "ordinal": 2},
        _read_result("This looks like a routine bill; pay before Wednesday to avoid a late fee.", business=True),
        call_id="call-3",
    )
    advice = json.loads(advise_socket.sent[0]["item"]["output"])
    assert advice["metadata"]["business_advice"] is True
    assert "pay before Wednesday" in _spoken_of(advise_socket)


# --- Interrupt mid Gmail-derived reply ---


def test_interrupting_a_gmail_derived_reply_stops_playback_like_any_other_reply(monkeypatch):
    # Content-agnostic by design (verified while investigating this area):
    # interruption keys off item_id/response_id, never message content, so
    # this scenario is mechanically identical to test_interruption.py's --
    # what matters here is confirming that fact holds for a reply that
    # happens to have come from a gmail_* tool call, per Priority 2.
    audio_chunk = base64.b64encode(b"\x01\x02" * 2400).decode()
    events = [
        {"type": "session.updated"},
        {"type": "response.created", "response": {"id": "r1"}},
        {"type": "response.output_audio.delta", "item_id": "gmail-answer", "content_index": 0,
         "response_id": "r1", "delta": audio_chunk},
        {"type": "input_audio_buffer.speech_started"},
    ]
    socket = patch_realtime_transport(monkeypatch, events)
    recorder = StateRecorder()

    session = run_session(RealtimeVoiceConfig(greeting=""), on_state=recorder)

    truncate_messages = [event for event in socket.sent if event.get("type") == "conversation.item.truncate"]
    assert len(truncate_messages) == 1
    assert truncate_messages[0]["item_id"] == "gmail-answer"
    assert "interrupted" in recorder.states()
    assert not session._playback.pending


# --- Reject disclosure ---


def test_rejecting_gmail_disclosure_does_not_mark_the_session_private():
    # A denied confirmation never reaches GmailService (tool_executor_from_router
    # returns before router.tools.execute runs), so no private content was ever
    # actually touched -- the session must stay eligible for normal memory
    # commit on later, unrelated turns. This intentionally asserts the
    # *absence* of suppression for a pure denial, the mirror image of every
    # other test in this file.
    session = RealtimeVoiceSession()
    socket = _dispatch(session, "gmail_search", {"query": "in:inbox"}, _denied_result("gmail_search"))

    output = json.loads(socket.sent[0]["item"]["output"])
    assert output["ok"] is False
    assert output["confirmed"] is False
    assert session._session_touched_private_content is False


def test_rejecting_gmail_read_disclosure_speaks_a_safe_cancellation_message():
    from jarvis.gmail import gmail_spoken_result
    from jarvis.models import CommandResult

    # gmail_spoken_result only rewrites .message when gmail_spoken_text is
    # present -- a denial has none, so the already-safe cancellation message
    # (no email content in it) is what would be spoken in Classic voice.
    result = CommandResult(False, "gmail_read cancelled.", action="gmail_read",
                           requires_confirmation=True, confirmed=False)
    assert gmail_spoken_result(result).message == "gmail_read cancelled."


# --- Ask about an expired selection ---


def test_asking_about_an_expired_selection_is_refused_and_marks_the_session_private():
    session = RealtimeVoiceSession()
    socket = _dispatch(session, "gmail_read", {"selection_id": "sel-old", "ordinal": 1}, _expired_selection_result())

    output = json.loads(socket.sent[0]["item"]["output"])
    assert output["ok"] is False
    assert "expired" in output["message"]
    # Unlike a denial, this result did reach GmailService (it failed inside
    # it), and GmailService._result() sets private_content unconditionally --
    # the user's evident intent to discuss a specific selected email is
    # itself treated as private, even though no content was read.
    assert session._session_touched_private_content is True


# --- End-to-end: a session that touched private content never reaches memory.add_turns ---


class _FakeMemory:
    def __init__(self) -> None:
        self.generation = 1
        self.add_turns_calls: list[tuple] = []

    def recent(self, limit: int) -> list:
        return []  # no prior turns to seed; irrelevant to what this test checks

    def add_turns(self, turns, expected_generation) -> None:
        self.add_turns_calls.append((turns, expected_generation))


def test_a_session_that_touched_gmail_content_never_commits_to_conversation_memory(monkeypatch):
    # run_stream() resets _session_touched_private_content at its own start
    # (by design -- a reconnect must not inherit a previous call's private
    # state), so setting the flag *before* calling run_stream() would just
    # get wiped. on_state fires mid-flight, after that reset and before the
    # finally-block commit check -- the same temporal position a real
    # gmail_* tool call's result would set it from, without fighting the
    # documented tool-task-vs-stream-end race (see test_tool_request.py).
    patch_realtime_transport(monkeypatch, [{"type": "session.updated"}])
    memory = _FakeMemory()

    def mark_private_once_listening(state, _event):
        if state == "listening":
            session._session_touched_private_content = True

    session = RealtimeVoiceSession(RealtimeVoiceConfig(greeting=""), memory=memory)
    asyncio.run(asyncio.wait_for(session.run_stream(on_state=mark_private_once_listening), timeout=2))

    assert memory.add_turns_calls == []


def test_a_session_that_never_touched_private_content_commits_normally(monkeypatch):
    # Control for the test above: same minimal scenario, flag never set --
    # proves the gate only suppresses when actually triggered, not always.
    patch_realtime_transport(monkeypatch, [{"type": "session.updated"}])
    memory = _FakeMemory()

    session = RealtimeVoiceSession(RealtimeVoiceConfig(greeting=""), memory=memory)
    asyncio.run(asyncio.wait_for(session.run_stream(), timeout=2))

    assert len(memory.add_turns_calls) == 1
