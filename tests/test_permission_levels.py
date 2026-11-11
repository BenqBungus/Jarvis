"""Kid and Guest rules (src/jarvis/permission_levels.py) at every entry point:
the tool registry, rule-based router commands, planned tools, Live voice
and full access."""
from __future__ import annotations

import pytest

from jarvis.permission_levels import LevelGate, intent_block, tool_allowed, visible_tool_specs
from jarvis.permissions import IntentMetadata
from jarvis.realtime import RealtimeVoiceSession, realtime_tool_schemas
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.tool_registry import ToolCall
from jarvis import trusted_actions
from jarvis.user_settings import JarvisSettings
from jarvis.windows_actions import WindowsActions


class _CountingSafety(SafetyPolicy):
    def __init__(self) -> None:
        super().__init__()
        self.asked = []

    def confirm(self, action: str, details: str = "") -> bool:
        self.asked.append(action)
        return True


@pytest.fixture
def router():
    safety = _CountingSafety()
    router = CommandRouter(WindowsActions(dry_run=True), safety, settings=JarvisSettings())
    gate = LevelGate("adult")
    router.tools.level_gate = gate
    yield router
    trusted_actions.allow_full_access(True)


def _spec(router, name):
    return router.tools.get(name).spec


@pytest.mark.parametrize(("name", "kid", "guest"), [
    ("shutdown", False, False), ("disable_internet", False, False), ("install_nvidia_driver", False, False),
    ("gmail_search", False, False), ("recycle_local_path", False, False), ("end_process", False, False),
    ("start_screen_sharing", False, False), ("run_autonomous_task", False, False), ("browser_fill", False, False),
    ("remember", True, False), ("search_local_files", True, False), ("open_application", True, False),
    ("game_mode", True, False), ("undo_last_action", True, False), ("analyze_document", True, False),
    ("set_volume", True, True), ("research_web", True, True), ("open_url", True, True), ("chat", True, True),
    ("system_temperatures", True, True), ("cancel_task", True, True), ("teach_task", True, True),
])
def test_what_each_level_may_use(router, name, kid, guest):
    spec = _spec(router, name)
    assert tool_allowed("adult", spec) == (True, "")
    assert tool_allowed("kid", spec)[0] is kid
    assert tool_allowed("guest", spec)[0] is guest
    if not kid:
        assert tool_allowed("kid", spec)[1].startswith("An adult profile is needed to ")


def test_blocked_tools_are_refused_and_hidden_from_the_ai(router):
    router.tools.level_gate.set_level("kid")
    result = router.tools.execute(ToolCall("shutdown"))
    assert not result.ok and result.metadata["blocked_by_level"] == "kid"
    assert result.metadata["executed"] is False
    names = {schema["name"] for schema in router.tools.schemas()}
    assert "shutdown" not in names and "gmail_search" not in names and "set_volume" in names
    assert "shutdown" not in {schema["name"] for schema in realtime_tool_schemas(router.tools)}
    assert len(router.tools.list_specs()) > len(visible_tool_specs("kid", router.tools))  # the UI still lists all


def test_rule_based_commands_are_blocked_before_anything_runs(router):
    router.tools.level_gate.set_level("kid")
    result = router.handle("изключи компютъра")
    assert not result.ok and result.metadata["blocked_by_level"] == "kid"
    assert router.safety.asked == []  # no confirmation dialog for a blocked request
    router.tools.level_gate.set_level("adult")
    router.handle("изключи компютъра")
    assert router.safety.asked  # adults are asked as before


def test_guest_commands_and_intents(router):
    assert intent_block("guest", "memory.remember") and not intent_block("kid", "memory.remember")
    assert intent_block("kid", "network.disable_internet") and not intent_block("adult", "network.disable_internet")
    router.tools.level_gate.set_level("guest")
    assert router.handle("запомни, че любимата ми игра е Valorant").metadata.get("blocked_by_level") == "guest"
    assert router.tools.level_gate.check_intent(IntentMetadata("system.volume_set", "set_volume")) is None


def test_live_voice_refuses_before_the_confirmation_dialog(router):
    router.tools.level_gate.set_level("kid")
    execute = RealtimeVoiceSession.tool_executor_from_router(router)
    payload = execute("shutdown", {})
    assert payload["ok"] is False and payload["metadata"]["blocked_by_level"] == "kid"
    assert router.safety.asked == []


def test_full_access_never_applies_to_kids(router):
    settings = JarvisSettings(safety={"full_access_local": True})
    assert trusted_actions.trusted_local_action(settings, "create_folder")
    trusted_actions.allow_full_access(False)
    assert not trusted_actions.trusted_local_action(settings, "create_folder")
