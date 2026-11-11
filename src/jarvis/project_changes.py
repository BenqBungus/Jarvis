"""Reviewed multi-file source patches with conflict checks and one durable undo."""
from __future__ import annotations

import ast
import base64
import difflib
import hashlib
import json
import os
import stat
import tempfile
import threading
from pathlib import Path, PureWindowsPath
from uuid import uuid4

from .models import CommandResult
from .privacy import contains_sensitive_text
from .project_workspace import ProjectReader, SOURCE_TYPES


def digest(data):
    return hashlib.sha256(data).hexdigest()


class ProjectChanges:
    MAX_BYTES = 128 * 1024

    def __init__(self, workspace):
        self.workspace = workspace
        self.enabled = False
        self.revoked = False
        self._pending = None
        self._lock = threading.RLock()

    def discard(self):
        with self._lock:
            self._pending = None

    def revoke(self):
        with self._lock:
            self.revoked = True
            self.enabled = False
            self._pending = None

    def _current(self, relative):
        reader = ProjectReader(self.workspace)
        reader._text(relative)
        return reader.snapshots[self.workspace.path(relative).relative_to(self.workspace.root).as_posix()]

    def _new_target(self, relative):
        target = self.workspace.path(relative, allow_missing_leaf=True)
        parts = Path(relative).parts
        if (not parts or any(PureWindowsPath(part).is_reserved() or part.endswith((" ", "."))
                or any(ord(c) < 32 or c in '<>:"|?*' for c in part) for part in parts)
                or target.suffix.casefold().lstrip(".") not in SOURCE_TYPES):
            raise ValueError("Choose a supported source filename without Windows reserved names.")
        return target

    def _current_or_absent(self, relative):
        target = self._new_target(relative)
        try:
            target.lstat()
        except FileNotFoundError:
            return None
        return self._current(relative)

    def propose(self, reader, edits, explanation, new_files=None):
        with self._lock:
            reader.check()
            if self.revoked or not self.enabled:
                raise ValueError("Edit proposals are not enabled.")
            self._pending = None
            if new_files is None:
                new_files = []
            if (not isinstance(edits, list) or not isinstance(new_files, list)
                    or len(edits) > 12 or len(new_files) > 6 or not (edits or new_files)):
                raise ValueError("Propose up to 12 replacements and six new files, with at least one change.")
            if not isinstance(explanation, str) or not 1 <= len(explanation) <= 2000 or contains_sensitive_text(explanation):
                raise ValueError("Invalid explanation.")
            sources, revised = {}, {}
            for edit in edits:
                reader.check()
                if not isinstance(edit, dict) or set(edit) != {"path", "old_text", "new_text"}:
                    raise ValueError("Invalid edit shape.")
                path, old, new = edit["path"], edit["old_text"], edit["new_text"]
                target = self.workspace.path(path)
                relative = target.relative_to(self.workspace.root).as_posix()
                if relative not in reader.read_paths:
                    raise ValueError("Read each file before proposing a change.")
                if not all(isinstance(value, str) and len(value) <= 16000 for value in (old, new)) or not old:
                    raise ValueError("Use a non-empty exact old text and a bounded replacement.")
                if contains_sensitive_text(old) or contains_sensitive_text(new) or "\x00" in new:
                    raise ValueError("Sensitive or binary replacement rejected.")
                if relative not in sources:
                    original = reader.snapshots[relative]
                    if self._current(relative) != original:
                        raise ValueError("Source changed since it was read.")
                    sources[relative] = original
                    revised[relative] = original.decode("utf-8-sig").replace("\r\n", "\n")
                old, new = old.replace("\r\n", "\n"), new.replace("\r\n", "\n")
                if revised[relative].count(old) != 1:
                    raise ValueError("Old text must match exactly once; request more surrounding lines.")
                revised[relative] = revised[relative].replace(old, new, 1)
            for item in new_files:
                reader.check()
                if not isinstance(item, dict) or set(item) != {"path", "content"}:
                    raise ValueError("Invalid new file shape.")
                target = self._new_target(item["path"])
                relative = target.relative_to(self.workspace.root).as_posix()
                if relative.casefold() in {path.casefold() for path in sources}:
                    raise ValueError("Duplicate or overlapping file change.")
                if target.parent.relative_to(self.workspace.root).as_posix() not in reader.listed_paths:
                    raise ValueError("List the destination directory before proposing a new file.")
                if self._current_or_absent(relative) is not None:
                    raise ValueError("New file already exists. Read it and propose an edit instead.")
                text = item["content"]
                if (not isinstance(text, str) or len(text) > 16000 or contains_sensitive_text(text)
                        or any(ord(c) < 32 and c not in "\r\n\t" for c in text)):
                    raise ValueError("Oversized, binary or recognized sensitive new content rejected.")
                sources[relative] = None
                revised[relative] = text.replace("\r\n", "\n")
            if len(sources) > 6 or sum(len(data or b"") for data in sources.values()) > self.MAX_BYTES:
                raise ValueError("Patch exceeds six files or 128 KiB of original source.")
            entries, diffs = [], []
            for path, text in revised.items():
                original = sources[path]
                if Path(path).suffix.casefold() == ".py":
                    ast.parse(text)
                elif Path(path).suffix.casefold() == ".json":
                    json.loads(text)
                newline = "\r\n" if original is not None and b"\r\n" in original else "\n"
                data = text.replace("\n", newline).encode("utf-8")
                if original is not None and original.startswith(b"\xef\xbb\xbf"):
                    data = b"\xef\xbb\xbf" + data
                if data == original:
                    continue
                entries.append({"path": path, "before": original, "after": data})
                if original is None and not text:
                    diffs.extend(["--- /dev/null", "+++ " + path, "(new empty file)"])
                else:
                    diffs.extend(difflib.unified_diff((original or b"").decode("utf-8-sig").splitlines(), text.splitlines(),
                        fromfile=path if original is not None else "/dev/null", tofile=path, lineterm=""))
            diff = "\n".join(diffs)
            if not entries or len(diff) > 24000 or sum(len(item["after"]) for item in entries) > self.MAX_BYTES:
                raise ValueError("Empty or oversized patch. Request a smaller change.")
            reader.check()
            self._pending = {"id": uuid4().hex, "explanation": explanation, "diff": diff, "entries": entries}
            return self.preview()

    def preview(self):
        with self._lock:
            if self.revoked or not self._pending:
                return None
            item = self._pending
            return {"proposal_id": item["id"], "explanation": item["explanation"], "diff": item["diff"],
                    "files": [entry["path"] for entry in item["entries"]], "applied": False,
                    "created_files": [entry["path"] for entry in item["entries"] if entry["before"] is None]}

    def _journal_path(self):
        self.workspace.path(".")
        path = self.workspace.root / ".jarvis-undo.json"
        try:
            info = path.lstat()
        except FileNotFoundError:
            return path
        self.workspace._validate_components(path)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1:
            raise ValueError("Undo journal is not an ordinary local file.")
        return path

    @staticmethod
    def _stage(path, data):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".jarvis-edit-", dir=path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            return temporary
        except BaseException:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
            raise

    def _save_journal(self, item):
        path = self._journal_path()
        temporary = self._stage(path, json.dumps(item, ensure_ascii=True).encode("utf-8"))
        try:
            self._journal_path()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _replace(self, relative, expected, replacement):
        target = self.workspace.path(relative)
        if self._current(relative) != expected:
            raise ValueError("Source conflict; newer edits were preserved.")
        mode = stat.S_IMODE(target.stat().st_mode)
        if not mode & stat.S_IWUSR:
            raise ValueError("Read-only source cannot be replaced.")
        temporary = self._stage(target, replacement)
        try:
            os.chmod(temporary, mode)
            self.workspace.path(relative)
            if self._current(relative) != expected:
                raise ValueError("Source changed before replacement.")
            os.replace(temporary, target)
            if self._current(relative) != replacement:
                raise ValueError("Replacement verification failed.")
        finally:
            temporary.unlink(missing_ok=True)

    def _create(self, relative, temporary, expected, identity):
        target = self._new_target(relative)
        self.workspace._validate_components(temporary)
        info = temporary.stat()
        if [info.st_dev, info.st_ino] != identity or info.st_nlink != 1:
            raise ValueError("Staged file changed before creation.")
        # A hard-link publish fails if any destination already exists, unlike replace().
        os.link(temporary, target)
        temporary.unlink()
        if self._current(relative) != expected:
            raise ValueError("New file verification failed.")

    def _check_created(self, relative, expected, identity):
        target = self._new_target(relative)
        if self._current_or_absent(relative) != expected:
            raise ValueError("Created file content changed; preserve it.")
        if expected is not None:
            info = target.stat()
            if [info.st_dev, info.st_ino] != identity:
                raise ValueError("Created file was replaced; preserve it.")
        return target

    def _remove_created(self, relative, expected, identity):
        target = self._check_created(relative, expected, identity)
        if expected is not None:
            target.unlink()
            if self._current_or_absent(relative) is not None:
                raise ValueError("Created file removal could not be verified.")

    def apply(self, proposal_id, *, confirmed=False):
        with self._lock:
            if not confirmed or self.revoked or not self._pending or self._pending["id"] != proposal_id:
                return CommandResult(False, "Review the current patch and explicitly approve it before applying.")
            pending = self._pending
            entries = pending["entries"]
            attempted = []
            staged = {}
            identities = {}
            journal = {"version": 2 if any(item["before"] is None for item in entries) else 1,
                       "proposal_id": proposal_id, "state": "prepared", "entries": []}
            try:
                for item in entries:
                    current = self._current_or_absent(item["path"]) if item["before"] is None else self._current(item["path"])
                    if current != item["before"]:
                        raise ValueError("Source changed since preview. Request a new patch.")
                    entry = {"path": item["path"], "original": None if item["before"] is None else base64.b64encode(item["before"]).decode("ascii"),
                             "before_sha256": None if item["before"] is None else digest(item["before"]),
                             "after_sha256": digest(item["after"])}
                    if item["before"] is None:
                        temporary = self._stage(self._new_target(item["path"]), item["after"])
                        staged[item["path"]] = temporary
                        info = temporary.stat()
                        identities[item["path"]] = [info.st_dev, info.st_ino]
                        entry["created_identity"] = identities[item["path"]]
                    journal["entries"].append(entry)
                self._save_journal(journal)
                for item in entries:
                    attempted.append(item)
                    if item["before"] is None:
                        self._create(item["path"], staged[item["path"]], item["after"], identities[item["path"]])
                    else:
                        self._replace(item["path"], item["before"], item["after"])
                journal["state"] = "applied"
                self._save_journal(journal)
                self._pending = None
                return CommandResult(True, f"Applied and verified {len(entries)} file changes. Runtime tests have not been run.",
                    metadata={"files": [item["path"] for item in entries], "applied": True,
                              "created_files": [item["path"] for item in entries if item["before"] is None],
                              "tests_run": False, "undo_available": True, "proposal_id": proposal_id})
            except (OSError, ValueError):
                conflicts = []
                for item in reversed(attempted):
                    try:
                        if item["before"] is None:
                            current = self._current_or_absent(item["path"])
                            if current is not None:
                                self._remove_created(item["path"], item["after"], identities[item["path"]])
                            continue
                        current = self._current(item["path"])
                        if current == item["after"]:
                            self._replace(item["path"], current, item["before"])
                        elif current != item["before"]:
                            conflicts.append(item["path"])
                    except (OSError, ValueError):
                        conflicts.append(item["path"])
                if attempted:
                    journal["state"] = "recovery_needed" if conflicts else "rolled_back"
                    try:
                        self._save_journal(journal)
                    except (OSError, ValueError):
                        pass  # The prepared journal still contains original bytes.
                self._pending = None
                return CommandResult(False, "Patch not completed. " +
                    ("Some files need manual recovery; originals remain in .jarvis-undo.json." if conflicts
                     else "No patch changes remain; concurrent edits were preserved."),
                    metadata={"applied": False, "recovery_needed": conflicts})
            finally:
                for temporary in staged.values():
                    temporary.unlink(missing_ok=True)

    def _load_journal(self):
        path = self._journal_path()
        if not path.exists() or path.stat().st_size > 512 * 1024:
            raise ValueError("No supported undo journal.")
        with path.open("rb") as stream:
            payload = stream.read(512 * 1024 + 1)
        if len(payload) > 512 * 1024:
            raise ValueError("Oversized undo journal.")
        item = json.loads(payload)
        if (not isinstance(item, dict) or item.get("version") not in {1, 2}
                or item.get("state") not in {"applied", "prepared", "recovery_needed"}
                or not isinstance(item.get("entries"), list) or not 1 <= len(item["entries"]) <= 6):
            raise ValueError("No reversible patch.")
        paths, total = set(), 0
        for entry in item["entries"]:
            if not isinstance(entry, dict):
                raise ValueError("Invalid undo entry.")
            created = item["version"] == 2 and entry.get("original") is None
            fields = {"path", "original", "before_sha256", "after_sha256"}
            if created:
                fields.add("created_identity")
            if set(entry) != fields:
                raise ValueError("Invalid undo entry.")
            target = self._new_target(entry["path"]) if created else self.workspace.path(entry["path"])
            if target in paths:
                raise ValueError("Duplicate undo path.")
            paths.add(target)
            after_hash = entry["after_sha256"]
            if not isinstance(after_hash, str) or len(after_hash) != 64 or any(c not in "0123456789abcdef" for c in after_hash):
                raise ValueError("Invalid after hash.")
            if created:
                identity = entry["created_identity"]
                if (entry["before_sha256"] is not None or not isinstance(identity, list) or len(identity) != 2
                        or any(type(value) is not int or value < 0 for value in identity)):
                    raise ValueError("Invalid created file identity.")
                continue
            data = base64.b64decode(entry["original"], validate=True)
            total += len(data)
            if total > self.MAX_BYTES or digest(data) != entry["before_sha256"] or len(entry["after_sha256"]) != 64:
                raise ValueError("Invalid undo data.")
            text = data.decode("utf-8-sig")
            if "\x00" in text or contains_sensitive_text(text):
                raise ValueError("Sensitive undo data rejected.")
        return item

    def undo_available(self):
        try:
            return not self.revoked and bool(self._load_journal())
        except (ValueError, OSError, TypeError, KeyError):
            return False

    def undo(self, *, confirmed=False):
        with self._lock:
            if not confirmed or self.revoked:
                return CommandResult(False, "Explicitly approve Undo in the selected project.")
            try:
                journal = self._load_journal()
                originals = []
                for entry in journal["entries"]:
                    if entry["original"] is None:
                        current = self._current_or_absent(entry["path"])
                        if current is not None and digest(current) != entry["after_sha256"]:
                            raise ValueError("New file changed; preserve it.")
                        self._check_created(entry["path"], current, entry["created_identity"])
                        originals.append((entry["path"], current, None, entry["created_identity"]))
                        continue
                    current = self._current(entry["path"])
                    if digest(current) not in {entry["before_sha256"], entry["after_sha256"]}:
                        raise ValueError("Newer edits conflict with Undo.")
                    originals.append((entry["path"], current, base64.b64decode(entry["original"], validate=True), None))
                for path, current, original, identity in originals:
                    if original is None:
                        self._remove_created(path, current, identity)
                        continue
                    if current != original:
                        self._replace(path, current, original)
                journal["state"] = "undone"
                self._save_journal(journal)
                self._pending = None
                return CommandResult(True, "Restored and verified previous contents; unchanged files created by this patch were removed.", metadata={"undone": True})
            except (OSError, ValueError, TypeError, KeyError):
                return CommandResult(False, "Undo could not complete. Newer edits are not overwritten; the journal retains original bytes. Check the files before retrying.")
