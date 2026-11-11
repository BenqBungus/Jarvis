from __future__ import annotations

from datetime import datetime, timezone

from jarvis.audit import AuditRecord
from jarvis.memory import ConversationMemory, EpisodicMemory


def test_episodic_memory_summarizes_conversation_and_tracks_state(tmp_path):
    conversation = ConversationMemory(path=tmp_path / "conversation.jsonl")
    conversation.add_turn("user", "Искам Jarvis да помни проектите ми.")
    conversation.add_turn("assistant", "Ще пазя полезни summaries.")

    episodic = EpisodicMemory(
        path=tmp_path / "episodes.jsonl",
        state_path=tmp_path / "episodes_state.json",
        min_new_turns=2,
    )

    result = episodic.summarize_conversation(conversation.recent(), force=False)
    second = episodic.summarize_conversation(conversation.recent(), force=False)

    assert result.ok
    assert result.metadata["episode_created"] is True
    assert second.metadata["episode_created"] is False
    assert "Conversation episode" in episodic.recent()[0].summary


def test_episodic_memory_searches_summaries(tmp_path):
    episodic = EpisodicMemory(path=tmp_path / "episodes.jsonl", state_path=tmp_path / "state.json")
    episodic.add_summary("Discussed Gaming mode and browser control.", topics=["gaming", "browser"])

    result = episodic.format_recent(query="gaming")

    assert result.ok
    assert "Gaming mode" in result.message
    assert result.metadata["episodes"][0]["topics"] == ["gaming", "browser"]


def test_episodic_memory_ignores_corrupt_lines(tmp_path):
    path = tmp_path / "episodes.jsonl"
    path.write_text('not-json\n{"summary": "Good episode", "topics": ["demo"]}\n', encoding="utf-8")

    episodes = EpisodicMemory(path=path, state_path=tmp_path / "state.json").recent()

    assert len(episodes) == 1
    assert episodes[0].summary == "Good episode"


def test_episodic_memory_summarizes_actions(tmp_path):
    episodic = EpisodicMemory(path=tmp_path / "episodes.jsonl", state_path=tmp_path / "state.json")
    now = datetime.now(timezone.utc).isoformat()
    records = [
        AuditRecord(
            timestamp=now,
            raw_text="jarvis отвори facebook",
            intent="apps_or_web.open",
            action="open_url",
            permission="safe",
            requires_confirmation=False,
            confirmed=None,
            ok=True,
            message="Opened",
            error="",
            dry_run=True,
            source="cli",
        ),
        AuditRecord(
            timestamp=now,
            raw_text="jarvis какво има на екрана",
            intent="vision.screen_describe",
            action="screen_describe",
            permission="confirm",
            requires_confirmation=True,
            confirmed=False,
            ok=False,
            message="cancelled",
            error="cancelled",
            dry_run=True,
            source="gui_voice",
        ),
    ]

    result = episodic.summarize_actions(records, minutes=30)
    episode = episodic.recent()[0]

    assert result.ok
    assert result.metadata["episode_created"] is True
    assert result.metadata["action_count"] == 2
    assert result.metadata["failed_count"] == 1
    assert episode.source == "actions"
    assert episode.metadata["minutes"] == 30
    assert episode.metadata["sources"] == ["cli", "gui_voice"]
