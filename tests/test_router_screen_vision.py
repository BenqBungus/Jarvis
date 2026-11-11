from __future__ import annotations

import builtins

from jarvis.ai_client import JarvisAI
from jarvis.models import CommandResult
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


class FakeScreenVision:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def describe(self, prompt: str = "What is on my screen?") -> CommandResult:
        self.calls.append(prompt)
        return CommandResult(True, f"screen: {prompt}", metadata={"privacy_sensitive": True})

    @staticmethod
    def status() -> CommandResult:
        return CommandResult(True, "screen vision ready")


def make_router(auto_confirm: bool = True) -> CommandRouter:
    router = CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=auto_confirm),
        ai=JarvisAI(dry_run=True),
    )
    router.screen_vision = FakeScreenVision()
    return router


def test_screen_vision_command_requires_confirmation_and_runs_when_allowed():
    router = make_router(auto_confirm=True)

    result = router.handle("jarvis какво има на екрана")

    assert result.ok
    assert result.intent == "vision.screen_describe"
    assert result.action == "screen_describe"
    assert result.requires_confirmation is True
    assert result.metadata["privacy_sensitive"] is True


def test_screen_vision_command_can_be_cancelled(monkeypatch):
    router = make_router(auto_confirm=False)
    monkeypatch.setattr(builtins, "input", lambda _: "NO")

    result = router.handle("jarvis какво гледам")

    assert not result.ok
    assert result.requires_confirmation is True
    assert result.confirmed is False


def test_screen_vision_status_is_safe():
    router = make_router()

    result = router.handle("jarvis провери screen vision")

    assert result.ok
    assert result.intent == "vision.status"
    assert result.action == "screen_vision_status"
    assert result.requires_confirmation is False
