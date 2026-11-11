from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

from ..privacy import redact_sensitive_text


DEFAULT_CONVERSATION_PATH = Path("data/conversation_history.jsonl")
_HISTORY_LOCK = RLock()
_GENERATIONS: dict[Path, int] = {}


@dataclass(frozen=True)
class ConversationTurn:
    role: str
    content: str
    created_at: str

    @classmethod
    def create(cls, role: str, content: str) -> "ConversationTurn":
        return cls(
            role=role,
            content=content,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    def to_record(self) -> dict[str, str]:
        return {
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
        }

    @classmethod
    def from_record(cls, record: dict[str, object]) -> "ConversationTurn | None":
        role = str(record.get("role", "")).strip()
        content = str(record.get("content", "")).strip()
        created_at = str(record.get("created_at", "")).strip()
        if role not in {"user", "assistant"} or not content:
            return None
        return cls(role=role, content=content, created_at=created_at)


class ConversationMemory:
    def __init__(self, path: Path = DEFAULT_CONVERSATION_PATH, max_turns: int = 80) -> None:
        self.path = path
        self.max_turns = max_turns

    def add_turn(self, role: str, content: str) -> None:
        self.add_turns([(role, content)])

    @property
    def generation(self) -> int:
        with _HISTORY_LOCK:
            return _GENERATIONS.get(self.path.resolve(), 0)

    def add_turns(self, turns: list[tuple[str, str]], *, expected_generation: int | None = None) -> None:
        with _HISTORY_LOCK:
            if expected_generation is not None and self.generation != expected_generation:
                return
            cleaned = [ConversationTurn.create(role, redact_sensitive_text(content).text.strip())
                       for role, content in turns if role in {"user", "assistant"} and content.strip()]
            if not cleaned:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as file:
                for turn in cleaned:
                    file.write(json.dumps(turn.to_record(), ensure_ascii=False) + "\n")
            self._trim()

    def recent(self, limit: int = 12) -> list[ConversationTurn]:
        with _HISTORY_LOCK:
            turns = self._read_all()
            return turns[-limit:] if limit > 0 else []

    def clear(self) -> None:
        with _HISTORY_LOCK:
            _GENERATIONS[self.path.resolve()] = self.generation + 1
            if self.path.exists():
                self.path.unlink()

    def _read_all(self) -> list[ConversationTurn]:
        if not self.path.exists():
            return []
        turns: list[ConversationTurn] = []
        with self.path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(record, dict):
                    turn = ConversationTurn.from_record(record)
                    if turn is not None:
                        turns.append(turn)
        return turns

    def _trim(self) -> None:
        turns = self._read_all()
        if len(turns) <= self.max_turns:
            return
        temporary = self.path.with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as file:
            for turn in turns[-self.max_turns :]:
                file.write(json.dumps(turn.to_record(), ensure_ascii=False) + "\n")
        temporary.replace(self.path)
