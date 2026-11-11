from __future__ import annotations

import builtins

from jarvis.ai_client import JarvisAI
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


def make_router(auto_confirm: bool = False) -> CommandRouter:
    return CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=auto_confirm),
        ai=JarvisAI(dry_run=True),
    )


def test_safe_command_gets_safe_permission_metadata():
    result = make_router().handle("jarvis отвори plasico.bg")
    assert result.ok
    assert result.intent == "apps_or_web.open"
    assert result.permission == "safe"
    assert result.requires_confirmation is False
    assert result.confirmed is None


def test_admin_command_records_denied_confirmation(monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda _: "NO")
    result = make_router().handle("jarvis спри интернета")
    assert not result.ok
    assert result.intent == "network.disable_internet"
    assert result.permission == "admin"
    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.metadata["error_type"] == "user_cancelled"
    assert result.metadata["recommended_action"] == "ask_user_before_retrying"


def test_confirm_command_records_auto_confirmation():
    result = make_router(auto_confirm=True).handle("jarvis undo")
    assert result.ok
    assert result.intent == "system.undo"
    assert result.permission == "confirm"
    assert result.requires_confirmation is True
    assert result.confirmed is True


def test_security_sensitive_command_is_blocked_before_execution():
    result = make_router(auto_confirm=True).handle("jarvis disable defender")
    assert not result.ok
    assert result.intent == "blocked.security_sensitive"
    assert result.permission == "blocked"
    assert result.action == "blocked"
    assert result.metadata["error_type"] == "blocked_action"
    assert result.metadata["error_severity"] == "high"
