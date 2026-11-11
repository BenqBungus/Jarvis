from __future__ import annotations

from jarvis.ai_client import JarvisAI
from jarvis.browser import DuckDuckGoSearchProvider, PageReader, SearchResult, WebResearcher
from jarvis.models import CommandResult
from jarvis.browser.research import analyze_source_coverage, score_research_source, summarize_source_quality, ResearchSource
from jarvis.web_context import WebContext


class FakeSearchProvider:
    def search(self, query: str, max_results: int = 6) -> list[SearchResult]:
        return [
            SearchResult("First source", "https://example.com/one"),
            SearchResult("Second source", "https://example.com/two"),
        ][:max_results]


class ConflictSearchProvider:
    def search(self, query: str, max_results: int = 6) -> list[SearchResult]:
        return [
            SearchResult("Support source", "https://example.com/support"),
            SearchResult("Contradict source", "https://example.com/contradict"),
        ][:max_results]


class ConflictPageReader:
    def extract(self, url: str) -> CommandResult:
        if "support" in url:
            return CommandResult(True, "ok", metadata={"excerpt": "The evidence supports this and says yes."})
        return CommandResult(True, "ok", metadata={"excerpt": "The evidence contradicts this and says no."})


def test_duckduckgo_provider_extracts_result_links():
    html = b"""
    <html>
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fitem">
        Example Result
      </a>
    </html>
    """
    provider = DuckDuckGoSearchProvider(fetch_bytes=lambda *_args: html)

    results = provider.search("demo")

    assert results == [SearchResult("Example Result", "https://example.com/item")]


def test_web_researcher_reads_sources_and_saves_candidates(tmp_path):
    context = WebContext(path=tmp_path / "web_context.json")
    page_reader = PageReader(fetch_bytes=lambda *_args: b"<title>Demo</title><p>Useful page evidence.</p>")
    researcher = WebResearcher(
        search_provider=FakeSearchProvider(),
        page_reader=page_reader,
        web_context=context,
        ai=JarvisAI(dry_run=True),
    )

    result = researcher.research("gaming mice", max_sources=2)

    assert result.ok
    assert "Would research" in result.message
    assert "Sources:" in result.message
    assert len(result.metadata["sources"]) == 2
    assert result.metadata["sources"][0]["excerpt"] == "Useful page evidence."
    assert result.metadata["sources"][0]["quality_label"] in {"low", "medium", "high"}
    assert result.metadata["sources"][0]["quality_score"] > 0
    assert result.metadata["source_quality"]["count"] == 2
    assert result.metadata["source_coverage"]["coverage_label"] == "limited"
    assert result.metadata["content_trust"] == "untrusted"
    assert result.metadata["prompt_injection_guard"] is True
    assert context.pick(1) is not None


def test_score_research_source_marks_substantial_https_source_higher_than_empty_source():
    strong = score_research_source(
        "Detailed source",
        "https://example.org/report",
        snippet="Research snippet.",
        excerpt="Evidence. " * 120,
    )
    weak = score_research_source("Sponsored coupon", "http://ads.example/coupon", excerpt="")

    assert strong["score"] > weak["score"]
    assert strong["label"] == "high"
    assert weak["label"] == "low"
    assert "no_extracted_text" in weak["reasons"]


def test_summarize_source_quality_counts_labels():
    summary = summarize_source_quality(
        [
            ResearchSource("A", "https://a.example", quality_score=80, quality_label="high"),
            ResearchSource("B", "https://b.example", quality_score=40, quality_label="low"),
        ]
    )

    assert summary["average_score"] == 60.0
    assert summary["labels"] == {"high": 1, "low": 1}
    assert summary["low_quality_count"] == 1


def test_analyze_source_coverage_detects_obvious_conflict_markers():
    coverage = analyze_source_coverage(
        [
            ResearchSource("A", "https://a.example", excerpt="This supports the claim and says yes."),
            ResearchSource("B", "https://b.example", excerpt="This contradicts the claim and says no."),
        ]
    )

    assert coverage["coverage_label"] == "limited"
    assert coverage["conflict_warning"] is True
    assert coverage["needs_more_sources"] is True
    assert {"left": "supports", "right": "contradicts", "left_sources": "1", "right_sources": "2"} in coverage["conflict_markers"]


def test_web_researcher_includes_source_coverage_conflict_metadata(tmp_path):
    context = WebContext(path=tmp_path / "web_context.json")
    researcher = WebResearcher(
        search_provider=ConflictSearchProvider(),
        page_reader=ConflictPageReader(),
        web_context=context,
        ai=JarvisAI(dry_run=True),
    )

    result = researcher.research("demo", max_sources=2)

    assert result.ok
    assert result.metadata["source_coverage"]["conflict_warning"] is True
    assert result.metadata["source_coverage"]["sources_with_excerpt"] == 2
