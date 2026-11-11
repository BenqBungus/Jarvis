from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    message: str
    intent: str = "unknown"
    action: str = "unknown"
    permission: str = "safe"
    requires_confirmation: bool = False
    confirmed: bool | None = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def with_metadata(
        self,
        *,
        intent: str | None = None,
        action: str | None = None,
        permission: str | None = None,
        requires_confirmation: bool | None = None,
        confirmed: bool | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "CommandResult":
        return replace(
            self,
            intent=self.intent if intent is None else intent,
            action=self.action if action is None else action,
            permission=self.permission if permission is None else permission,
            requires_confirmation=self.requires_confirmation
            if requires_confirmation is None
            else requires_confirmation,
            confirmed=self.confirmed if confirmed is None else confirmed,
            error=self.error if error is None else error,
            metadata=self.metadata if metadata is None else metadata,
        )
