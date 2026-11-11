from __future__ import annotations

import html
import ipaddress
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ..models import CommandResult
from ..prompt_safety import prompt_guard_metadata


FetchBytes = Callable[[str, float, int], bytes]


@dataclass(frozen=True)
class PageExtract:
    url: str
    title: str
    text: str

    @property
    def excerpt(self) -> str:
        if len(self.text) <= 1200:
            return self.text
        return f"{self.text[:1197]}..."


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = data.strip()
        if not cleaned:
            return
        if self._in_title:
            self.title_parts.append(cleaned)
        else:
            self.text_parts.append(cleaned)

    def extract(self, url: str) -> PageExtract:
        title = _normalize_text(" ".join(self.title_parts))
        text = _normalize_text(" ".join(self.text_parts))
        return PageExtract(url=url, title=title, text=text)


class PageReader:
    def __init__(
        self,
        *,
        timeout: float = 10.0,
        max_bytes: int = 750_000,
        fetch_bytes: FetchBytes | None = None,
    ) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self._fetch_bytes = fetch_bytes or _fetch_url_bytes

    def extract(self, url: str) -> CommandResult:
        normalized = _normalize_url(url)
        error = _validate_public_http_url(normalized)
        if error:
            return CommandResult(False, error)

        try:
            payload = self._fetch_bytes(normalized, self.timeout, self.max_bytes)
        except Exception as exc:
            return CommandResult(False, f"Could not read webpage: {exc}")

        parser = _ReadableHtmlParser()
        parser.feed(payload.decode("utf-8", errors="replace"))
        page = parser.extract(normalized)
        if not page.text:
            return CommandResult(False, "I could not extract readable text from that webpage.")

        title = f" ({page.title})" if page.title else ""
        return CommandResult(
            True,
            f"Read webpage{title}:\n{page.excerpt}",
            metadata={
                "url": page.url,
                "title": page.title,
                "text_length": len(page.text),
                "excerpt": page.excerpt,
                "untrusted_web_content": True,
                **prompt_guard_metadata("page_reader"),
            },
        )


def _fetch_url_bytes(url: str, timeout: float, max_bytes: int) -> bytes:
    request = Request(url, headers={"User-Agent": "JarvisLocalAssistant/0.1"})
    with urlopen(request, timeout=timeout) as response:
        return response.read(max_bytes + 1)[:max_bytes]


def _normalize_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return url
    if not url.startswith(("http://", "https://")):
        return f"https://{url}"
    return url


def _validate_public_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return "I can only read http or https webpages."
    hostname = (parsed.hostname or "").strip().lower()
    if not hostname:
        return "That webpage URL does not have a hostname."
    if hostname in {"localhost"} or hostname.endswith(".localhost"):
        return "I will not read localhost webpages without a separate allowlist."
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        return ""
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
        return "I will not read private-network webpages without a separate allowlist."
    return ""


def _normalize_text(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()
