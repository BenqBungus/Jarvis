from __future__ import annotations

from jarvis.ai_client import JarvisAI
from jarvis.browser import BrowserController, SearchResult
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.web_context import WebContext
from jarvis.windows_actions import WindowsActions


class FakeSearchProvider:
    def search(self, query: str, max_results: int = 6) -> list[SearchResult]:
        assert query
        return [
            SearchResult("First result", "https://example.com/first"),
            SearchResult("Plasico result", "https://plasico.bg/search?q=mouse"),
        ][:max_results]


def make_router(tmp_path) -> CommandRouter:
    router = CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=True),
        ai=JarvisAI(dry_run=True),
    )
    router.web_context = WebContext(path=tmp_path / "web_context.json")
    router.browser = BrowserController(
        actions=router.actions,
        web_context=router.web_context,
        search_provider=FakeSearchProvider(),
    )
    return router


def test_router_browser_search_saves_results(tmp_path):
    router = make_router(tmp_path)

    result = router.handle("jarvis търси в браузъра gaming mouse")

    assert result.ok
    assert result.intent == "browser.search"
    assert result.action == "browser_search"
    assert router.web_context.pick(1).url == "https://example.com/first"


def test_router_browser_search_and_open_first_result(tmp_path):
    router = make_router(tmp_path)

    result = router.handle("jarvis потърси gaming mouse и отвори първия")

    assert result.ok
    assert result.intent == "browser.search_and_open"
    assert result.action == "browser_search_and_open"
    assert "Would open https://example.com/first" in result.message


def test_router_opens_saved_browser_result_by_matching_text(tmp_path):
    router = make_router(tmp_path)
    router.handle("jarvis търси в браузъра gaming mouse")

    result = router.handle("jarvis отвори резултата за plasico")

    assert result.ok
    assert result.intent == "browser.open_matching_result"
    assert result.action == "browser_open_matching_result"
    assert "https://plasico.bg" in result.message
    assert result.metadata["ordinal"] == 2


def test_router_browser_automation_status(tmp_path):
    router = make_router(tmp_path)

    result = router.handle("jarvis провери playwright")

    assert result.action == "browser_automation_status"
    assert "Playwright" in result.message
