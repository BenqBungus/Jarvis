from __future__ import annotations

from jarvis.memory import EpisodicMemory, LongTermMemory, SemanticMemorySearch


def test_semantic_memory_matches_bulgarian_query_to_english_preference(tmp_path):
    long_term = LongTermMemory(path=tmp_path / "memory.sqlite3")
    long_term.remember("Preferred browser is Opera GX", category="preference", importance=5)
    long_term.remember("Favorite game is Minecraft", category="game", importance=3)
    semantic = SemanticMemorySearch(long_term_memory=long_term)

    result = semantic.format_search("любим браузър")

    assert result.ok
    assert "Preferred browser is Opera GX" in result.message
    assert result.metadata["semantic_memory_hits"][0]["kind"] == "long_term"
    assert result.metadata["semantic_memory_hits"][0]["category"] == "preference"


def test_semantic_memory_searches_episodic_summaries(tmp_path):
    episodic = EpisodicMemory(path=tmp_path / "episodes.jsonl", state_path=tmp_path / "episodes_state.json")
    episodic.add_summary(
        "Discussed browser control and screen vision for Jarvis.",
        source="conversation",
        topics=["browser", "vision"],
    )
    semantic = SemanticMemorySearch(episodic_memory=episodic)

    result = semantic.format_search("екрана browser")

    assert result.ok
    assert "screen vision" in result.message
    assert result.metadata["semantic_memory_hits"][0]["kind"] == "episode"
    assert result.metadata["semantic_memory_hits"][0]["source"] == "conversation"


def test_semantic_memory_requires_query(tmp_path):
    semantic = SemanticMemorySearch(long_term_memory=LongTermMemory(path=tmp_path / "memory.sqlite3"))

    result = semantic.format_search("")

    assert not result.ok
    assert "query" in result.message.lower()
