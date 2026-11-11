from __future__ import annotations

import builtins

from jarvis.intent_parser import ParsedIntent
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


class FakeAI:
    dry_run = False

    def __init__(self, parsed: ParsedIntent) -> None:
        self.parsed = parsed

    def parse_intent(self, _message, _registry, history=None):
        return self.parsed

    def answer_conversation(self, message, history=None):
        from jarvis.models import CommandResult

        return CommandResult(True, f"chat: {message}")

    def answer_with_web_search(self, question):
        from jarvis.models import CommandResult

        return CommandResult(True, f"web: {question}")


def make_router(parsed: ParsedIntent, auto_confirm: bool = False) -> CommandRouter:
    return CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=auto_confirm),
        ai=FakeAI(parsed),
    )


def test_llm_intent_tool_call_executes_registered_safe_tool():
    router = make_router(
        ParsedIntent(
            kind="tool_call",
            tool="open_url",
            arguments={"url": "https://facebook.com"},
            reason="User asked to open Facebook.",
        )
    )

    result = router.handle("jarvis можеш ли да отвориш facebook")

    assert result.ok
    assert "Would open https://facebook.com" in result.message
    assert result.intent == "llm.tool.open_url"
    assert result.metadata["tool"] == "open_url"
    assert result.metadata["intent_reason"] == "User asked to open Facebook."
    assert result.metadata["llm_tool_trace"]["source"] == "llm_intent_parser"
    assert result.metadata["llm_tool_trace"]["status"] == "executed"
    assert result.metadata["llm_tool_trace"]["selected_tool"] == "open_url"
    assert result.metadata["llm_tool_trace"]["result_ok"] is True


def test_conversation_first_handles_open_site_before_static_open_rules():
    router = make_router(
        ParsedIntent(
            kind="tool_call",
            tool="open_url",
            arguments={"url": "https://plasico.bg"},
            reason="User asked to open a site by free-form name.",
        )
    )

    result = router.handle("jarvis отвори plasico")

    assert result.ok
    assert result.intent == "llm.tool.open_url"
    assert result.metadata["tool"] == "open_url"
    assert result.metadata["tool_arguments"]["url"] == "https://plasico.bg"


def test_conversation_first_keeps_direct_restart_confirmation_local(monkeypatch):
    router = make_router(
        ParsedIntent(kind="conversation", message="няма нужда от рестарт", reason="Bad parser result."),
        auto_confirm=False,
    )
    monkeypatch.setattr(builtins, "input", lambda _: "NO")

    result = router.handle("jarvis рестартирай лаптопа")

    assert not result.ok
    assert result.intent == "system.restart"
    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert "Restart cancelled" in result.message


def test_llm_intent_confirmation_can_cancel_admin_tool(monkeypatch):
    router = make_router(
        ParsedIntent(kind="tool_call", tool="disable_internet", arguments={}, reason="Network change."),
        auto_confirm=False,
    )
    monkeypatch.setattr(builtins, "input", lambda _: "NO")

    result = router.handle("jarvis би ли спрял интернета")

    assert not result.ok
    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.metadata["llm_tool_trace"]["status"] == "cancelled"
    assert result.metadata["llm_tool_trace"]["selected_tool"] == "disable_internet"


def test_llm_intent_conversation_uses_chat_path():
    router = make_router(
        ParsedIntent(kind="conversation", message="скучно ми е", reason="Casual chat.")
    )

    result = router.handle("jarvis май ми е скучно")

    assert result.ok
    assert result.intent == "llm.conversation"
    assert result.message == "chat: скучно ми е"


def test_llm_intent_web_answer_uses_web_path():
    router = make_router(
        ParsedIntent(kind="web_answer", message="latest nvidia drivers", reason="Current facts.")
    )

    result = router.handle("jarvis би ли проверил актуални новини за amd")

    assert result.ok
    assert result.intent == "llm.web_answer"
    assert result.message == "web: latest nvidia drivers"


def test_llm_intent_unknown_tool_records_trace():
    router = make_router(
        ParsedIntent(kind="tool_call", tool="run_shell", arguments={"command": "whoami"}, reason="Bad tool.")
    )

    result = router.handle("jarvis run whoami")

    assert not result.ok
    assert result.permission == "blocked"
    assert result.metadata["llm_tool_trace"]["status"] == "unregistered_tool"
    assert result.metadata["llm_tool_trace"]["selected_tool"] == "run_shell"


def test_llm_intent_low_confidence_tool_asks_for_clarification():
    router = make_router(
        ParsedIntent(
            kind="tool_call",
            tool="open_url",
            arguments={"url": "https://facebook.com"},
            reason="The user may want Facebook but it is not clear.",
            confidence=0.4,
            clarification_question="Do you want me to open Facebook?",
        )
    )

    result = router.handle("jarvis онова с фейс")

    assert not result.ok
    assert result.intent == "llm.clarification"
    assert result.action == "ask_clarification"
    assert "Do you want me to open Facebook" in result.message
    assert result.metadata["llm_tool_trace"]["status"] == "needs_clarification"
    assert result.metadata["llm_tool_trace"]["selected_tool"] == "open_url"


def test_llm_intent_missing_required_argument_asks_for_value_then_runs():
    router = make_router(
        ParsedIntent(
            kind="tool_call",
            tool="open_url",
            arguments={},
            reason="The user wants to open a site but no URL was provided.",
            confidence=0.95,
        )
    )

    asked = router.handle("jarvis можеш ли да отвориш това")
    resumed = router.handle("https://facebook.com")

    assert not asked.ok
    assert asked.intent == "llm.argument_clarification"
    assert asked.action == "ask_tool_argument"
    assert asked.metadata["missing_arguments"] == ["url"]
    assert asked.metadata["llm_tool_trace"]["status"] == "missing_arguments"
    assert resumed.ok
    assert resumed.intent == "llm.tool.open_url"
    assert resumed.metadata["tool_arguments"]["url"] == "https://facebook.com"
    assert resumed.metadata["clarification_resolved"] is True


def test_llm_intent_blank_required_argument_asks_for_value_then_runs():
    router = make_router(
        ParsedIntent(
            kind="tool_call",
            tool="open_url",
            arguments={"url": "  "},
            reason="The model left the URL blank.",
            confidence=0.95,
        )
    )

    asked = router.handle("jarvis можеш ли да отвориш това")
    resumed = router.handle("https://facebook.com")

    assert not asked.ok
    assert asked.intent == "llm.argument_clarification"
    assert asked.metadata["missing_arguments"] == ["url"]
    assert resumed.ok
    assert resumed.intent == "llm.tool.open_url"
    assert resumed.metadata["tool_arguments"]["url"] == "https://facebook.com"
    assert resumed.metadata["clarification_resolved"] is True


def test_llm_intent_unexpected_argument_is_rejected_before_execution():
    router = make_router(
        ParsedIntent(
            kind="tool_call",
            tool="open_url",
            arguments={"url": "https://facebook.com", "shell": "whoami"},
            reason="The model added an unsafe extra argument.",
            confidence=0.95,
        )
    )

    result = router.handle("jarvis можеш ли да отвориш facebook")

    assert not result.ok
    assert result.intent == "llm.argument_clarification"
    assert result.metadata["unexpected_arguments"] == ["shell"]
    assert result.metadata["llm_tool_trace"]["status"] == "unexpected_arguments"


def test_llm_intent_low_confidence_admin_tool_asks_before_confirmation(monkeypatch):
    router = make_router(
        ParsedIntent(
            kind="tool_call",
            tool="disable_internet",
            arguments={},
            reason="The phrase sounded like a network command.",
            confidence=0.7,
            clarification_question="Should I disable the internet connection?",
        ),
        auto_confirm=True,
    )
    prompts: list[str] = []
    monkeypatch.setattr(router.safety, "confirm", lambda action, reason: prompts.append(action) or True)

    result = router.handle("jarvis май спри нещо")

    assert not result.ok
    assert result.intent == "llm.clarification"
    assert prompts == []
    assert result.metadata["llm_tool_trace"]["status"] == "needs_clarification"


def test_llm_intent_clarification_yes_resumes_pending_safe_tool():
    router = make_router(
        ParsedIntent(
            kind="tool_call",
            tool="open_url",
            arguments={"url": "https://facebook.com"},
            reason="The user may want Facebook but it is not clear.",
            confidence=0.4,
            clarification_question="Do you want me to open Facebook?",
        )
    )

    asked = router.handle("jarvis онова с фейс")
    resumed = router.handle("да")

    assert asked.intent == "llm.clarification"
    assert resumed.ok
    assert resumed.intent == "llm.tool.open_url"
    assert resumed.action == "open_url"
    assert "Would open https://facebook.com" in resumed.message
    assert resumed.metadata["clarification_resolved"] is True
    assert resumed.metadata["llm_tool_trace"]["status"] == "executed"


def test_llm_intent_clarification_no_cancels_pending_tool():
    router = make_router(
        ParsedIntent(
            kind="tool_call",
            tool="open_url",
            arguments={"url": "https://facebook.com"},
            reason="The user may want Facebook but it is not clear.",
            confidence=0.4,
            clarification_question="Do you want me to open Facebook?",
        )
    )

    router.handle("jarvis онова с фейс")
    cancelled = router.handle("не")

    assert not cancelled.ok
    assert cancelled.intent == "llm.clarification_cancelled"
    assert cancelled.metadata["llm_tool_trace"]["status"] == "clarification_cancelled"


def test_llm_intent_clarification_yes_still_uses_confirmation_for_admin(monkeypatch):
    router = make_router(
        ParsedIntent(
            kind="tool_call",
            tool="disable_internet",
            arguments={},
            reason="The phrase sounded like a network command.",
            confidence=0.7,
            clarification_question="Should I disable the internet connection?",
        ),
        auto_confirm=False,
    )
    monkeypatch.setattr(builtins, "input", lambda _: "NO")

    asked = router.handle("jarvis май спри нещо")
    resumed = router.handle("да")

    assert asked.intent == "llm.clarification"
    assert not resumed.ok
    assert resumed.intent == "llm.tool.disable_internet"
    assert resumed.requires_confirmation is True
    assert resumed.confirmed is False
    assert resumed.metadata["clarification_resolved"] is True
    assert resumed.metadata["llm_tool_trace"]["status"] == "cancelled"
