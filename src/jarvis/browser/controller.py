from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus

from ..models import CommandResult
from ..web_context import WebCandidate, WebContext
from .research import DuckDuckGoSearchProvider, SearchProvider, SearchResult


@dataclass(frozen=True)
class BrowserSearchSession:
    query: str
    results: list[SearchResult]


class BrowserController:
    """Search context and an optional isolated Playwright session."""

    def __init__(
        self,
        *,
        actions,
        web_context: WebContext | None = None,
        search_provider: SearchProvider | None = None,
        dry_run: bool | None = None,
    ) -> None:
        self.actions = actions
        self.web_context = web_context or WebContext()
        self.search_provider = search_provider or DuckDuckGoSearchProvider()
        self.dry_run = getattr(actions, "dry_run", False) if dry_run is None else dry_run
        self._managed = None

    def managed_call(self, operation: str, **arguments) -> CommandResult:
        return self._managed_browser().call(operation, **arguments)

    def _managed_browser(self):
        if self._managed is None:
            from .managed import ManagedBrowser

            discover = getattr(self.actions, "_preferred_browser_command", None)
            self._managed = ManagedBrowser(
                executable_path=discover() if discover else None, dry_run=self.dry_run)
        return self._managed

    def close(self) -> None:
        if self._managed is not None:
            self._managed.close()

    def search(self, query: str, max_results: int = 6) -> CommandResult:
        cleaned = query.strip()
        if not cleaned:
            return CommandResult(False, "I need something to search for.")
        limit = max(1, min(10, int(max_results)))

        try:
            results = self.search_provider.search(cleaned, max_results=limit)
        except Exception as exc:
            return CommandResult(False, f"Browser search failed: {exc}")

        if not results:
            return CommandResult(False, f"I could not find browser results for: {cleaned}")

        self.web_context.save_candidates(
            [WebCandidate(title=result.title, url=result.url) for result in results],
            query=cleaned,
        )
        lines = [f"Saved browser results for: {cleaned}"]
        for index, result in enumerate(results, start=1):
            lines.append(f"{index}. {result.title} - {result.url}")
        lines.append("Say 'отвори първия' or 'прочети втория' to continue.")
        return CommandResult(
            True,
            "\n".join(lines),
            metadata={
                "query": cleaned,
                "browser_results": [
                    {"title": result.title, "url": result.url, "snippet": result.snippet}
                    for result in results
                ],
                "candidates": [result.url for result in results],
            },
        )

    def open_result(self, ordinal: int = 1) -> CommandResult:
        candidate = self.web_context.pick(int(ordinal))
        if candidate is None:
            return CommandResult(False, "I do not have a saved browser result for that number yet.")
        result = self.actions.open_url(candidate.url)
        if result.ok:
            self.web_context.record_opened(candidate, ordinal=int(ordinal))
        return result.with_metadata(
            metadata={
                **result.metadata,
                "ordinal": int(ordinal),
                "title": candidate.title,
                "url": candidate.url,
            }
        )

    def open_matching_result(self, query: str) -> CommandResult:
        cleaned = query.strip()
        if not cleaned:
            return CommandResult(False, "I need text to match against saved browser results.")
        match = self.web_context.find(cleaned)
        if match is None:
            return CommandResult(False, f"I do not have a saved browser result matching: {cleaned}")
        ordinal, candidate = match
        result = self.actions.open_url(candidate.url)
        if result.ok:
            self.web_context.record_opened(candidate, ordinal=ordinal, match_query=cleaned)
        return result.with_metadata(
            metadata={
                **result.metadata,
                "match_query": cleaned,
                "ordinal": ordinal,
                "title": candidate.title,
                "url": candidate.url,
            }
        )

    def search_and_open(self, query: str, ordinal: int = 1, max_results: int = 6) -> CommandResult:
        search_result = self.search(query, max_results=max_results)
        if not search_result.ok:
            return search_result
        open_result = self.open_result(ordinal)
        return open_result.with_metadata(
            metadata={
                **open_result.metadata,
                "query": query.strip(),
                "browser_results": search_result.metadata.get("browser_results", []),
            }
        )

    def open_search_page(self, query: str) -> CommandResult:
        cleaned = query.strip()
        if not cleaned:
            return CommandResult(False, "I need something to search for.")
        url = f"https://www.google.com/search?q={quote_plus(cleaned)}"
        result = self.actions.open_url(url)
        return result.with_metadata(metadata={**result.metadata, "query": cleaned, "url": url})

    def automation_status(self) -> CommandResult:
        return self._managed_browser().status()
