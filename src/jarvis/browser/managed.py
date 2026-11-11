from __future__ import annotations

import atexit
import ipaddress
import os
import shutil
import socket
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

from ..models import CommandResult
from ..privacy import redact_sensitive_data, redact_sensitive_text
from .page_reader import _normalize_url, _validate_public_http_url


# This code is fixed by the application. Neither the model nor a webpage can
# supply JavaScript, selectors, executable paths, or a personal browser profile.
_DESCRIBE_ELEMENT = """el => {
const labelText = label => {
    const copy = label.cloneNode(true);
    copy.querySelectorAll('input, textarea, select, button').forEach(x => x.remove());
    return copy.textContent;
};
return ({
    in_view: el.getBoundingClientRect().bottom > 0 && el.getBoundingClientRect().top < innerHeight,
    tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '',
    role: el.getAttribute('role') || '',
    label: (el.getAttribute('aria-label') ||
        (el.labels && Array.from(el.labels).map(labelText).join(' ')) ||
        el.innerText || el.getAttribute('placeholder') ||
        el.getAttribute('title') || el.getAttribute('name') || '').trim().slice(0, 180),
    href: el.tagName === 'A' ? el.href : '',
    disabled: !!el.disabled,
    autocomplete: el.getAttribute('autocomplete') || '',
    options: el.tagName === 'SELECT' ? Array.from(el.options).slice(0, 40)
        .map(x => ({label: x.label, value: x.value})) : []
}); }"""


class ManagedBrowser:
    """Lazy, isolated browser session. All Playwright objects stay on one thread."""

    def __init__(self, *, executable_path: str | None = None, dry_run: bool = False,
                 workspace: Path | None = None, headless: bool = False,
                 test_origin: str = "") -> None:
        self.workspace = (workspace or Path.cwd()).resolve()
        self.executable_path = executable_path
        self.dry_run = dry_run
        self.headless = headless
        # Only headless integration fixtures may explicitly use a loopback server.
        if test_origin and (not headless or urlsplit(test_origin).hostname != "127.0.0.1"):
            raise ValueError("Test origin must be an explicit headless loopback fixture.")
        self._test_origin = test_origin
        self._pool: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()
        self._closed = False
        self._playwright = None
        self._context = None
        self._active = None
        self._tabs: dict[str, object] = {}
        self._refs: dict[str, tuple] = {}
        self._backend = ""
        atexit.register(self.close)

    def status(self) -> CommandResult:
        try:
            import playwright.sync_api  # noqa: F401
            available = True
        except ImportError:
            available = False
        return CommandResult(available,
            "Playwright managed browser ready to start in an isolated Jarvis profile."
            if available else 'Install browser support: python -m pip install -e ".[browser]"',
            metadata={"playwright_available": available, "running": self._context is not None,
                      "backend": self._backend, "isolated_profile": True})

    def call(self, operation: str, **arguments) -> CommandResult:
        if operation not in {"navigate", "inspect", "tabs", "switch", "close_tab",
                             "click", "fill", "select", "scroll"}:
            return CommandResult(False, "Unsupported browser operation.")
        if self.dry_run:
            return CommandResult(True, f"Would run managed browser {operation}.",
                                 metadata={"dry_run": True, "operation": operation})
        with self._lock:
            if self._closed:
                return CommandResult(False, "Managed browser has been shut down.")
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="jarvis-browser")
            future = self._pool.submit(self._execute, operation, arguments)
        return future.result()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pool = self._pool
            future = pool.submit(self._dispose) if pool else None
        if future:
            try:
                future.result()
            finally:
                pool.shutdown(wait=True)
        atexit.unregister(self.close)

    def _dispose(self) -> None:
        self._invalidate_refs()
        try:
            if self._context:
                self._context.close()
        finally:
            self._context = self._active = None
            self._tabs.clear()
            if self._playwright:
                self._playwright.stop()
                self._playwright = None

    def _validate_url(self, url: str) -> None:
        parsed = urlsplit(url)
        if parsed.username or parsed.password or any(ord(c) < 32 for c in url):
            raise ValueError("Credentials and control characters are not allowed in browser URLs.")
        if self._test_origin and f"{parsed.scheme}://{parsed.netloc}" == self._test_origin:
            return
        error = _validate_public_http_url(url)
        if error:
            raise ValueError(error)
        # Check redirects and subrequests too, not just the initial user URL.
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Private-network browser access is blocked.")

    def _route_request(self, route) -> None:
        try:
            self._validate_url(route.request.url)
        except (ValueError, OSError):
            route.abort("blockedbyclient")
        else:
            route.continue_()

    def _ensure_context(self) -> None:
        if self._context is not None:
            return
        from playwright.sync_api import sync_playwright

        if self._playwright:
            self._playwright.stop()
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(self.workspace / "data/browser-binaries"))
        self._playwright = sync_playwright().start()
        executable = self.executable_path
        if executable and not Path(executable).is_file():
            executable = shutil.which(executable)
        try:
            options = dict(headless=self.headless, accept_downloads=False,
                           service_workers="block", chromium_sandbox=True, timeout=20000,
                           viewport={"width": 1280, "height": 800})
            # Keep Opera and Chromium profiles separate, including on fallback.
            profile = self.workspace / "data/browser-profile" / ("preferred" if executable else "chromium")
            self._context = self._playwright.chromium.launch_persistent_context(
                str(profile), executable_path=executable, **options)
            self._backend = Path(executable).name if executable else "Chromium"
            self._context.set_default_timeout(6000)
            self._context.set_default_navigation_timeout(15000)
            self._context.route("**/*", self._route_request)
            self._context.on("page", self._register_page)
            self._context.on("close", self._context_closed)
            # Opera's startup tab can be taken over by GX Corner after launch.
            # Create our own tab. Do not control or close its internal startup tabs.
            self._context.new_page()
        except Exception:
            self._dispose()
            raise

    def _context_closed(self, *_args) -> None:
        self._context = self._active = None
        self._tabs.clear()
        self._refs.clear()

    def _register_page(self, page) -> None:
        if page in self._tabs.values():
            return
        self._tabs[uuid.uuid4().hex[:8]] = page
        page.on("download", lambda download: download.cancel())
        page.on("dialog", lambda dialog: dialog.dismiss())
        page.on("framenavigated", lambda frame: self._invalidate_refs()
                if frame == page.main_frame else None)
        if self._active is None:
            self._active = page

    def _invalidate_refs(self) -> None:
        refs, self._refs = list(self._refs.values()), {}
        for handle, *_ in refs:
            try:
                handle.dispose()
            except Exception:
                pass

    def _page(self):
        if self._active is None or self._active.is_closed():
            self._active = next((p for p in self._tabs.values() if not p.is_closed()), None)
        if self._active is None:
            raise ValueError("No managed tab is open. Use browser_navigate first.")
        return self._active

    def _tab_list(self) -> list[dict]:
        self._tabs = {key: page for key, page in self._tabs.items() if not page.is_closed()}
        return [{"tab_id": key, "url": page.url, "title": page.title(), "active": page == self._active}
                for key, page in self._tabs.items()]

    def _snapshot(self) -> CommandResult:
        page = self._page()
        self._invalidate_refs()
        if page.url != "about:blank":
            self._validate_url(page.url)
        controls = []
        candidates = page.query_selector_all("a[href], button, input, textarea, select, [role=button]")
        for handle in candidates[:300]:
            retained = False
            try:
                if len(controls) < 80 and handle.is_visible():
                    descriptor = handle.evaluate(_DESCRIBE_ELEMENT)
                    if descriptor["in_view"] and descriptor["type"] not in {"hidden", "password", "file"}:
                        ref = uuid.uuid4().hex[:12]
                        self._refs[ref] = (handle, descriptor, page, page.url)
                        controls.append({"ref": ref, **descriptor})
                        retained = True
            finally:
                if not retained:
                    handle.dispose()
        for handle in candidates[300:]:
            handle.dispose()
        excerpt = page.locator("body").inner_text(timeout=6000)[:12000]
        metadata = redact_sensitive_data({"url": page.url, "title": page.title(),
            "excerpt": excerpt, "controls": controls, "tabs": self._tab_list(),
            "backend": self._backend, "untrusted_web_content": True,
            "prompt_injection_guard": True, "isolated_profile": True})
        return CommandResult(True, f"Read managed tab: {metadata['title']}\n{metadata['url']}\n{metadata['excerpt']}",
                             metadata=metadata)

    def _resolve(self, ref: str, expected_label: str):
        item = self._refs.get(ref)
        if not item:
            raise ValueError("Stale or unknown element reference. Inspect the page again.")
        handle, descriptor, page, url = item
        if page != self._page() or page.url != url or not handle.is_visible():
            raise ValueError("Page changed. Inspect it again before acting.")
        if handle.evaluate(_DESCRIBE_ELEMENT) != descriptor or descriptor["label"] != expected_label:
            raise ValueError("Element changed or its label does not match. Inspect it again.")
        if descriptor["disabled"]:
            raise ValueError("That control is disabled.")
        if descriptor["href"]:
            self._validate_url(descriptor["href"])
        if descriptor["type"] in {"password", "file"} or any(
            word in descriptor["autocomplete"] for word in ("password", "cc-", "one-time-code")
        ):
            raise ValueError("Credentials, payments and file uploads require manual interaction.")
        return handle

    def _execute(self, operation: str, arguments: dict) -> CommandResult:
        try:
            if operation == "navigate":
                arguments["url"] = _normalize_url(arguments["url"])
                self._validate_url(arguments["url"])
            if operation != "navigate" and self._context is None:
                return CommandResult(False, "No managed browser is running. Use browser_navigate first.")
            self._ensure_context()
            if operation == "navigate":
                page = self._context.new_page() if arguments.get("new_tab", False) or not any(
                    not p.is_closed() for p in self._tabs.values()) else self._page()
                self._active = page
                self._invalidate_refs()
                response = page.goto(arguments["url"], wait_until="domcontentloaded")
                if response and response.status >= 400:
                    return CommandResult(False, f"Webpage returned HTTP {response.status}.",
                                         metadata={"url": page.url, "http_status": response.status})
            elif operation == "tabs":
                tabs = redact_sensitive_data(self._tab_list())
                return CommandResult(True, "\n".join(f"{t['tab_id']}: {t['title']} {t['url']}" for t in tabs),
                                     metadata={"tabs": tabs, "untrusted_web_content": True})
            elif operation in {"switch", "close_tab"}:
                page = self._tabs.get(arguments["tab_id"])
                if page is None or page.is_closed():
                    raise ValueError("Unknown tab ID. List the tabs again.")
                self._invalidate_refs()
                if operation == "close_tab":
                    page.close()
                    return CommandResult(True, "Closed managed tab.", metadata={"tabs": self._tab_list()})
                self._active = page
                page.bring_to_front()
            elif operation in {"click", "fill", "select"}:
                handle = self._resolve(arguments["ref"], arguments["expected_label"])
                try:
                    if operation == "fill":
                        value = arguments["text"]
                        if not isinstance(value, str) or len(value) > 2000:
                            raise ValueError("Browser input must be text of at most 2000 characters.")
                        if redact_sensitive_text(value).text != value:
                            raise ValueError("Do not send API keys or secrets through browser tools.")
                        handle.fill(value)
                    elif operation == "select":
                        handle.select_option(label=arguments["option_label"])
                    else:
                        handle.click()
                finally:
                    self._invalidate_refs()
            elif operation == "scroll":
                direction = arguments.get("direction", "down")
                if direction not in {"up", "down"}:
                    raise ValueError("Scroll direction must be up or down.")
                self._page().evaluate("dy => window.scrollBy(0, dy)", 600 if direction == "down" else -600)
            return self._snapshot()
        except ImportError:
            return CommandResult(False, 'Install browser support: python -m pip install -e ".[browser]"')
        except Exception as exc:
            self._invalidate_refs()
            detail = redact_sensitive_text(str(exc)).text[:1200]
            return CommandResult(False, f"Managed browser {operation} failed: {detail}",
                metadata={"operation": operation, "outcome_uncertain": operation in {"click", "fill", "select"}})
