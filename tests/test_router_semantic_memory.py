from __future__ import annotations

from jarvis.memory import EpisodicMemory, LongTermMemory, SemanticMemorySearch
from jarvis.intent_parser import ParsedIntent
from jarvis.models import CommandResult
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


def make_router(tmp_path) -> CommandRouter:
    router = CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=True),
        ai=None,
    )
    router.long_term_memory = LongTermMemory(path=tmp_path / "memory.sqlite3")
    router.episodic_memory = EpisodicMemory(path=tmp_path / "episodes.jsonl", state_path=tmp_path / "episodes_state.json")
    router.semantic_memory = SemanticMemorySearch(
        long_term_memory=router.long_term_memory,
        episodic_memory=router.episodic_memory,
    )
    return router


def test_router_can_search_memory_semantically(tmp_path):
    router = make_router(tmp_path)
    router.long_term_memory.remember("Preferred browser is Opera GX", category="preference", importance=5)

    result = router.handle("jarvis търси семантично в паметта любим браузър")

    assert result.ok
    assert result.intent == "memory.semantic_search"
    assert result.action == "semantic_memory_search"
    assert "Preferred browser is Opera GX" in result.message


def test_router_passes_relevant_memory_to_conversation_ai(tmp_path):
    class MemoryAwareAI:
        def parse_intent(self, _message, _registry, history=None):
            return ParsedIntent(kind="unknown")

        def answer_conversation(self, message, history=None, memory_context=None):
            return CommandResult(True, f"chat: {message} / memory={memory_context[0]['content']}")

    router = make_router(tmp_path)
    router.ai = MemoryAwareAI()
    router.long_term_memory.remember("Preferred browser is Opera GX", category="preference", importance=5)

    result = router.handle("jarvis помниш ли любим браузър")

    assert result.ok
    assert result.intent == "conversation.chat"
    assert "Preferred browser is Opera GX" in result.message
    assert result.metadata["memory_context_count"] == 1
    assert result.metadata["memory_context_hits"][0]["kind"] == "long_term"


def test_router_can_disable_memory_context_for_conversation_ai(tmp_path):
    class MemoryAwareAI:
        def parse_intent(self, _message, _registry, history=None):
            return ParsedIntent(kind="unknown")

        def answer_conversation(self, message, history=None, memory_context=None):
            return CommandResult(True, f"memory_count={len(memory_context or [])}")

    router = make_router(tmp_path)
    router.ai = MemoryAwareAI()
    router.settings.openai["use_memory_context"] = False
    router.long_term_memory.remember("Preferred browser is Opera GX", category="preference", importance=5)

    result = router.handle("jarvis помниш ли любим браузър")

    assert result.ok
    assert result.message == "memory_count=0"
    assert "memory_context_hits" not in result.metadata
