from __future__ import annotations

from jarvis.audit import AuditLogger
from jarvis.intent_parser import ParsedIntent
from jarvis.memory import ConversationMemory, EpisodicMemory
from jarvis.models import CommandResult
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


class FakeAI:
    dry_run = False

    def parse_intent(self, _message, _registry, history=None):
        return ParsedIntent(kind="unknown")

    def answer_conversation(self, message, history=None):
        return CommandResult(True, f"chat: {message}")

    def answer_with_web_search(self, question):
        return CommandResult(True, f"web: {question}")

    def summarize_episode(self, turns):
        return CommandResult(True, f"episode with {len(turns)} turns")


def make_router(tmp_path, *, dry_run: bool = True) -> CommandRouter:
    router = CommandRouter(
        actions=WindowsActions(dry_run=dry_run),
        safety=SafetyPolicy(auto_confirm=True),
        ai=FakeAI(),
    )
    router.conversation_memory = ConversationMemory(path=tmp_path / "conversation.jsonl")
    router.episodic_memory = EpisodicMemory(
        path=tmp_path / "episodes.jsonl",
        state_path=tmp_path / "episodes_state.json",
        min_new_turns=2,
    )
    router.audit_reader = AuditLogger(path=tmp_path / "audit.jsonl")
    return router


def test_router_can_summarize_conversation_episode(tmp_path):
    router = make_router(tmp_path)
    router.conversation_memory.add_turn("user", "работим по Jarvis")
    router.conversation_memory.add_turn("assistant", "добавям памет")

    result = router.handle("jarvis обобщи разговора")

    assert result.ok
    assert result.intent == "memory.episode_summarize"
    assert result.action == "summarize_conversation_episode"
    assert result.metadata["episode_created"] is True
    assert "episode with 2 turns" in result.message


def test_router_can_show_episodic_memory(tmp_path):
    router = make_router(tmp_path)
    router.episodic_memory.add_summary("Discussed browser control.", topics=["browser"])

    result = router.handle("jarvis покажи епизодична памет browser")

    assert result.ok
    assert result.intent == "memory.episode_search"
    assert result.action == "list_episode_summaries"
    assert "Discussed browser control" in result.message


def test_router_auto_summarizes_after_enough_real_conversation_turns(tmp_path):
    router = make_router(tmp_path, dry_run=False)

    result = router.handle("jarvis скучно ми е")

    assert result.ok
    assert router.episodic_memory.recent()[0].summary == "episode with 2 turns"


def test_router_does_not_auto_summarize_in_dry_run(tmp_path):
    router = make_router(tmp_path, dry_run=True)

    result = router.handle("jarvis скучно ми е")

    assert result.ok
    assert router.episodic_memory.recent() == []


def test_router_can_summarize_recent_actions_as_episode(tmp_path):
    router = make_router(tmp_path)
    router.audit_reader.log(
        "jarvis отвори facebook",
        CommandResult(True, "Opened", intent="apps_or_web.open", action="open_url"),
        dry_run=True,
        source="cli",
        latency_ms=1.2,
    )

    result = router.handle("jarvis обобщи действията от последните 10 минути")

    assert result.ok
    assert result.intent == "memory.action_episode_summarize"
    assert result.action == "summarize_action_episode"
    assert result.metadata["episode_created"] is True
    assert result.metadata["action_count"] == 1
    assert router.episodic_memory.recent()[0].source == "actions"
