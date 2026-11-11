from __future__ import annotations

from dataclasses import dataclass


SAFE = "safe"
CONFIRM = "confirm"
ADMIN = "admin"
BLOCKED = "blocked"


@dataclass(frozen=True)
class IntentMetadata:
    intent: str
    action: str
    permission: str = SAFE
    requires_confirmation: bool = False


def confirmed_from_result(ok: bool, message: str, requires_confirmation: bool) -> bool | None:
    if not requires_confirmation:
        return None
    if "cancelled" in message.lower():
        return False
    return ok

