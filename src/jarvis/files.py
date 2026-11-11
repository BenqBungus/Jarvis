from __future__ import annotations

import os
import stat
import time
import re
from collections import deque
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from threading import RLock
from uuid import uuid4

from .models import CommandResult
from .content_search import TEXT_EXTENSIONS, TextContentSearch, content_path_allowed


_FOLDERS = {"desktop": "Desktop", "documents": "Personal", "pictures": "My Pictures",
            "downloads": "{374DE290-123F-4565-9164-39C4925E467B}"}
_DOCUMENT_TYPES = {".txt", ".md", ".pdf", ".docx", ".xlsx", ".pptx", ".csv",
                   ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".wav", ".mp3", ".mp4"}


class FileSearchService:
    """Bounded local file search. Content inspection requires an explicit folder."""

    def __init__(self, *, dry_run: bool = False, folders: dict[str, Path] | None = None, cancelled=None) -> None:
        self.dry_run = dry_run
        self.folders = folders if folders is not None else self._known_folders()
        self.cancelled = cancelled or (lambda: False)
        self._results_lock = RLock()
        self._search_id = ""
        self._saved_results = []
        self._saved_identities = {}
        self._saved_at = 0.0
        self._saved_partial = False
        self._saved_search_kind = "filename"

    @staticmethod
    def _identity(attrs):
        return (attrs.st_dev, attrs.st_ino, getattr(attrs, "st_birthtime_ns", attrs.st_ctime_ns), stat.S_IFMT(attrs.st_mode))

    @property
    def has_search_context(self) -> bool:
        with self._results_lock:
            return bool(self._search_id)

    def show_results(self) -> CommandResult:
        with self._results_lock:
            if not self._saved_results or time.monotonic() - self._saved_at >= 300:
                return CommandResult(False, "No current file results. Search again; file selections expire after five minutes.")
            rows = [dict(row) for row in self._saved_results]
            message = "\n".join(f"{row['ordinal']}. {row['path']}" for row in rows)
            if self._saved_partial:
                message += "\nThese results are from a partial search."
            return CommandResult(True, message, metadata={"file_results": rows, "search_id": self._search_id,
                                 "partial": self._saved_partial, "content_read": False,
                                 "search_kind": self._saved_search_kind,
                                 "expires_in_seconds": max(0, int(300 - (time.monotonic() - self._saved_at)))})

    def open_result(self, ordinal: int, search_id: str) -> CommandResult:
        with self._results_lock:
            if type(ordinal) is not int or not 1 <= ordinal <= len(self._saved_results):
                return CommandResult(False, "Choose a valid numbered file result from a fresh search.")
            if not search_id or search_id != self._search_id or time.monotonic() - self._saved_at >= 300:
                return CommandResult(False, "File results changed or expired. Search again before opening.")
            if self.cancelled():
                return CommandResult(False, "File opening cancelled.")
            row = self._saved_results[ordinal - 1]
            identity = self._saved_identities.get(row["path"])
            if identity is None or not identity[1]:
                return CommandResult(False, "Cannot verify this file's identity. Search again or review the explicit path.")
            result = self._open_checked(row["path"], expected_identity=identity)
            return result.with_metadata(metadata={**result.metadata, "file_result_ordinal": ordinal,
                                                  "search_id": search_id})

    @staticmethod
    def _known_folders() -> dict[str, Path]:
        folders = {name: Path.home() / name.capitalize() for name in _FOLDERS}
        if os.name == "nt":
            import winreg
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as key:
                    for name, value in _FOLDERS.items():
                        try:
                            folders[name] = Path(winreg.QueryValueEx(key, value)[0])
                        except OSError:
                            pass
            except OSError:
                pass
        return folders

    def _path(self, value: str) -> Path:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Specify a local path or known folder name.")
        raw = value.strip().strip('"')
        first, *tail = re.split(r"[/\\]", raw, maxsplit=1)
        if first.casefold() in self.folders:
            raw = str(self.folders[first.casefold()] / tail[0]) if tail else str(self.folders[first.casefold()])
        if raw.startswith(("\\\\", "//")) or ":" in raw[2:]:
            raise ValueError("Only local filesystem paths are supported, not network/device paths or streams.")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise ValueError("Use an absolute local path or Desktop, Documents, Downloads, Pictures.")
        # Reject reparse points in every component, not just the final file.
        for part in (path, *path.parents):
            attrs = part.lstat()
            if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, "st_file_attributes", 0) & 0x400:
                raise ValueError("Linked or cloud-placeholder paths need separate review.")
        return path.resolve(strict=True)

    def open_path(self, path: str) -> CommandResult:
        return self._open_checked(path)

    def _open_checked(self, path: str, *, expected_identity=None) -> CommandResult:
        try:
            target = self._path(path)
            if expected_identity is not None and self._identity(target.stat()) != expected_identity:
                return CommandResult(False, "The selected file/folder was replaced. Search again; nothing was opened.")
            if not target.is_dir() and target.suffix.lower() not in _DOCUMENT_TYPES:
                return CommandResult(False, "This file type is not approved for direct opening. Scripts, shortcuts and installers are blocked.",
                                     permission="blocked")
            if not self.dry_run:
                os.startfile(str(target))
            return CommandResult(True, f"{'Would request opening' if self.dry_run else 'Windows accepted the open request for'} {target}",
                                 action="open_local_path", metadata={"path": str(target), "exists": True,
                                 "verification": "path_exists" if self.dry_run else "launch_request_accepted",
                                 "window_verified": False})
        except (OSError, ValueError) as exc:
            return CommandResult(False, f"Could not open the local path: {exc}")

    def search(self, query: str = "", root: str = "", *, extension: str = "", kind: str = "any",
               modified_after: str = "", modified_before: str = "", min_size_bytes: int | None = None,
               max_size_bytes: int | None = None, match_mode: str = "contains", max_entries: int = 12000,
               timeout: float = 3.0, content: str | None = None) -> CommandResult:
        with self._results_lock:
            search_id = self._search_id = uuid4().hex
            self._saved_results = []
            self._saved_identities = {}
        if not all(isinstance(value, str) for value in (query, root, extension, kind, modified_after, modified_before, match_mode)):
            return CommandResult(False, "Search names, paths, dates and modes must be text.")
        query = query.strip().casefold()
        extension = extension.strip().casefold().removeprefix(".")
        if content is not None:
            if not isinstance(content, str) or not 2 <= len(content.strip()) <= 200:
                return CommandResult(False, "Use a literal content phrase between 2 and 200 characters.")
            if not root.strip():
                return CommandResult(False, "Content search requires an explicitly chosen local folder; which folder should I search?",
                                     metadata={"clarification_required": True})
            if kind == "folder" or extension and extension not in TEXT_EXTENSIONS:
                return CommandResult(False, "Content search supports TXT, MD and CSV files only, not folders, PDF or DOCX.")
        if extension and not re.fullmatch(r"[a-z0-9]{1,16}", extension):
            return CommandResult(False, "Specify one file extension, for example pdf or .docx, without wildcards.")
        if kind not in {"any", "file", "folder"} or match_mode not in {"contains", "exact", "fuzzy"}:
            return CommandResult(False, "Kind must be any/file/folder; match mode must be contains/exact/fuzzy.")
        for size in (min_size_bytes, max_size_bytes):
            if size is not None and (type(size) is not int or not 0 <= size <= 2**63 - 1):
                return CommandResult(False, "Size limits must be nonnegative whole bytes.")
        if min_size_bytes is not None and max_size_bytes is not None and min_size_bytes > max_size_bytes:
            return CommandResult(False, "Minimum size exceeds maximum size.")
        file_only = content is not None or bool(extension) or min_size_bytes is not None or max_size_bytes is not None
        if kind == "folder" and file_only:
            return CommandResult(False, "Extension and size filters apply to files, not folder totals.")
        if query and (len(query) < 2 or len(query) > 200):
            return CommandResult(False, "Use a filename fragment between 2 and 200 characters.")
        if not query and not (file_only or modified_after or modified_before or kind != "any"):
            return CommandResult(False, "Specify a filename fragment or at least one search filter.")
        try:
            def day(value):
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                    raise ValueError("Dates must use YYYY-MM-DD.")
                return datetime.strptime(value, "%Y-%m-%d")
            after = day(modified_after).timestamp() if modified_after else None
            before = (day(modified_before) + timedelta(days=1)).timestamp() if modified_before else None
            if after is not None and before is not None and after >= before:
                raise ValueError("Start date is later than end date.")
        except (ValueError, OverflowError, OSError) as exc:
            return CommandResult(False, f"Invalid modification-date filter: {exc}")
        if (type(max_entries) is not int or not 1 <= max_entries <= 12000
                or type(timeout) not in (int, float) or not 0 < timeout <= 10):
            return CommandResult(False, "Search limits must be 1-12000 entries and at most 10 seconds.")
        filters = {"query": query, "extension": extension, "kind": kind, "match_mode": match_mode,
                   "modified_after": modified_after, "modified_before": modified_before,
                   "min_size_bytes": min_size_bytes, "max_size_bytes": max_size_bytes}

        def match(name, folder, attrs):
            if (kind == "file" or file_only) and folder or kind == "folder" and not folder:
                return None
            if extension and Path(name).suffix.casefold() != "." + extension:
                return None
            if after is not None and attrs.st_mtime < after or before is not None and attrs.st_mtime >= before:
                return None
            if min_size_bytes is not None and attrs.st_size < min_size_bytes or max_size_bytes is not None and attrs.st_size > max_size_bytes:
                return None
            name = name.casefold()
            if not query or name == query:
                return 1.0
            if match_mode == "contains":
                return 1.0 if query in name else None
            if match_mode == "fuzzy":
                score = max(SequenceMatcher(None, query, name).ratio(),
                            SequenceMatcher(None, query, Path(name).stem).ratio())
                return round(score, 3) if score >= 0.75 else None
            return None

        roots, skipped = [], 0
        for value in ([root] if root else list(self.folders)):
            try:
                path = self._path(value)
                if not path.is_dir():
                    raise ValueError("Search root must be a folder.")
                if content is not None and (not content_path_allowed(path) or path == Path(path.anchor) or path == Path.home()):
                    raise ValueError("Choose a document folder, not a private/system folder, home root or drive root.")
                if path not in roots:
                    roots.append(path)
            except (OSError, ValueError):
                skipped += 1
        if not roots:
            return CommandResult(False, "No accessible local search folder.")
        deadline, visited, results, pending, seen = time.monotonic() + timeout, 0, [], deque(roots), set()
        reader = TextContentSearch(content.strip(), deadline=deadline, cancelled=self.cancelled) if content is not None else None
        limited, cancelled = False, False
        identities = {}
        while pending:
            directory = pending.popleft()
            if directory in seen:
                continue
            seen.add(directory)
            if self.cancelled():
                cancelled = True
                break
            if time.monotonic() >= deadline or visited >= max_entries:
                limited = True
                break
            try:
                self._path(str(directory))  # Recheck parents before traversing a queued directory.
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if self.cancelled():
                            cancelled = True
                            break
                        if time.monotonic() >= deadline or visited >= max_entries or len(results) >= 25:
                            limited = True
                            break
                        visited += 1
                        try:
                            attrs = entry.stat(follow_symlinks=False)
                            if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, "st_file_attributes", 0) & 0x400:
                                skipped += 1
                                continue
                            folder = entry.is_dir(follow_symlinks=False)
                            if not folder and not stat.S_ISREG(attrs.st_mode):
                                skipped += 1
                                continue
                            if reader and (not content_path_allowed(Path(entry.path))
                                           or not folder and Path(entry.name).suffix.casefold().lstrip(".") not in TEXT_EXTENSIONS):
                                skipped += 1
                                continue
                            score = match(entry.name, folder, attrs)
                            if score is not None:
                                # Windows directory enumeration can omit the file ID.
                                attrs = self._path(entry.path).stat()
                                folder = stat.S_ISDIR(attrs.st_mode)
                                if not folder and not stat.S_ISREG(attrs.st_mode):
                                    skipped += 1
                                    continue
                                score = match(entry.name, folder, attrs)
                                if score is None:
                                    continue
                                if reader:
                                    matched = reader.matches(self._path(entry.path), attrs)
                                    if matched is None:
                                        skipped += 1
                                    if reader.stopped():
                                        limited, cancelled = reader.limited, reader.cancelled
                                        break
                                    if not matched:
                                        continue
                                identities[entry.path] = self._identity(attrs)
                                results.append({"path": entry.path, "name": entry.name, "is_directory": folder,
                                                "size_bytes": None if folder else attrs.st_size,
                                                "modified_at": datetime.fromtimestamp(attrs.st_mtime).astimezone().isoformat(),
                                                "match_score": score})
                            if folder and not entry.name.startswith(".") and entry.name.casefold() not in {"appdata", "$recycle.bin", "windows"}:
                                pending.append(Path(entry.path))
                            elif folder:
                                skipped += 1
                        except (OSError, ValueError, OverflowError):
                            skipped += 1
            except (OSError, ValueError):
                skipped += 1
            if limited or cancelled:
                break
        results.sort(key=lambda item: (-item["match_score"], item["path"].casefold()))
        for index, item in enumerate(results, 1):
            item["ordinal"] = index
        with self._results_lock:
            superseded = search_id != self._search_id
            if not cancelled and not superseded:
                self._saved_results = [dict(row) for row in results]
                self._saved_identities = identities
                self._saved_at = time.monotonic()
                self._saved_partial = limited or bool(skipped)
                self._saved_search_kind = "content" if reader else "filename"
        lines = [f"{index}. {item['path']} | {'folder' if item['is_directory'] else str(item['size_bytes']) + ' bytes'} | modified {item['modified_at']}"
                 for index, item in enumerate(results, 1)] or ["No matches in the inspected folders."]
        if match_mode == "fuzzy" and results:
            lines.insert(0, "Approximate name matches: review the paths before choosing a file.")
        if reader:
            lines.insert(0, "Literal text search in TXT, MD and CSV only. Document contents and excerpts are not returned.")
        if cancelled:
            lines.append("Search cancelled. Results cover only the folders inspected so far.")
        elif limited or skipped:
            lines.append("Search is partial: a limit, excluded file or inaccessible path was reached.")
        if superseded:
            lines.append("A newer file search replaced this selection list; review the latest results.")
        return CommandResult(not cancelled, "\n".join(lines), action="search_local_files", metadata={
            "file_results": results, "partial": limited or bool(skipped) or cancelled, "entries_checked": visited,
            "filters": filters, "cancelled": cancelled, "date_basis": "local modification date, inclusive bounds",
            "search_id": search_id, "selection_available": bool(results) and not cancelled and not superseded,
            "skipped_paths": skipped, "roots": [str(path) for path in roots], "content_read": bool(reader and reader.files_read),
            "search_kind": "content" if reader else "filename",
            "content_files_read": reader.files_read if reader else 0, "content_bytes_read": reader.bytes_read if reader else 0})
