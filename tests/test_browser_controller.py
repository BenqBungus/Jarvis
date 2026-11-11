from __future__ import annotations

from jarvis.browser import BrowserController, SearchResult
from jarvis.web_context import WebContext
from jarvis.windows_actions import WindowsActions


class FakeSearchProvider:
    def search(self, query: str, max_results: int = 6) -> list[SearchResult]:
        return [
            SearchResult(f"{query} one", "https://example.com/one"),
            SearchResult(f"{query} two", "https://example.com/two"),
        ][:max_results]


def test_browser_search_saves_numbered_results(tmp_path):
    context = WebContext(path=tmp_path / "web_context.json")
    controller = BrowserController(
        actions=WindowsActions(dry_run=True),
        web_context=context,
        search_provider=FakeSearchProvider(),
    )

    result = controller.search("gaming mouse")

    assert result.ok
    assert "Saved browser results" in result.message
    assert result.metadata["candidates"] == ["https://example.com/one", "https://example.com/two"]
    assert context.pick(2).url == "https://example.com/two"


def test_browser_open_result_uses_preferred_browser(tmp_path):
    context = WebContext(path=tmp_path / "web_context.json")
    controller = BrowserController(
        actions=WindowsActions(dry_run=True),
        web_context=context,
        search_provider=FakeSearchProvider(),
    )
    controller.search("gaming mouse")

    result = controller.open_result(2)

    assert result.ok
    assert "Would open https://example.com/two" in result.message
    assert result.metadata["ordinal"] == 2
    assert context.recent_opened()[0].url == "https://example.com/two"


def test_browser_open_matching_result_uses_saved_title(tmp_path):
    context = WebContext(path=tmp_path / "web_context.json")
    controller = BrowserController(
        actions=WindowsActions(dry_run=True),
        web_context=context,
        search_provider=FakeSearchProvider(),
    )
    controller.search("gaming mouse")

    result = controller.open_matching_result("two")

    assert result.ok
    assert "Would open https://example.com/two" in result.message
    assert result.metadata["match_query"] == "two"
    assert result.metadata["ordinal"] == 2
    assert context.recent_opened()[0].match_query == "two"


def test_browser_search_and_open_combines_result_metadata(tmp_path):
    context = WebContext(path=tmp_path / "web_context.json")
    controller = BrowserController(
        actions=WindowsActions(dry_run=True),
        web_context=context,
        search_provider=FakeSearchProvider(),
    )

    result = controller.search_and_open("gaming mouse", ordinal=1)

    assert result.ok
    assert "https://example.com/one" in result.message
    assert result.metadata["query"] == "gaming mouse"
    assert len(result.metadata["browser_results"]) == 2


def test_browser_automation_status_reports_missing_playwright(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "playwright.sync_api":
            raise ImportError("missing")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    controller = BrowserController(actions=WindowsActions(dry_run=True), search_provider=FakeSearchProvider())

    result = controller.automation_status()

    assert not result.ok
    assert result.metadata["playwright_available"] is False
