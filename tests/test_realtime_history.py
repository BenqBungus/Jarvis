from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

from jarvis.memory.conversation import ConversationMemory
from jarvis.memory.realtime_history import RealtimeHistory
from jarvis.realtime import RealtimeVoiceSession


def message(journal, key, role):
    journal.observe({"type": "conversation.item.added", "item": {"id": key, "role": role}})


def transcript(journal, key, role, text):
    kind = "conversation.item.input_audio_transcription.completed" if role == "user" else "response.output_audio_transcript.done"
    journal.observe({"type": kind, "item_id": key, "transcript": text})


def complete(journal, key):
    journal.observe({"type": "response.done", "response": {"id": "response", "status": "completed",
        "output": [{"id": key, "type": "message"}]}})


def test_voice_history_orders_late_transcription_and_waits_for_playback(tmp_path):
    memory = ConversationMemory(tmp_path / "history.jsonl")
    journal = RealtimeHistory(memory)
    message(journal, "user1", "user")
    message(journal, "assistant1", "assistant")
    transcript(journal, "assistant1", "assistant", "Hello Berk")
    complete(journal, "assistant1")
    journal.playback_drained()
    transcript(journal, "user1", "user", "Hello Jarvis")
    journal.commit()
    journal.commit()
    assert [(t.role, t.content) for t in memory.recent()] == [("user", "Hello Jarvis"), ("assistant", "Hello Berk")]


def test_unheard_and_interrupted_voice_responses_are_not_persisted(tmp_path):
    memory = ConversationMemory(tmp_path / "history.jsonl")
    journal = RealtimeHistory(memory)
    transcript(journal, "notheard", "assistant", "Unheard content")
    complete(journal, "notheard")
    journal.commit()
    assert memory.recent() == []
    journal = RealtimeHistory(memory)
    transcript(journal, "interrupted", "assistant", "Full response that was interrupted")
    complete(journal, "interrupted")
    journal.interrupt(["interrupted"])
    journal.playback_drained()
    journal.commit()
    assert memory.recent() == []


def test_interrupted_response_before_first_audio_is_not_remembered(tmp_path):
    memory = ConversationMemory(tmp_path / "history.jsonl")
    journal = RealtimeHistory(memory)
    journal.interrupt_response("response")
    transcript(journal, "early", "assistant", "Never played")
    complete(journal, "early")
    journal.playback_drained()
    journal.commit()
    assert not memory.recent()


def test_clear_memory_during_voice_session_does_not_resurrect_it(tmp_path):
    memory = ConversationMemory(tmp_path / "history.jsonl")
    journal = RealtimeHistory(memory)
    transcript(journal, "user1", "user", "Forget this")
    memory.clear()
    journal.commit()
    assert not memory.recent()


def test_concurrent_memory_writes_are_valid_and_redacted(tmp_path):
    memory = ConversationMemory(tmp_path / "history.jsonl", max_turns=40)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda i: memory.add_turn("user", f"Message {i} password: not-a-real-password"), range(100)))
    turns = memory.recent(100)
    assert len(turns) == 40
    assert all("not-a-real-password" not in turn.content for turn in turns)
    assert memory.recent(0) == []


def test_realtime_seeds_bounded_history_without_running_a_response(tmp_path):
    memory = ConversationMemory(tmp_path / "history.jsonl")
    memory.add_turn("user", "Remember my project")
    sent = []

    class Socket:
        async def send(self, data):
            sent.append(json.loads(data))

    asyncio.run(RealtimeVoiceSession(memory=memory)._seed_history(Socket()))
    assert len(sent) == 1 and sent[0]["type"] == "conversation.item.create"
    assert "Remember my project" in sent[0]["item"]["content"][0]["text"]
    assert "Do not execute old requests" in sent[0]["item"]["content"][0]["text"]
    sent.clear()
    asyncio.run(RealtimeVoiceSession()._seed_history(Socket()))
    assert sent == []
    asyncio.run(RealtimeVoiceSession(memory=memory, memory_enabled=lambda: False)._seed_history(Socket()))
    assert sent == []
