from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from ..models import CommandResult
from ..prompt_safety import prompt_guard_metadata
from ..web_context import WebCandidate, WebContext
from .page_reader import PageReader


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True)
class ResearchSource:
    title: str
    url: str
    snippet: str = ""
    excerpt: str = ""
    quality_score: int = 0
    quality_label: str = "unknown"
    quality_reasons: tuple[str, ...] = ()

    def to_metadata(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "excerpt": self.excerpt,
            "quality_score": self.quality_score,
            "quality_label": self.quality_label,
            "quality_reasons": list(self.quality_reasons),
        }


class SearchProvider(Protocol):
    def search(self, query: str, max_results: int = 6) -> list[SearchResult]:
        ...


class _DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[SearchResult] = []
        self._href: str | None = None
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = {name: value or "" for name, value in attrs}
        href = attr_map.get("href", "")
        css_class = attr_map.get("class", "")
        if "result__a" not in css_class and "uddg=" not in href:
            return
        self._href = _normalize_result_url(href)
        self._title_parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._href:
            return
        title = " ".join(part.strip() for part in self._title_parts if part.strip())
        if title and self._href.startswith(("http://", "https://")):
            self.results.append(SearchResult(title=title, url=self._href))
        self._href = None
        self._title_parts = []


def _normalize_result_url(href: str) -> str:
    if href.startswith("//duckduckgo.com/l/"):
        href = "https:" + href
    parsed = urlparse(href)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return unquote(query["uddg"][0])
    return href


class DuckDuckGoSearchProvider:
    def __init__(
        self,
        *,
        endpoint: str = "https://duckduckgo.com/html/",
        fetch_bytes=None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.endpoint = endpoint
        self.fetch_bytes = fetch_bytes or self._fetch_bytes
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, max_results: int = 6) -> list[SearchResult]:
        cleaned = query.strip()
        if not cleaned:
            return []
        url = f"{self.endpoint}?q={quote_plus(cleaned)}"
        html = self.fetch_bytes(url, self.timeout_seconds).decode("utf-8", errors="replace")
        parser = _DuckDuckGoResultParser()
        parser.feed(html)

        seen: set[str] = set()
        results: list[SearchResult] = []
        for result in parser.results:
            if result.url in seen:
                continue
            seen.add(result.url)
            results.append(result)
            if len(results) >= max_results:
                break
        return results

    @staticmethod
    def _fetch_bytes(url: str, timeout_seconds: float) -> bytes:
        request = Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Jarvis/0.1"
                )
            },
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read(750_000)


class WebResearcher:
    def __init__(
        self,
        *,
        search_provider: SearchProvider | None = None,
        page_reader: PageReader | None = None,
        web_context: WebContext | None = None,
        ai=None,
    ) -> None:
        self.search_provider = search_provider or DuckDuckGoSearchProvider()
        self.page_reader = page_reader or PageReader()
        self.web_context = web_context or WebContext()
        self.ai = ai

    def research(self, query: str, max_sources: int = 3) -> CommandResult:
        cleaned = query.strip()
        if not cleaned:
            return CommandResult(False, "I need a topic to research.")

        limit = max(1, min(5, int(max_sources)))
        try:
            search_results = self.search_provider.search(cleaned, max_results=max(6, limit))
        except Exception as exc:
            return CommandResult(False, f"Web search failed: {exc}")

        if not search_results:
            return CommandResult(False, f"I could not find web results for: {cleaned}")

        self.web_context.save_candidates(
            [WebCandidate(title=result.title, url=result.url) for result in search_results],
            query=cleaned,
        )

        sources: list[ResearchSource] = []
        for result in search_results[:limit]:
            page_result = self.page_reader.extract(result.url)
            excerpt = ""
            if page_result.ok:
                excerpt = str(page_result.metadata.get("excerpt", "")).strip()
            quality = score_research_source(result.title, result.url, snippet=result.snippet, excerpt=excerpt)
            sources.append(
                ResearchSource(
                    title=result.title,
                    url=result.url,
                    snippet=result.snippet,
                    excerpt=excerpt,
                    quality_score=quality["score"],
                    quality_label=quality["label"],
                    quality_reasons=tuple(quality["reasons"]),
                )
            )

        summary = self._summarize(cleaned, sources)
        source_lines = [f"{index}. {source.title} - {source.url}" for index, source in enumerate(sources, start=1)]
        message = summary
        if source_lines:
            message += "\n\nSources:\n" + "\n".join(source_lines)
            message += "\n\nSay 'отвори първия' or 'прочети втория' to continue from these results."

        return CommandResult(
            True,
            message,
            metadata={
                "query": cleaned,
                "sources": [source.to_metadata() for source in sources],
                "source_quality": summarize_source_quality(sources),
                "source_coverage": analyze_source_coverage(sources),
                "candidates": [result.url for result in search_results],
                "untrusted_web_content": True,
                **prompt_guard_metadata("web_research"),
            },
        )

    def _summarize(self, query: str, sources: list[ResearchSource]) -> str:
        if self.ai is not None and hasattr(self.ai, "summarize_research") and not getattr(self.ai, "dry_run", False):
            result = self.ai.summarize_research(query, sources)
            if result.ok:
                return result.message

        if self.ai is not None and getattr(self.ai, "dry_run", False):
            return f"Would research with {self.ai.model}: {query}"

        lines = [f"I found sources for: {query}"]
        for index, source in enumerate(sources, start=1):
            detail = source.excerpt or source.snippet
            if detail:
                quality = f"{source.quality_label} quality" if source.quality_label != "unknown" else "unknown quality"
                lines.append(f"{index}. [{quality}] {detail[:240]}")
        return "\n".join(lines)


def score_research_source(title: str, url: str, *, snippet: str = "", excerpt: str = "") -> dict[str, Any]:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    title_text = title.strip()
    snippet_text = snippet.strip()
    excerpt_text = excerpt.strip()
    reasons: list[str] = []
    score = 35

    if parsed.scheme == "https":
        score += 12
        reasons.append("https")
    else:
        score -= 10
        reasons.append("not_https")

    if title_text:
        score += 8
        reasons.append("has_title")
    if snippet_text:
        score += 6
        reasons.append("has_snippet")

    excerpt_len = len(excerpt_text)
    if excerpt_len >= 600:
        score += 24
        reasons.append("substantial_excerpt")
    elif excerpt_len >= 160:
        score += 14
        reasons.append("useful_excerpt")
    elif excerpt_len:
        score += 5
        reasons.append("thin_excerpt")
    else:
        score -= 22
        reasons.append("no_extracted_text")

    if hostname.endswith((".gov", ".edu")):
        score += 15
        reasons.append("institutional_domain")
    elif hostname.endswith(".org"):
        score += 8
        reasons.append("organization_domain")

    lower_all = f"{title_text} {snippet_text} {url}".lower()
    if any(marker in lower_all for marker in ("sponsored", "affiliate", "coupon", "promo code", "adserver")):
        score -= 15
        reasons.append("commercial_or_ad_marker")
    if any(marker in lower_all for marker in ("forum", "reddit.com", "quora.com")):
        score -= 8
        reasons.append("community_source")

    score = max(0, min(100, score))
    if score >= 75:
        label = "high"
    elif score >= 50:
        label = "medium"
    else:
        label = "low"
    return {"score": score, "label": label, "reasons": reasons}


def summarize_source_quality(sources: list[ResearchSource]) -> dict[str, Any]:
    if not sources:
        return {"count": 0, "average_score": 0, "labels": {}}
    labels: dict[str, int] = {}
    for source in sources:
        labels[source.quality_label] = labels.get(source.quality_label, 0) + 1
    average = round(sum(source.quality_score for source in sources) / len(sources), 1)
    return {
        "count": len(sources),
        "average_score": average,
        "labels": labels,
        "low_quality_count": labels.get("low", 0),
    }


def analyze_source_coverage(sources: list[ResearchSource]) -> dict[str, Any]:
    sources_with_excerpt = [source for source in sources if source.excerpt.strip()]
    conflict_markers = _conflict_markers(sources_with_excerpt)
    if len(sources_with_excerpt) >= 3:
        coverage_label = "multi_source"
    elif len(sources_with_excerpt) >= 2:
        coverage_label = "limited"
    elif len(sources_with_excerpt) == 1:
        coverage_label = "single_source"
    else:
        coverage_label = "no_extracted_sources"
    return {
        "source_count": len(sources),
        "sources_with_excerpt": len(sources_with_excerpt),
        "coverage_label": coverage_label,
        "conflict_markers": conflict_markers,
        "conflict_warning": bool(conflict_markers),
        "needs_more_sources": len(sources_with_excerpt) < 2 or bool(conflict_markers),
    }


def _conflict_markers(sources: list[ResearchSource]) -> list[dict[str, str]]:
    marker_pairs = (
        ("supports", "contradicts"),
        ("safe", "dangerous"),
        ("increase", "decrease"),
        ("higher", "lower"),
        ("yes", "no"),
        ("true", "false"),
        ("recommended", "not recommended"),
        ("works", "does not work"),
    )
    texts = [f"{source.title} {source.snippet} {source.excerpt}".lower() for source in sources]
    markers: list[dict[str, str]] = []
    for left, right in marker_pairs:
        left_sources = [str(index + 1) for index, text in enumerate(texts) if left in text]
        right_sources = [str(index + 1) for index, text in enumerate(texts) if right in text]
        if left_sources and right_sources:
            markers.append(
                {
                    "left": left,
                    "right": right,
                    "left_sources": ",".join(left_sources),
                    "right_sources": ",".join(right_sources),
                }
            )
    return markers
