"""Explicitly selected, read-only project scope for screen-assisted diagnosis."""
from __future__ import annotations

import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

from .content_search import content_path_allowed
from .privacy import contains_sensitive_text


SOURCE_TYPES = frozenset("txt md json yaml yml xml csv log py js ts tsx jsx html css scss java cpp c h hpp cs go rs sql toml".split())
SKIP_DIRS = frozenset({"build", "dist", "dist-beta", "dist-desktop", "vendor", "coverage", "target"})


def _identity(info):
    return info.st_dev, info.st_ino


def _linked(info):
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


class ProjectWorkspace:
    """A grant for one directory, never a drive or the whole user profile."""

    def __init__(self, root):
        raw = Path(root)
        if not raw.is_absolute() or ".." in raw.parts:
            raise ValueError("Select an absolute project folder.")
        self.root = raw.absolute()
        if self.root == Path(self.root.anchor) or self.root == Path.home() or not content_path_allowed(self.root):
            raise ValueError("Select a specific project outside private or system folders.")
        self._validate_components(self.root)
        info = self.root.stat()
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Select a project folder, not a file.")
        self.identity = _identity(info)

    @staticmethod
    def _validate_components(path):
        for part in reversed((path, *path.parents)):
            if _linked(part.lstat()):
                raise ValueError("Linked folders and reparse points are not in the approved scope.")

    def path(self, relative=".", *, allow_missing_leaf=False):
        if not isinstance(relative, str) or len(relative) > 600 or "\x00" in relative or ":" in relative:
            raise ValueError("Use a relative project path.")
        child = Path(relative)
        if child.is_absolute() or child.anchor or ".." in child.parts:
            raise ValueError("Path is outside the selected project.")
        target = self.root / child
        if not target.is_relative_to(self.root) or not content_path_allowed(target):
            raise ValueError("Private or out-of-scope path is unavailable.")
        if any(part.casefold() in SKIP_DIRS for part in child.parts):
            raise ValueError("Generated build folders are excluded.")
        try:
            target.lstat()
        except FileNotFoundError:
            if not allow_missing_leaf:
                raise
            self._validate_components(target.parent)
        else:
            self._validate_components(target)
        if _identity(self.root.stat()) != self.identity:
            raise ValueError("Project folder changed. Select it again.")
        if not target.resolve().is_relative_to(self.root):
            raise ValueError("Path left the approved project.")
        return target


class ProjectReader:
    MAX_FILE_BYTES = 256 * 1024
    MAX_TOTAL_BYTES = 2 * 1024 * 1024
    MAX_ENTRIES = 1500

    def __init__(self, workspace, *, cancelled=lambda: False, on_action=lambda item: None, changes=None):
        self.workspace = workspace
        self.cancelled = cancelled
        self.on_action = on_action
        self.deadline = time.monotonic() + 180
        self.bytes_read = 0
        self.entries = 0
        self.limited = False
        self.audit = []
        self.snapshots = {}
        self.read_paths = set()
        self.listed_paths = set()
        self.changes = changes

    def check(self):
        if self.cancelled():
            raise ValueError("Project analysis cancelled.")
        if time.monotonic() > self.deadline:
            self.limited = True
            raise ValueError("Project analysis reached its time limit.")

    def _text(self, path):
        self.check()
        target = self.workspace.path(path)
        info = target.stat()
        if target.suffix.casefold().lstrip(".") not in SOURCE_TYPES or not stat.S_ISREG(info.st_mode):
            raise ValueError("Unsupported source file.")
        if info.st_nlink > 1 or info.st_size > self.MAX_FILE_BYTES:
            raise ValueError("Linked or oversized file excluded.")
        if self.bytes_read + info.st_size + 1 > self.MAX_TOTAL_BYTES:
            self.limited = True
            raise ValueError("Project read budget reached.")
        with target.open("rb") as stream:
            before = os.fstat(stream.fileno())
            if _identity(info) != _identity(before) or before.st_nlink > 1 or not stat.S_ISREG(before.st_mode):
                raise ValueError("File changed before reading.")
            data = stream.read(self.MAX_FILE_BYTES + 1)
            self.bytes_read += len(data)
            after = os.fstat(stream.fileno())
        stamp = lambda item: (_identity(item), item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if stamp(info) != stamp(before) or stamp(before) != stamp(after) or len(data) != info.st_size:
            raise ValueError("File changed during reading.")
        self.workspace.path(path)
        self.check()
        text = data.decode("utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig")
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text) or contains_sensitive_text(text):
            raise ValueError("Binary or recognized sensitive content excluded.")
        self.snapshots[target.relative_to(self.workspace.root).as_posix()] = data
        return text

    def _walk(self, directory=".", *, recursive=True):
        pending = [(directory, 0)]
        while pending:
            self.check()
            relative, depth = pending.pop()
            try:
                folder = self.workspace.path(relative)
                with os.scandir(folder) as entries:
                    for entry in entries:
                        self.check()
                        self.entries += 1
                        if self.entries > self.MAX_ENTRIES:
                            self.limited = True
                            return
                        path = Path(entry.path).relative_to(self.workspace.root).as_posix()
                        try:
                            target = self.workspace.path(path)
                            info = target.stat()
                            if info.st_nlink > 1 and stat.S_ISREG(info.st_mode):
                                continue
                            is_dir = stat.S_ISDIR(info.st_mode)
                            if not is_dir and not stat.S_ISREG(info.st_mode):
                                continue
                            if contains_sensitive_text(path):
                                continue
                            yield path, info, is_dir
                            if is_dir and recursive:
                                if depth < 12:
                                    pending.append((path, depth + 1))
                                else:
                                    self.limited = True
                        except (OSError, ValueError):
                            continue
            except OSError:
                continue

    def list_files(self, path="."):
        folder = self.workspace.path(path)
        if not folder.is_dir():
            raise ValueError("Choose an existing directory.")
        self.listed_paths.add(folder.relative_to(self.workspace.root).as_posix())
        rows = []
        for relative, info, is_dir in self._walk(path, recursive=False):
            rows.append({"path": relative, "kind": "directory" if is_dir else "file", "bytes": info.st_size})
            if len(rows) >= 150:
                self.limited = True
                break
        return {"entries": rows, "limited": self.limited}

    def read_file(self, path, start_line=1):
        if type(start_line) is not int or not 1 <= start_line <= 100000:
            raise ValueError("Invalid starting line.")
        lines = self._text(path).splitlines()
        self.read_paths.add(self.workspace.path(path).relative_to(self.workspace.root).as_posix())
        selected, length = [], 0
        for number, line in enumerate(lines[start_line - 1:start_line + 199], start_line):
            numbered = f"{number}: {line}"
            if length + len(numbered) > 16000:
                break
            selected.append(numbered)
            length += len(numbered) + 1
        return {"path": path, "text": "\n".join(selected), "total_lines": len(lines),
                "next_line": start_line + len(selected) if start_line + len(selected) <= len(lines) else None,
                "limited": not selected and start_line <= len(lines)}

    def search_files(self, query="", extension=None, content=None, min_bytes=None, max_bytes=None,
                     modified_after=None, modified_before=None):
        if not isinstance(query, str):
            raise ValueError("Use text for the filename query.")
        for value in (query, extension, content):
            if value is not None and (not isinstance(value, str) or len(value) > 300):
                raise ValueError("Use literal search text of at most 300 characters.")
        for size in (min_bytes, max_bytes):
            if size is not None and (type(size) is not int or size < 0):
                raise ValueError("Invalid size filter.")
        def timestamp(value):
            if value is None:
                return None
            if not isinstance(value, str) or len(value) > 40:
                raise ValueError("Use an ISO date or timestamp.")
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return date.replace(tzinfo=timezone.utc).timestamp() if date.tzinfo is None else date.timestamp()
        after, before = timestamp(modified_after), timestamp(modified_before)
        rows = []
        for path, info, is_dir in self._walk():
            if query.casefold() not in path.casefold():
                continue
            if extension and (is_dir or Path(path).suffix.casefold() != "." + extension.lstrip(".").casefold()):
                continue
            if min_bytes is not None and (is_dir or info.st_size < min_bytes):
                continue
            if max_bytes is not None and (is_dir or info.st_size > max_bytes):
                continue
            if after is not None and info.st_mtime < after or before is not None and info.st_mtime > before:
                continue
            matches = []
            if content:
                if is_dir:
                    continue
                try:
                    text = self._text(path)
                except (OSError, ValueError, UnicodeError):
                    self.check()
                    continue
                for number, line in enumerate(text.splitlines(), 1):
                    if content.casefold() in line.casefold():
                        matches.append({"line": number, "text": line[:250]})
                        if len(matches) >= 3:
                            break
                if not matches:
                    continue
            rows.append({"path": path, "kind": "directory" if is_dir else "file", "bytes": info.st_size,
                         "modified_utc": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(), "matches": matches})
            if len(rows) >= 40:
                self.limited = True
                break
        return {"results": rows, "limited": self.limited, "entries_scanned": self.entries, "bytes_read": self.bytes_read,
                "coverage": "Eligible readable project files only; private, linked, generated and unsupported content excluded."}

    def execute(self, name, arguments):
        self.check()
        handlers = {"list_project_files": self.list_files, "read_project_file": self.read_file,
                    "search_project_files": self.search_files}
        if self.changes is not None and self.changes.enabled and not self.changes.revoked:
            handlers["propose_project_edits"] = lambda edits, explanation, new_files=None: self.changes.propose(self, edits, explanation, new_files)
        ok = False
        try:
            if name not in handlers or not isinstance(arguments, dict):
                raise ValueError("Unknown tool or invalid arguments.")
            result = handlers[name](**arguments)
            ok = True
        except (ValueError, OSError, TypeError, UnicodeError, SyntaxError):
            result = {"error": "Read unavailable: check scope, file type, privacy exclusions and search limits."}
        self.check()
        relative = arguments.get("path", "") if isinstance(arguments, dict) else ""
        if not isinstance(relative, str) or contains_sensitive_text(relative):
            relative = ""
        item = {"tool": name if name in handlers else "unsupported_tool", "path": relative[:600], "ok": ok,
                "time_utc": datetime.now(timezone.utc).isoformat(), "limited": self.limited}
        self.audit.append(item)
        self.on_action(dict(item))
        return result
