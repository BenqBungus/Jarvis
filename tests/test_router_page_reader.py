from __future__ import annotations

from jarvis.ai_client import JarvisAI
from jarvis.browser import PageReader
from jarvis.models import CommandResult
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.tool_registry import build_core_tool_registry
from jarvis.web_context import WebCandidate, WebContext
from jarvis.windows_actions import WindowsActions


def make_router(tmp_path) -> CommandRouter:
    router = CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=True),
        ai=JarvisAI(dry_run=True),
    )
    router.web_context = WebContext(path=tmp_path / "web_context.json")
    router.page_reader = PageReader(fetch_bytes=lambda *_args: b"<title>Demo</title><h1>Hello</h1><p>Readable page.</p>")
    router.tools = build_core_tool_registry(
        router.actions,
        router.ai,
        memory=router.long_term_memory,
        audit=router.audit_reader,
        web_context=router.web_context,
        page_reader=router.page_reader,
    )
    return router


def test_router_reads_direct_webpage_url(tmp_path):
    router = make_router(tmp_path)

    result = router.handle("jarvis прочети страницата example.com")

    assert result.ok
    assert result.intent == "browser.extract_webpage"
    assert "Readable page" in result.message
    assert result.metadata["untrusted_web_content"] is True


def test_router_preserves_url_scheme_for_page_reading(tmp_path):
    router = make_router(tmp_path)

    result = router.handle("jarvis прочети страницата http://localhost:8000")

    assert not result.ok
    assert result.intent == "browser.extract_webpage"
    assert "localhost" in result.message.lower()


def test_router_reads_saved_candidate_by_ordinal(tmp_path):
    router = make_router(tmp_path)
    router.web_context.save_candidates([WebCandidate("Example", "https://example.com")], query="demo")

    result = router.handle("jarvis прочети първия")

    assert result.ok
    assert result.intent == "browser.extract_saved_candidate"
    assert "Readable page" in result.message


def test_router_reads_saved_candidate_by_matching_text(tmp_path):
    router = make_router(tmp_path)
    router.web_context.save_candidates(
        [
            WebCandidate("Example", "https://example.com"),
            WebCandidate("Plasico result", "https://plasico.bg/search"),
        ],
        query="demo",
    )

    result = router.handle("jarvis прочети резултата за plasico")

    assert result.ok
    assert result.intent == "browser.extract_matching_saved_candidate"
    assert "Readable page" in result.message
    assert result.metadata["ordinal"] == 2


def test_router_browser_session_summary_includes_read_pages(tmp_path):
    router = make_router(tmp_path)
    router.web_context.save_candidates([WebCandidate("Example", "https://example.com")], query="demo")
    router.handle("jarvis прочети първия")

    result = router.handle("jarvis какво прочете")

    assert result.ok
    assert result.intent == "browser.session_summary"
    assert "Read:" in result.message
    assert result.metadata["browser_session"]["read_pages"][0]["url"] == "https://example.com"


def test_router_compares_read_pages_from_current_browser_session(tmp_path):
    router = make_router(tmp_path)
    router.web_context.save_candidates(
        [
            WebCandidate("First page", "https://example.com/one"),
            WebCandidate("Second page", "https://example.com/two"),
        ],
        query="demo",
    )
    router.handle("jarvis прочети първия")
    router.handle("jarvis прочети втория")

    result = router.handle("jarvis сравни тези резултати")

    assert result.ok
    assert result.intent == "browser.session_compare"
    assert "Comparison from the current browser session" in result.message
    assert len(result.metadata["compared_pages"]) == 2


def test_router_uses_ai_for_browser_session_compare_when_available(tmp_path):
    class FakeCompareAI(JarvisAI):
        dry_run = False

        def compare_browser_session_pages(self, pages, question="Compare these browser session pages."):
            return CommandResult(True, f"ai compared {len(pages)} pages", metadata={"ai_trace": {"operation": "browser_session_compare"}})

    router = make_router(tmp_path)
    router.ai = FakeCompareAI(dry_run=False)
    router.web_context.save_candidates(
        [
            WebCandidate("First page", "https://example.com/one"),
            WebCandidate("Second page", "https://example.com/two"),
        ],
        query="demo",
    )
    router.handle("jarvis прочети първия")
    router.handle("jarvis прочети втория")

    result = router.handle("jarvis сравни тези резултати")

    assert result.ok
    assert result.message == "ai compared 2 pages"
    assert result.metadata["browser_session_ai_compare"] is True
    assert result.metadata["ai_trace"]["operation"] == "browser_session_compare"


def test_router_answers_question_from_current_browser_session_fallback(tmp_path):
    router = make_router(tmp_path)
    router.web_context.save_candidates([WebCandidate("Battery page", "https://example.com/battery")], query="battery")
    router.handle("jarvis прочети първия")

    result = router.handle("jarvis какво казват страниците за battery")

    assert result.ok
    assert result.intent == "browser.session_answer"
    assert "Answer from current browser session" in result.message
    assert result.metadata["browser_session_ai_answer"] is False
    assert result.metadata["browser_session_question"] == "battery"


def test_router_uses_ai_for_browser_session_question_when_available(tmp_path):
    class FakeAnswerAI(JarvisAI):
        dry_run = False

        def answer_browser_session_question(self, pages, question):
            return CommandResult(True, f"ai answered {question} from {len(pages)} pages", metadata={"ai_trace": {"operation": "browser_session_answer"}})

    router = make_router(tmp_path)
    router.ai = FakeAnswerAI(dry_run=False)
    router.web_context.save_candidates([WebCandidate("Battery page", "https://example.com/battery")], query="battery")
    router.handle("jarvis прочети първия")

    result = router.handle("jarvis отговори от прочетеното батерия")

    assert result.ok
    assert result.message == "ai answered батерия from 1 pages"
    assert result.metadata["browser_session_ai_answer"] is True
    assert result.metadata["ai_trace"]["operation"] == "browser_session_answer"


def test_router_read_saved_candidate_reports_missing_context(tmp_path):
    router = make_router(tmp_path)

    result = router.handle("jarvis прочети първия")

    assert not result.ok
    assert "saved web result" in result.message
