from __future__ import annotations

import os
import re
import stat
import time
from pathlib import Path

from .privacy import contains_sensitive_text


TEXT_EXTENSIONS = frozenset({"txt", "md", "csv"})
_PRIVATE_PARTS = frozenset({"appdata", "windows", "program files", "program files (x86)",
                            "programdata", "$recycle.bin", "system volume information",
                            "node_modules", "venv", "__pycache__"})
_PRIVATE_NAME = re.compile(r"(?:^|[._\s-])(secrets?|passwords?|credentials?|tokens?|keys?|config|settings)(?:$|[._\s-])", re.I)


def content_path_allowed(path: Path) -> bool:
    return not any(part.startswith(".") or part.casefold() in _PRIVATE_PARTS or _PRIVATE_NAME.search(part)
                   for part in path.parts)


class TextContentSearch:
    """Bounded literal matching; document text never leaves this reader."""

    MAX_FILE_BYTES = 1024 * 1024
    MAX_TOTAL_BYTES = 16 * 1024 * 1024

    def __init__(self, phrase: str, *, deadline: float, cancelled) -> None:
        self.phrase = phrase.casefold()
        self.deadline = deadline
        self.cancel_requested = cancelled
        self.bytes_read = 0
        self.files_read = 0
        self.limited = False
        self.cancelled = False

    def stopped(self) -> bool:
        self.cancelled = self.cancelled or self.cancel_requested()
        self.limited = self.limited or time.monotonic() >= self.deadline
        return self.cancelled or self.limited

    def matches(self, path: Path, expected) -> bool | None:
        if not content_path_allowed(path) or path.suffix.casefold().lstrip(".") not in TEXT_EXTENSIONS:
            return None
        if expected.st_size > self.MAX_FILE_BYTES:
            return None
        if expected.st_size + 1 > self.MAX_TOTAL_BYTES - self.bytes_read:
            self.limited = True
            return None
        if self.stopped():
            return None
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if (not stat.S_ISREG(before.st_mode)
                    or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                    != (expected.st_dev, expected.st_ino, expected.st_size, expected.st_mtime_ns)):
                return None
            self.files_read += 1
            chunks = []
            remaining = expected.st_size + 1
            while remaining:
                if self.stopped():
                    return None
                chunk = stream.read(min(65536, remaining))
                self.bytes_read += len(chunk)
                remaining -= len(chunk)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(stream.fileno())
        if self.stopped():
            return None
        data = b"".join(chunks)
        if len(data) != expected.st_size or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return None
        try:
            text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        except UnicodeError:
            return None
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text) or contains_sensitive_text(text):
            return None
        return self.phrase in text.casefold()
