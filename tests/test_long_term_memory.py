from __future__ import annotations

from jarvis.memory import LongTermMemory, normalize_memory_category


def test_long_term_memory_is_lazy_until_used(tmp_path):
    path = tmp_path / "memory.sqlite3"
    LongTermMemory(path=path)

    assert not path.exists()


def test_long_term_memory_remember_search_forget(tmp_path):
    memory = LongTermMemory(path=tmp_path / "memory.sqlite3")

    item = memory.remember("Call me Berk", category="preference", importance=5)
    results = memory.search("berk")
    deleted = memory.forget("berk")

    assert item.id > 0
    assert results[0].content == "Call me Berk"
    assert results[0].category == "preference"
    assert deleted == 1
    assert memory.search("berk") == []


def test_long_term_memory_update_and_categories(tmp_path):
    memory = LongTermMemory(path=tmp_path / "memory.sqlite3")

    item = memory.remember("Favorite browser is Chrome", category="preference", importance=5)
    updated = memory.update(item.id, content="Favorite browser is Opera GX", category="website", importance=4)
    missing = memory.update(999, content="missing")

    assert updated is not None
    assert updated.content == "Favorite browser is Opera GX"
    assert updated.category == "website"
    assert updated.importance == 4
    assert missing is None
    assert memory.list_categories()["website"] == 1


def test_long_term_memory_redacts_sensitive_values_on_remember_and_update(tmp_path):
    memory = LongTermMemory(path=tmp_path / "memory.sqlite3")

    item = memory.remember("OpenAI key is sk-proj-abcdefghijklmnopqrstuvwxyz123456")
    updated = memory.update(item.id, content="password: hunter2")

    assert "sk-proj-" not in item.content
    assert item.content == "OpenAI key is [REDACTED_SECRET]"
    assert updated is not None
    assert updated.content == "password: [REDACTED_SECRET]"


def test_memory_category_aliases_normalize_to_known_categories():
    assert normalize_memory_category("предпочитания") == "preference"
    assert normalize_memory_category("игри") == "game"
    assert normalize_memory_category("unknown-custom") == "general"
