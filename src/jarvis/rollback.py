from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from threading import RLock


ROLLBACK_PATH = Path("data/rollback_state.json")
_LOCK = RLock()


@dataclass(frozen=True)
class RollbackAction:
    timestamp: str
    label: str
    undo_type: str
    payload: dict[str, Any]


class RollbackManager:
    def __init__(self, path: Path = ROLLBACK_PATH) -> None:
        self.path = path

    def push(self, label: str, undo_type: str, payload: dict[str, Any]) -> None:
        with _LOCK:
            self._push(label, undo_type, payload)

    def _push(self, label: str, undo_type: str, payload: dict[str, Any]) -> None:
        stack = self.load()
        stack.append(
            RollbackAction(
                timestamp=datetime.now(timezone.utc).isoformat(),
                label=label,
                undo_type=undo_type,
                payload=payload,
            )
        )
        self._save(stack[-50:])

    def pop(self) -> RollbackAction | None:
        with _LOCK:
            stack = self.load()
            if not stack:
                return None
            action = stack.pop()
            self._save(stack)
            return action

    def peek(self) -> RollbackAction | None:
        stack = self.load()
        return stack[-1] if stack else None

    def discard_if_latest(self, expected: RollbackAction) -> bool:
        with _LOCK:
            stack = self.load()
            if not stack or stack[-1] != expected:
                return False
            self._save(stack[:-1])
            return True

    def load(self) -> list[RollbackAction]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return [
            RollbackAction(
                timestamp=str(row["timestamp"]),
                label=str(row["label"]),
                undo_type=str(row["undo_type"]),
                payload=dict(row.get("payload", {})),
            )
            for row in data
        ]

    def _save(self, stack: list[RollbackAction]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w", encoding="utf-8") as file:
            json.dump([asdict(item) for item in stack], file, ensure_ascii=False, indent=2)
            file.write("\n")
        temporary.replace(self.path)
