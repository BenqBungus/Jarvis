from __future__ import annotations

from jarvis.ai_client import JarvisAI
from jarvis.browser import PageReader, SearchResult, WebResearcher
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.web_context import WebContext
from jarvis.windows_actions import WindowsActions


class FakeSearchProvider:
    def search(self, query: str, max_results: int = 6) -> list[SearchResult]:
        assert "rtx 4060" in query
        return [SearchResult("RTX comparison", "https://example.com/rtx")]


def test_research_command_uses_web_researcher(tmp_path):
    router = CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=True),
        ai=JarvisAI(dry_run=True),
    )
    router.web_context = WebContext(path=tmp_path / "web_context.json")
    router.researcher = WebResearcher(
        search_provider=FakeSearchProvider(),
        page_reader=PageReader(fetch_bytes=lambda *_args: b"<title>RTX</title><p>Fast card details.</p>"),
        web_context=router.web_context,
        ai=router.ai,
    )

    result = router.handle("jarvis сравни rtx 4060 и rtx 4070")

    assert result.ok
    assert result.intent == "research.web"
    assert result.action == "research_web"
    assert "Sources:" in result.message
    assert router.web_context.pick(1) is not None


def test_system_update_question_does_not_become_research():
    router = CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=True),
        ai=JarvisAI(dry_run=True),
    )

    result = router.handle("jarvis провери windows update")

    assert result.ok
    assert result.action == "check_windows_updates"
