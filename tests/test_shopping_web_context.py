from __future__ import annotations

from jarvis.ai_client import JarvisAI
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.web_context import WebCandidate, WebContext
from jarvis.windows_actions import WindowsActions


def make_router() -> CommandRouter:
    return CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=True),
        ai=JarvisAI(dry_run=True),
    )


def test_opens_product_search_in_named_store():
    result = make_router().handle("jarvis отвори гейминг мишки в пласико")
    assert result.ok
    assert "plasico.bg" in result.message
    assert "гейминг" in result.message or "%D0%B3" in result.message


def test_discount_search_saves_candidates():
    result = make_router().handle("jarvis в кои магазини има намаления за гейминг мишки")
    assert result.ok
    assert "Plasico" in result.message
    assert "отвори първия" in result.message


def test_open_saved_candidate(tmp_path):
    context = WebContext(path=tmp_path / "web_context.json")
    context.save_candidates([WebCandidate("Example", "https://example.com")], query="example")
    assert context.pick(1) == WebCandidate("Example", "https://example.com")
    assert context.pick(2) is None


def test_find_saved_candidate_by_title_or_url(tmp_path):
    context = WebContext(path=tmp_path / "web_context.json")
    context.save_candidates(
        [
            WebCandidate("Plasico gaming mice", "https://plasico.bg/search?q=mouse"),
            WebCandidate("Other shop", "https://example.com/mouse"),
        ],
        query="gaming mouse",
    )

    result = context.find("plasico")

    assert result is not None
    ordinal, candidate = result
    assert ordinal == 1
    assert candidate.url == "https://plasico.bg/search?q=mouse"


def test_records_opened_and_read_pages_in_session(tmp_path):
    context = WebContext(path=tmp_path / "web_context.json")
    candidate = WebCandidate("Plasico gaming mice", "https://plasico.bg/search?q=mouse")
    context.save_candidates([candidate], query="gaming mouse")

    context.record_opened(candidate, ordinal=1, match_query="plasico")
    context.record_read(url=candidate.url, title=candidate.title, excerpt="Mouse details", text_length=12, ordinal=1)
    summary = context.session_summary()

    assert summary["query"] == "gaming mouse"
    assert summary["opened"][0]["match_query"] == "plasico"
    assert summary["read_pages"][0]["excerpt"] == "Mouse details"
