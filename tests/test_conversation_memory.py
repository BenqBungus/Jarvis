from __future__ import annotations

from jarvis.memory import ConversationMemory


def test_conversation_memory_stores_and_trims_recent_turns(tmp_path):
    memory = ConversationMemory(path=tmp_path / "conversation.jsonl", max_turns=3)

    memory.add_turn("user", "one")
    memory.add_turn("assistant", "two")
    memory.add_turn("user", "three")
    memory.add_turn("assistant", "four")

    recent = memory.recent(limit=10)

    assert [turn.content for turn in recent] == ["two", "three", "four"]


def test_conversation_memory_ignores_corrupt_lines(tmp_path):
    path = tmp_path / "conversation.jsonl"
    path.write_text('not-json\n{"role": "user", "content": "hello", "created_at": "now"}\n', encoding="utf-8")
    memory = ConversationMemory(path=path)

    recent = memory.recent()

    assert len(recent) == 1
    assert recent[0].content == "hello"
