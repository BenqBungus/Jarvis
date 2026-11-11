"""What a Kid or a Guest profile may do.

X2 of docs/claude/PERSONALIZATION_HANDOFF.md, built by Claude on the user's
decision of 2026-09-25. Adults are unchanged. The rules are checked in
ToolRegistry.execute (typed, planned, Live-voice and workflow tools), in
CommandRouter.handle (the rule-based commands) and before any confirmation
dialog opens; tools a profile may not use are also hidden from the AI. Full
access never applies to a Kid or Guest profile (trusted_actions.py).
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .models import CommandResult
from .permissions import ADMIN, BLOCKED

LEVELS = ("adult", "kid", "guest")
LEVEL_NAMES = {"adult": "Adult", "kid": "Kid", "guest": "Guest"}

# What each blocked group is about, finishing "An adult profile is needed to ...".
_REASONS = {
    "power": "shut down, restart or sleep the PC",
    "network": "turn the internet or Bluetooth off or on",
    "drivers": "check or install drivers",
    "admin": "make administrator changes",
    "gmail": "read email",
    "files_risky": "delete, move, rename or clean up files",
    "apps_close": "close apps or end processes",
    "screen": "share or look at the screen",
    "agent": "run tasks on its own",
    "browser_actions": "click or type on websites",
    "memory": "use saved memory",
    "history": "see Jarvis's history",
    "files": "open or change files",
    "documents": "read or write documents",
    "settings": "change settings",
    "apps": "open apps",
    "modes": "switch PC modes",
    "undo": "undo actions",
    "passwords": "use saved passwords",
}
_KID_TOOLS = {
    "cleanup_temp_files": "files_risky", "recycle_local_path": "files_risky", "move_local_path": "files_risky",
    "rename_local_path": "files_risky", "close_app": "apps_close", "end_process": "apps_close",
    "start_screen_sharing": "screen", "ask_shared_screen": "screen", "screen_describe": "screen",
    "run_autonomous_task": "agent", "browser_click": "browser_actions", "browser_fill": "browser_actions",
    "browser_select": "browser_actions",
}
_KID_CATEGORIES = {"power": "power", "network": "network", "bluetooth": "network", "drivers": "drivers",
                   "gmail": "gmail", "vault": "passwords"}
_GUEST_TOOLS = {"undo_last_action": "undo"}
_GUEST_CATEGORIES = {"memory": "memory", "developer": "history", "files": "files", "documents": "documents",
                     "settings": "settings", "vision": "screen", "applications": "apps", "modes": "modes"}
# Rule-based router commands (IntentMetadata.intent prefixes).
_KID_INTENTS = (("system.restart", "power"), ("system.shutdown", "power"), ("system.sleep", "power"),
                ("system.cleanup_temp", "files_risky"), ("network.", "network"), ("bluetooth.", "network"),
                ("vision.screen_describe", "screen"))
_GUEST_INTENTS = (("memory.", "memory"), ("developer.", "history"), ("settings.", "settings"),
                  ("modes.", "modes"), ("vision.", "screen"), ("workflow.", "agent"))


def normalize_level(level: Any) -> str:
    return level if level in LEVELS else "adult"


def tool_block(level: str, spec: Any) -> str:
    """Why `level` may not use this tool ("" when it may)."""
    level = normalize_level(level)
    if level == "adult":
        return ""
    name, category = getattr(spec, "name", ""), getattr(spec, "category", "")
    group = _KID_TOOLS.get(name) or _KID_CATEGORIES.get(category)
    if not group and getattr(spec, "permission", "") == ADMIN and category != "modes":
        group = "admin"
    if not group and level == "guest":
        group = _GUEST_TOOLS.get(name) or _GUEST_CATEGORIES.get(category)
    return _REASONS[group] if group else ""


def tool_allowed(level: str, spec: Any) -> tuple[bool, str]:
    reason = tool_block(level, spec)
    return (not reason, _sentence(reason) if reason else "")


def intent_block(level: str, intent: str) -> str:
    level = normalize_level(level)
    if level == "adult" or not intent:
        return ""
    rules = _KID_INTENTS + (_GUEST_INTENTS if level == "guest" else ())
    group = next((group for prefix, group in rules if intent.startswith(prefix)), "")
    return _REASONS[group] if group else ""


def visible_tool_specs(level: str, registry: Any) -> list:
    return [spec for spec in registry.list_specs() if not tool_block(level, spec)]


def full_access_allowed(level: str) -> bool:
    return normalize_level(level) == "adult"


def _sentence(reason: str) -> str:
    return f"An adult profile is needed to {reason}."


def blocked_result(level: str, reason: str, *, action: str = "", permission: str = BLOCKED) -> CommandResult:
    return CommandResult(False, _sentence(reason), action=action, permission=permission,
                         metadata={"blocked_by_level": normalize_level(level), "error_code": "blocked_by_level",
                                   "executed": False, "retryable": False})


class LevelGate:
    """The active profile's level, checked by ToolRegistry (as `level_gate`)
    and by CommandRouter for rule-based commands."""

    def __init__(self, level: str | Callable[[], str] = "adult") -> None:
        self._level = level

    @property
    def level(self) -> str:
        return normalize_level(self._level() if callable(self._level) else self._level)

    def set_level(self, level: str) -> None:
        self._level = normalize_level(level)

    def __call__(self, spec: Any) -> CommandResult | None:
        level = self.level
        reason = tool_block(level, spec)
        if not reason:
            return None
        return blocked_result(level, reason, action=getattr(spec, "name", ""),
                              permission=getattr(spec, "permission", BLOCKED))

    def check_intent(self, intent: Any) -> CommandResult | None:
        level = self.level
        name = getattr(intent, "intent", intent if isinstance(intent, str) else "")
        reason = intent_block(level, name)
        if not reason:
            return None
        return blocked_result(level, reason, action=getattr(intent, "action", ""),
                              permission=getattr(intent, "permission", BLOCKED))
