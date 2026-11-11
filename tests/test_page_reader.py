from __future__ import annotations

from jarvis.browser import PageReader


def test_page_reader_extracts_title_and_visible_text():
    html = b"""
    <html>
      <head><title>Demo Page</title><style>.x{}</style></head>
      <body><h1>Hello</h1><script>alert(1)</script><p>Visible text.</p></body>
    </html>
    """
    reader = PageReader(fetch_bytes=lambda _url, _timeout, _max_bytes: html)

    result = reader.extract("https://example.com")

    assert result.ok
    assert "Demo Page" in result.message
    assert "Hello Visible text." in result.message
    assert "alert" not in result.message
    assert result.metadata["untrusted_web_content"] is True
    assert result.metadata["content_trust"] == "untrusted"
    assert result.metadata["prompt_injection_guard"] is True


def test_page_reader_rejects_non_http_urls():
    result = PageReader(fetch_bytes=lambda *_args: b"").extract("file:///C:/secret.txt")

    assert not result.ok
    assert "http or https" in result.message


def test_page_reader_rejects_localhost():
    result = PageReader(fetch_bytes=lambda *_args: b"").extract("http://localhost:8000")

    assert not result.ok
    assert "localhost" in result.message.lower()


def test_page_reader_rejects_private_ip():
    result = PageReader(fetch_bytes=lambda *_args: b"").extract("http://192.168.1.1")

    assert not result.ok
    assert "private-network" in result.message


def test_page_reader_reports_empty_extraction():
    result = PageReader(fetch_bytes=lambda *_args: b"<html><script>only()</script></html>").extract("https://example.com")

    assert not result.ok
    assert "readable text" in result.message
