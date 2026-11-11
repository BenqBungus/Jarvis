from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..privacy import redact_sensitive_text


DEFAULT_MEMORY_DB_PATH = Path("data/memory.sqlite3")
MEMORY_CATEGORIES = ("general", "preference", "project", "device", "game", "website", "routine")


@dataclass(frozen=True)
class MemoryItem:
    id: int
    content: str
    category: str
    importance: int
    created_at: str
    updated_at: str


class LongTermMemory:
    def __init__(self, path: Path = DEFAULT_MEMORY_DB_PATH) -> None:
        self.path = path
        self._schema_ready = False

    def remember(self, content: str, category: str = "general", importance: int = 3) -> MemoryItem:
        self._ensure_schema()
        content = content.strip()
        if not content:
            raise ValueError("Memory content cannot be empty.")
        content = redact_sensitive_text(content).text
        category = normalize_memory_category(category)
        importance = max(1, min(5, importance))
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO memories (content, category, importance, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (content, category, importance, now, now),
            )
            memory_id = int(cursor.lastrowid)
        return MemoryItem(memory_id, content, category, importance, now, now)

    def get(self, memory_id: int) -> MemoryItem | None:
        self._ensure_schema()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, content, category, importance, created_at, updated_at
                FROM memories
                WHERE id = ?
                """,
                (int(memory_id),),
            ).fetchone()
        return self._row_to_item(row) if row is not None else None

    def search(self, query: str = "", limit: int = 8) -> list[MemoryItem]:
        self._ensure_schema()
        query = query.strip()
        with self._connect() as connection:
            if query:
                rows = connection.execute(
                    """
                    SELECT id, content, category, importance, created_at, updated_at
                    FROM memories
                    WHERE content LIKE ? OR category LIKE ?
                    ORDER BY importance DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (f"%{query}%", f"%{query}%", limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT id, content, category, importance, created_at, updated_at
                    FROM memories
                    ORDER BY importance DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [self._row_to_item(row) for row in rows]

    def forget(self, query: str) -> int:
        self._ensure_schema()
        query = query.strip()
        if not query:
            return 0
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM memories WHERE content LIKE ? OR category LIKE ?",
                (f"%{query}%", f"%{query}%"),
            )
            return int(cursor.rowcount)

    def update(
        self,
        memory_id: int,
        *,
        content: str | None = None,
        category: str | None = None,
        importance: int | None = None,
    ) -> MemoryItem | None:
        self._ensure_schema()
        current = self.get(memory_id)
        if current is None:
            return None

        new_content = current.content if content is None else content.strip()
        if not new_content:
            raise ValueError("Memory content cannot be empty.")
        new_content = redact_sensitive_text(new_content).text
        new_category = current.category if category is None else normalize_memory_category(category)
        new_importance = current.importance if importance is None else max(1, min(5, int(importance)))
        now = datetime.now(timezone.utc).isoformat()

        with self._connect() as connection:
            connection.execute(
                """
                UPDATE memories
                SET content = ?, category = ?, importance = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_content, new_category, new_importance, now, int(memory_id)),
            )
        return self.get(memory_id)

    def list_categories(self) -> dict[str, int]:
        self._ensure_schema()
        counts = {category: 0 for category in MEMORY_CATEGORIES}
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT category, COUNT(*)
                FROM memories
                GROUP BY category
                ORDER BY category
                """
            ).fetchall()
        for category, count in rows:
            counts[str(category)] = int(count)
        return counts

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    importance INTEGER NOT NULL DEFAULT 3,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
            connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at)")
        self._schema_ready = True

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    @staticmethod
    def _row_to_item(row: tuple) -> MemoryItem:
        return MemoryItem(
            id=int(row[0]),
            content=str(row[1]),
            category=str(row[2]),
            importance=int(row[3]),
            created_at=str(row[4]),
            updated_at=str(row[5]),
        )


def normalize_memory_category(category: str) -> str:
    cleaned = category.strip().lower().replace(" ", "_")
    aliases = {
        "preferences": "preference",
        "предпочитание": "preference",
        "предпочитания": "preference",
        "проект": "project",
        "проекти": "project",
        "устройство": "device",
        "устройства": "device",
        "игра": "game",
        "игри": "game",
        "сайт": "website",
        "сайтове": "website",
        "рутина": "routine",
        "рутини": "routine",
        "общо": "general",
    }
    cleaned = aliases.get(cleaned, cleaned)
    if cleaned not in MEMORY_CATEGORIES:
        return "general"
    return cleaned
