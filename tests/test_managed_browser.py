from __future__ import annotations

import os
import socket
from pathlib import Path
from unittest.mock import Mock

import pytest

from jarvis.browser.managed import ManagedBrowser


@pytest.fixture
def browser(tmp_path):
    instance = ManagedBrowser(workspace=tmp_path)
    yield instance
    instance.close()


@pytest.mark.parametrize("url", ["file:///C:/secret.txt", "javascript:alert(1)",
    "http://localhost", "http://127.0.0.1", "http://192.168.1.1", "http://[::1]",
    "https://user:password@example.com", "https://example.com/\nfoo"])
def test_rejects_nonpublic_or_credential_urls_before_launch(browser, url):
    result = browser.call("navigate", url=url)
    assert not result.ok
    assert browser._context is None


def test_rejects_dns_private_address(browser, monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("192.168.1.9", 443))])
    with pytest.raises(ValueError, match="Private-network"):
        browser._validate_url("https://private.example")
    route = Mock()
    route.request.url = "https://private.example"
    browser._route_request(route)
    route.abort.assert_called_once()
    route.continue_.assert_not_called()


def test_fixture_allowlist_cannot_be_used_by_visible_browser(tmp_path):
    with pytest.raises(ValueError):
        ManagedBrowser(workspace=tmp_path, test_origin="http://127.0.0.1:8080")


def test_dry_run_never_starts_browser_or_writes_profile(tmp_path):
    browser = ManagedBrowser(dry_run=True, workspace=tmp_path)
    try:
        result = browser.call("navigate", url="https://example.com")
        assert result.ok and result.metadata["dry_run"]
        assert browser._pool is None
        assert not list(tmp_path.iterdir())
    finally:
        browser.close()


def test_actions_cannot_start_browser_without_navigation(browser):
    result = browser.call("click", ref="invented", expected_label="Buy")
    assert not result.ok
    assert browser._playwright is None


@pytest.fixture
def live_browser(tmp_path):
    if os.getenv("JARVIS_BROWSER_INTEGRATION") != "1":
        pytest.skip("Set JARVIS_BROWSER_INTEGRATION=1 for real local Chromium tests")
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    from urllib.parse import parse_qs, urlsplit
    import html

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = parse_qs(urlsplit(self.path).query).get("q", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(("<!doctype html><title>Jarvis browser fixture</title>"
                "<h1>Local test shop</h1><form action='/results'>"
                "<label>Search<input name='q' type='search'></label>"
                "<button>Find products</button></form>"
                "<label>Sort<select><option>Price</option><option>Rating</option></select></label>"
                "<a href='/next'>Next page</a>"
                "<button id='changing'>Original</button>"
                "<input type='password' value='must-not-read'>"
                f"<p>Query: {html.escape(query)}</p>").encode("utf-8"))

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path.cwd() / "data/browser-binaries"))
    browser = ManagedBrowser(workspace=tmp_path, headless=True, test_origin=origin)
    try:
        yield browser, origin
    finally:
        browser.close()
        server.shutdown()
        server.server_close()
        thread.join(2)


def control(result, label):
    assert result.ok, result.message
    element = next(item for item in result.metadata["controls"] if item["label"] == label)
    return {"ref": element["ref"], "expected_label": label}


def test_live_search_uses_fresh_refs_and_observes_result(live_browser):
    browser, origin = live_browser
    first = browser.call("navigate", url=origin)
    old_button = control(first, "Find products")
    assert not any(item["type"] == "password" for item in first.metadata["controls"])
    assert "must-not-read" not in first.message
    filled = browser.call("fill", **control(first, "Search"), text="gaming mouse")
    assert not browser.call("click", **old_button).ok
    fresh = browser.call("inspect")
    searched = browser.call("click", **control(fresh, "Find products"))
    assert searched.ok, searched.message
    assert "Query: gaming mouse" in searched.message
    assert searched.metadata["untrusted_web_content"]
    assert searched.metadata["isolated_profile"]
    selected = browser.call("select", **control(searched, "Sort"), option_label="Rating")
    assert selected.ok, selected.message


def test_live_tabs_and_changed_control_are_safe(live_browser):
    browser, origin = live_browser
    first = browser.call("navigate", url=origin)
    stale = control(first, "Original")
    browser._pool.submit(lambda: browser._active.locator("#changing").evaluate(
        "el => el.textContent = 'Changed'")).result()
    assert not browser.call("click", **stale).ok
    first_id = first.metadata["tabs"][0]["tab_id"]
    second = browser.call("navigate", url=origin + "/next", new_tab=True)
    second_id = next(t["tab_id"] for t in second.metadata["tabs"] if t["active"])
    assert len(browser.call("tabs").metadata["tabs"]) == 2
    assert browser.call("switch", tab_id=first_id).ok
    assert browser.call("close_tab", tab_id=second_id).ok
    assert browser.call("close_tab", tab_id=first_id).ok
    assert browser.call("navigate", url=origin).ok


def test_live_context_reopens_after_user_closes_it(live_browser):
    browser, origin = live_browser
    assert browser.call("navigate", url=origin).ok
    browser._pool.submit(lambda: browser._context.close()).result()
    reopened = browser.call("navigate", url=origin)
    assert reopened.ok, reopened.message


def test_live_browser_accepts_calls_from_different_threads(live_browser):
    from concurrent.futures import ThreadPoolExecutor

    browser, origin = live_browser
    assert browser.call("navigate", url=origin).ok
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(browser.call, "inspect"), pool.submit(browser.call, "tabs")]
        assert all(future.result().ok for future in results)
