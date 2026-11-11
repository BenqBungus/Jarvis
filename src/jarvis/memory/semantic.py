from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any

from ..models import CommandResult
from .episodic import EpisodeSummary
from .long_term import MemoryItem


TOKEN_RE = re.compile(r"[A-Za-zА-Яа-я0-9]{2,}")

SEMANTIC_ALIASES: dict[str, set[str]] = {
    "browser": {"браузър", "браузъра", "браузер", "браузера", "opera", "chrome", "edge", "firefox", "сайт", "website", "web"},
    "website": {"сайт", "сайтове", "страница", "page", "url", "link", "browser", "web"},
    "preference": {"предпочитание", "предпочитания", "любим", "любима", "любимият", "любимия", "харесвам", "favorite", "preferred"},
    "project": {"проект", "проекти", "project", "workspace", "работа"},
    "device": {"устройство", "лаптоп", "компютър", "pc", "computer", "hardware"},
    "game": {"игра", "игри", "gaming", "гейминг", "steam", "valorant", "minecraft"},
    "routine": {"рутина", "рутини", "режим", "mode", "workflow", "навици"},
    "conversation": {"разговор", "разговори", "чат", "chat", "session"},
    "actions": {"действия", "команди", "history", "audit", "commands", "action"},
    "screen": {"екран", "екрана", "screenshot", "vision", "виждам", "гледам", "display"},
    "voice": {"глас", "voice", "микрофон", "microphone", "wake", "слушай"},
    "driver": {"драйвер", "драйвери", "nvidia", "gpu", "chipset", "drivers"},
    "temperature": {"температура", "температури", "cpu", "gpu", "temp", "thermal"},
}


@dataclass(frozen=True)
class SemanticMemoryHit:
    kind: str
    id: str
    content: str
    score: float
    category: str = ""
    source: str = ""
    created_at: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["score"] = round(self.score, 4)
        return data


class SemanticMemorySearch:
    def __init__(self, *, long_term_memory: Any | None = None, episodic_memory: Any | None = None) -> None:
        self.long_term_memory = long_term_memory
        self.episodic_memory = episodic_memory

    def search(self, query: str, limit: int = 8) -> list[SemanticMemoryHit]:
        query = query.strip()
        if not query:
            return []
        limit = max(1, min(20, int(limit)))
        query_tokens = _expanded_tokens(query)
        hits: list[SemanticMemoryHit] = []

        for item in self._long_term_items():
            haystack = f"{item.content} {item.category}"
            score = _score(query_tokens, _expanded_tokens(haystack))
            if score > 0:
                hits.append(
                    SemanticMemoryHit(
                        kind="long_term",
                        id=str(item.id),
                        content=item.content,
                        category=item.category,
                        score=score + (item.importance * 0.01),
                        created_at=item.updated_at,
                        metadata={"importance": item.importance, "created_at": item.created_at},
                    )
                )

        for episode in self._episode_items():
            topics = " ".join(episode.topics)
            haystack = f"{episode.summary} {episode.source} {topics}"
            score = _score(query_tokens, _expanded_tokens(haystack))
            if score > 0:
                hits.append(
                    SemanticMemoryHit(
                        kind="episode",
                        id=episode.id,
                        content=episode.summary,
                        source=episode.source,
                        score=score,
                        created_at=episode.created_at,
                        metadata={
                            "topics": episode.topics,
                            "turn_count": episode.turn_count,
                            "action_count": episode.action_count,
                            **episode.metadata,
                        },
                    )
                )

        return sorted(hits, key=lambda hit: (hit.score, hit.created_at), reverse=True)[:limit]

    def format_search(self, query: str, limit: int = 8) -> CommandResult:
        query = query.strip()
        if not query:
            return CommandResult(False, "I need a memory search query.", metadata={"semantic_memory_hits": []})
        hits = self.search(query, limit=limit)
        if not hits:
            return CommandResult(True, f"I did not find semantic memory matches for: {query}", metadata={"semantic_memory_hits": []})

        lines = ["Semantic memory matches:"]
        for hit in hits:
            label = hit.category if hit.kind == "long_term" else hit.source
            label_text = f" [{label}]" if label else ""
            lines.append(f"- {hit.kind} #{hit.id}{label_text} score={hit.score:.2f}: {_compact(hit.content, 180)}")
        return CommandResult(
            True,
            "\n".join(lines),
            metadata={"semantic_memory_hits": [hit.to_dict() for hit in hits], "semantic_query": query},
        )

    def _long_term_items(self) -> list[MemoryItem]:
        if self.long_term_memory is None or not hasattr(self.long_term_memory, "search"):
            return []
        return list(self.long_term_memory.search(query="", limit=200))

    def _episode_items(self) -> list[EpisodeSummary]:
        if self.episodic_memory is None or not hasattr(self.episodic_memory, "recent"):
            return []
        return list(self.episodic_memory.recent(limit=200))


def _tokens(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def _expanded_tokens(text: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for token in _tokens(text):
        counter[token] += 1
        for canonical, aliases in SEMANTIC_ALIASES.items():
            if token == canonical or token in aliases:
                counter[canonical] += 1
                for alias in aliases:
                    counter[alias] += 1
    return counter


def _score(query: Counter[str], candidate: Counter[str]) -> float:
    if not query or not candidate:
        return 0.0
    shared = set(query) & set(candidate)
    if not shared:
        return 0.0
    dot = sum(query[token] * candidate[token] for token in shared)
    query_norm = math.sqrt(sum(value * value for value in query.values()))
    candidate_norm = math.sqrt(sum(value * value for value in candidate.values()))
    if query_norm == 0 or candidate_norm == 0:
        return 0.0
    cosine = dot / (query_norm * candidate_norm)
    coverage = len(shared) / max(1, len(query))
    return (cosine * 0.75) + (coverage * 0.25)


def _compact(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."
