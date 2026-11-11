from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ..audit import AuditRecord
from ..models import CommandResult
from .conversation import ConversationTurn


DEFAULT_EPISODIC_MEMORY_PATH = Path("data/episodic_memory.jsonl")
DEFAULT_EPISODIC_STATE_PATH = Path("data/episodic_memory_state.json")


@dataclass(frozen=True)
class EpisodeSummary:
    id: str
    summary: str
    source: str
    topics: list[str]
    turn_count: int
    action_count: int
    created_at: str
    metadata: dict[str, object]

    @classmethod
    def from_record(cls, record: dict[str, object]) -> "EpisodeSummary | None":
        summary = str(record.get("summary", "")).strip()
        if not summary:
            return None
        topics_raw = record.get("topics", [])
        topics = [str(topic) for topic in topics_raw] if isinstance(topics_raw, list) else []
        metadata_raw = record.get("metadata", {})
        metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
        return cls(
            id=str(record.get("id", "")) or str(uuid4()),
            summary=summary,
            source=str(record.get("source", "manual")),
            topics=topics,
            turn_count=int(record.get("turn_count", 0) or 0),
            action_count=int(record.get("action_count", 0) or 0),
            created_at=str(record.get("created_at", "")) or datetime.now(timezone.utc).isoformat(),
            metadata=metadata,
        )


class EpisodicMemory:
    def __init__(
        self,
        *,
        path: Path = DEFAULT_EPISODIC_MEMORY_PATH,
        state_path: Path = DEFAULT_EPISODIC_STATE_PATH,
        min_new_turns: int = 6,
    ) -> None:
        self.path = path
        self.state_path = state_path
        self.min_new_turns = max(2, min_new_turns)

    def add_summary(
        self,
        summary: str,
        *,
        source: str = "manual",
        topics: list[str] | None = None,
        turn_count: int = 0,
        action_count: int = 0,
        metadata: dict[str, object] | None = None,
    ) -> EpisodeSummary:
        episode = EpisodeSummary(
            id=str(uuid4()),
            summary=summary.strip(),
            source=source,
            topics=topics or _extract_topics(summary),
            turn_count=max(0, turn_count),
            action_count=max(0, action_count),
            created_at=datetime.now(timezone.utc).isoformat(),
            metadata=metadata or {},
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(asdict(episode), ensure_ascii=False) + "\n")
        return episode

    def recent(self, limit: int = 8) -> list[EpisodeSummary]:
        return self._read_all()[-limit:]

    def search(self, query: str = "", limit: int = 8) -> list[EpisodeSummary]:
        cleaned = query.strip().lower()
        episodes = list(reversed(self._read_all()))
        if cleaned:
            episodes = [
                episode
                for episode in episodes
                if cleaned in episode.summary.lower()
                or any(cleaned in topic.lower() for topic in episode.topics)
            ]
        return episodes[:limit]

    def summarize_conversation(
        self,
        turns: list[ConversationTurn],
        *,
        ai=None,
        force: bool = False,
    ) -> CommandResult:
        new_turns = self._new_conversation_turns(turns)
        if not force and len(new_turns) < self.min_new_turns:
            return CommandResult(
                True,
                f"No episode summary needed yet. New turns: {len(new_turns)}/{self.min_new_turns}.",
                metadata={"episode_created": False, "new_turns": len(new_turns), "min_new_turns": self.min_new_turns},
            )
        if not new_turns:
            return CommandResult(True, "There is no conversation to summarize yet.", metadata={"episode_created": False})

        summary = self._summarize_turns(new_turns, ai=ai)
        episode = self.add_summary(
            summary,
            source="conversation",
            turn_count=len(new_turns),
            metadata={
                "first_turn_at": new_turns[0].created_at,
                "last_turn_at": new_turns[-1].created_at,
            },
        )
        self._write_state({"last_conversation_turn_created_at": new_turns[-1].created_at})
        return CommandResult(
            True,
            f"Saved episode summary:\n{episode.summary}",
            metadata={"episode_created": True, "episode_id": episode.id, "topics": episode.topics},
        )

    def summarize_actions(
        self,
        records: list[AuditRecord],
        *,
        force: bool = True,
        minutes: int | None = None,
    ) -> CommandResult:
        if not records:
            return CommandResult(True, "There are no recent actions to summarize.", metadata={"episode_created": False})
        recent_records = records[-12:]
        ok_count = sum(1 for record in records if record.ok)
        failed_count = len(records) - ok_count
        action_names = [record.action for record in records]
        source_names = sorted({record.source for record in records if record.source})
        lines = []
        for record in recent_records:
            status = "ok" if record.ok else "failed"
            lines.append(f"{record.action} ({status}): {_compact(record.raw_text, 120)}")
        window = f" from the last {minutes} minutes" if minutes is not None else ""
        summary = (
            f"Recent Jarvis actions{window}: {len(records)} action(s), "
            f"{ok_count} ok, {failed_count} failed. "
            + "; ".join(lines)
        )
        episode = self.add_summary(
            summary,
            source="actions",
            action_count=len(records),
            metadata={
                "record_count": len(records),
                "minutes": minutes,
                "actions": action_names,
                "sources": source_names,
                "ok_count": ok_count,
                "failed_count": failed_count,
            },
        )
        return CommandResult(
            True,
            f"Saved action episode summary:\n{episode.summary}",
            metadata={
                "episode_created": True,
                "episode_id": episode.id,
                "topics": episode.topics,
                "action_count": len(records),
                "ok_count": ok_count,
                "failed_count": failed_count,
            },
        )

    def format_recent(self, query: str = "", limit: int = 8) -> CommandResult:
        episodes = self.search(query=query, limit=limit)
        if not episodes:
            return CommandResult(True, "I do not have episodic memories matching that yet.", metadata={"episodes": []})
        lines = ["Episodic memories:"]
        for episode in episodes:
            created = episode.created_at.split("T", 1)[0]
            topics = f" [{', '.join(episode.topics[:4])}]" if episode.topics else ""
            lines.append(f"- {created} ({episode.source}){topics}: {episode.summary}")
        return CommandResult(
            True,
            "\n".join(lines),
            metadata={"episodes": [asdict(episode) for episode in episodes]},
        )

    def _new_conversation_turns(self, turns: list[ConversationTurn]) -> list[ConversationTurn]:
        state = self._read_state()
        last_seen = str(state.get("last_conversation_turn_created_at", ""))
        if not last_seen:
            return turns
        return [turn for turn in turns if turn.created_at > last_seen]

    def _summarize_turns(self, turns: list[ConversationTurn], *, ai=None) -> str:
        if ai is not None and hasattr(ai, "summarize_episode") and not getattr(ai, "dry_run", False):
            result = ai.summarize_episode(turns)
            if result.ok and result.message.strip():
                return result.message.strip()

        compact: list[str] = []
        for turn in turns[-12:]:
            role = "User" if turn.role == "user" else "Jarvis"
            compact.append(f"{role}: {_compact(turn.content, 180)}")
        return "Conversation episode: " + " | ".join(compact)

    def _read_all(self) -> list[EpisodeSummary]:
        if not self.path.exists():
            return []
        episodes: list[EpisodeSummary] = []
        with self.path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    episode = EpisodeSummary.from_record(record)
                    if episode is not None:
                        episodes.append(episode)
        return episodes

    def _read_state(self) -> dict[str, object]:
        if not self.state_path.exists():
            return {}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}

    def _write_state(self, updates: dict[str, object]) -> None:
        state = self._read_state()
        state.update(updates)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _compact(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _extract_topics(text: str, limit: int = 6) -> list[str]:
    words = re.findall(r"[A-Za-zА-Яа-я0-9]{4,}", text.lower())
    ignored = {
        "conversation",
        "episode",
        "jarvis",
        "user",
        "assistant",
        "това",
        "какво",
        "може",
        "трябва",
        "искам",
        "джарвис",
    }
    topics: list[str] = []
    for word in words:
        if word in ignored or word in topics:
            continue
        topics.append(word)
        if len(topics) >= limit:
            break
    return topics
