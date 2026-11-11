from __future__ import annotations

import builtins

import pytest

from jarvis.ai_client import JarvisAI
from jarvis.browser import PageReader, SearchResult, WebResearcher
from jarvis.memory import ConversationMemory
from jarvis.models import CommandResult
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.web_context import WebContext
from jarvis.windows_actions import WindowsActions


def make_router(auto_confirm: bool = False, with_ai: bool = True) -> CommandRouter:
    actions = WindowsActions(dry_run=True)
    safety = SafetyPolicy(auto_confirm=auto_confirm)
    ai = JarvisAI(dry_run=True) if with_ai else None
    return CommandRouter(actions=actions, safety=safety, ai=ai)


class FakeSearchProvider:
    def search(self, query: str, max_results: int = 6) -> list[SearchResult]:
        return [SearchResult("Search result", "https://example.com/result", snippet=query)]


def attach_fake_researcher(router: CommandRouter, tmp_path) -> None:
    router.web_context = WebContext(path=tmp_path / "web_context.json")
    router.researcher = WebResearcher(
        search_provider=FakeSearchProvider(),
        page_reader=PageReader(fetch_bytes=lambda *_args: b"<title>Result</title><p>Stable details.</p>"),
        web_context=router.web_context,
        ai=router.ai,
    )


def test_router_runs_voice_diagnostics_for_voice_problem_request(monkeypatch):
    from jarvis.audio import diagnostics

    monkeypatch.setattr(
        diagnostics,
        "build_voice_diagnostics",
        lambda settings=None: CommandResult(True, "Voice Doctor ready", metadata={"voice_diagnostics": {}}),
    )
    router = make_router()

    result = router.handle("jarvis защо не говориш")

    assert result.ok
    assert result.action == "voice_diagnostics"
    assert "Voice Doctor" in result.message


# --- Commands that should dispatch successfully without any confirmation ---

BULGARIAN_OK_COMMANDS = [
    "здравей jarvis отвори facebook",
    "hey jarvis open instagram",
    "jarvis отвори ютуб",
    "джарвис отвори gmail",
    "jarvis отвори plasico.bg",
    "jarvis отвори plasico bg",
    "jarvis отвори plasico точка bg",
    "jarvis увеличи звука",
    "jarvis намали звука",
    "jarvis заглуши звука",
    "jarvis направи звука на 30",
    "jarvis сложи звука на 55%",
    "jarvis отвори windows update",
    "jarvis провери ъпдейт",
    "jarvis провери nvidia драйверите",
    "jarvis провери всички драйвери",
    "jarvis провери chipset драйверите",
    "jarvis провери audio драйверите",
    "jarvis провери network драйверите",
    "jarvis провери bluetooth драйверите",
    "jarvis провери driver updates",
    "jarvis провери температурите",
    "jarvis предупреди ме ако температурите са над 85",
    "jarvis отвори nitrosense",
    "jarvis провери nitrosense ъпдейти",
    "jarvis quiet mode",
    "jarvis режим учене",
    "jarvis режим батерия",
    "jarvis отвори последния файл",
    "jarvis направи ми документ за втората световна война",
    "jarvis какво ми товари компютъра",
    "jarvis провери стартъп програмите",
    "jarvis покажи tools",
    "jarvis създай папка notes",
    "jarvis създай файл notes/todo.txt",
    "jarvis отвори бележник",
    "jarvis отвори калкулатор",
    "jarvis отвори настройки",
    "jarvis какво е инфлация",
    "jarvis провери в интернет последните новини за nvidia",
]


@pytest.mark.parametrize("command", BULGARIAN_OK_COMMANDS)
def test_bulgarian_commands_dispatch_successfully(command, tmp_path):
    router = make_router()
    attach_fake_researcher(router, tmp_path)
    result = router.handle(command)
    assert result.ok, f"{command!r} -> {result.message}"


def test_unknown_bulgarian_command_is_reported_as_unknown():
    router = make_router()
    result = router.handle("jarvis направи ми кафе")
    assert not result.ok


def test_casual_bulgarian_text_falls_back_to_conversation(tmp_path):
    router = make_router()
    router.conversation_memory = ConversationMemory(path=tmp_path / "conversation.jsonl")

    result = router.handle("jarvis скучно ми е")

    assert result.ok
    assert result.intent == "conversation.chat"
    assert "Would chat" in result.message
    assert [turn.role for turn in router.conversation_memory.recent()] == ["user", "assistant"]


def test_compare_question_uses_research_path(tmp_path):
    router = make_router()
    attach_fake_researcher(router, tmp_path)
    result = router.handle("jarvis сравни rtx 4060 и rtx 4070")

    assert result.ok
    assert result.intent == "research.web"
    assert "Would research" in result.message


def test_knowledge_question_without_ai_configured_reports_clearly():
    router = make_router(with_ai=False)
    result = router.handle("jarvis какво е инфлация")
    assert not result.ok
    assert "not configured" in result.message.lower()


def test_list_tools_command_returns_registered_tools():
    router = make_router()
    result = router.handle("jarvis покажи tools")

    assert result.ok
    assert "Available Jarvis tools" in result.message
    assert "open_url" in result.metadata["tools"]


# --- Commands that must go through SafetyPolicy.confirm() first -----------

DESTRUCTIVE_COMMANDS = [
    "jarvis рестартирай лаптопа",
    "jarvis изключи лаптопа",
    "jarvis приспи лаптопа",
    "jarvis спри интернета",
    "jarvis включи интернета",
    "jarvis спри bluetooth",
    "jarvis включи bluetooth",
    "jarvis почисти temp файлове",
    "jarvis режим игра",
]


@pytest.mark.parametrize("command", DESTRUCTIVE_COMMANDS)
def test_destructive_bulgarian_commands_require_typed_yes(monkeypatch, command):
    router = make_router(auto_confirm=False)
    monkeypatch.setattr(builtins, "input", lambda _: "NO")
    result = router.handle(command)
    assert not result.ok
    assert "cancelled" in result.message.lower()


@pytest.mark.parametrize("command", DESTRUCTIVE_COMMANDS)
def test_destructive_bulgarian_commands_proceed_after_typed_yes(monkeypatch, command):
    router = make_router(auto_confirm=False)
    monkeypatch.setattr(builtins, "input", lambda _: "YES")
    result = router.handle(command)
    assert result.ok


@pytest.mark.parametrize("command", DESTRUCTIVE_COMMANDS)
def test_destructive_bulgarian_commands_proceed_with_auto_confirm(command):
    router = make_router(auto_confirm=True)
    result = router.handle(command)
    assert result.ok


def test_safety_policy_is_never_bypassed_by_voice_wake_word_alone():
    # A command that only differs from a destructive one by the wake phrase
    # used must still hit the same confirmation gate.
    router = make_router(auto_confirm=False)
    calls: list[str] = []

    def deny(_prompt: str) -> str:
        calls.append(_prompt)
        return "NO"

    import builtins as _builtins

    original_input = _builtins.input
    _builtins.input = deny
    try:
        result = router.handle("джарвис рестартирай лаптопа")
    finally:
        _builtins.input = original_input

    assert not result.ok
    assert calls, "SafetyPolicy.confirm() should have prompted for input"
