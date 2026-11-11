"""AI-assisted text/code edits with preview and no-overwrite revised copies."""
from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time
from threading import RLock
from uuid import uuid4

from .content_search import content_path_allowed
from .models import CommandResult
from .privacy import contains_sensitive_text

EDIT_TYPES = {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".css", ".html", ".json", ".yaml", ".yml"}
MAX_EDIT_BYTES = 64000


class FileEditing:
    def __init__(self, files, local_files, ai=None, *, cancelled=None, dry_run=False):
        self.files, self.local_files, self.ai = files, local_files, ai
        self.cancelled = cancelled or (lambda: False)
        self.dry_run = dry_run
        self._lock = RLock()
        self._pending = None
        self._generation = ""

    def discard(self):
        with self._lock:
            self._pending, self._generation = None, uuid4().hex
        return CommandResult(True, "Edit proposal discarded. No file was changed.")

    def _read(self, path):
        target = self.files._path(path)
        if target.suffix.casefold() not in EDIT_TYPES or not content_path_allowed(target):
            raise ValueError("Choose an ordinary text/code file outside private/system/config paths. PDF/Word editing is not supported here.")
        attrs = target.stat()
        if not stat.S_ISREG(attrs.st_mode) or attrs.st_size > MAX_EDIT_BYTES:
            raise ValueError("Text editing supports files of at most 64000 bytes.")
        with target.open("rb") as stream:
            before = os.fstat(stream.fileno())
            data = stream.read(MAX_EDIT_BYTES + 1)
            after = os.fstat(stream.fileno())
        stamp = lambda a: (a.st_dev, a.st_ino, a.st_mtime_ns, a.st_ctime_ns, a.st_size)
        if stamp(attrs) != stamp(before) or stamp(before) != stamp(after) or len(data) != attrs.st_size:
            raise ValueError("File changed during reading. Try again.")
        content = data.decode("utf-8-sig")
        if "\x00" in content or contains_sensitive_text(content):
            raise ValueError("Binary content or recognized credentials found; no AI editing allowed for this file.")
        return target, data, content

    def propose(self, path: str, instructions: str):
        with self._lock:
            self.discard()
            generation = self._generation
        try:
            if not isinstance(instructions, str) or not 1 <= len(instructions.strip()) <= 3000:
                raise ValueError("Provide editing instructions of at most 3000 characters.")
            if self.cancelled():
                raise ValueError("Editing cancelled.")
            if self.dry_run:
                return CommandResult(True, "Would propose a file edit; dry run reads and writes nothing.")
            target, original, content = self._read(path)
            if self.ai is None:
                raise ValueError("AI editing is not configured.")
            response = self.ai.propose_text_edit(content, instructions, target.suffix.casefold())
            if not response.ok:
                return response
            payload = json.loads(response.message)
            if not isinstance(payload, dict) or set(payload) != {"replacement", "explanation"}:
                raise ValueError("AI returned an invalid edit proposal.")
            replacement, explanation = payload["replacement"], payload["explanation"]
            if not isinstance(replacement, str) or not isinstance(explanation, str) or len(explanation) > 2000:
                raise ValueError("Invalid replacement or explanation.")
            if len(replacement.encode("utf-8")) > MAX_EDIT_BYTES or "\x00" in replacement or contains_sensitive_text(replacement) or contains_sensitive_text(explanation):
                raise ValueError("Replacement exceeds limits or contains recognized credentials.")
            if target.suffix.casefold() == ".json":
                json.loads(replacement)
            elif target.suffix.casefold() == ".py":
                ast.parse(replacement)
            if replacement == content:
                return CommandResult(True, "No changes proposed.")
            diff = "\n".join(difflib.unified_diff(content.splitlines(), replacement.splitlines(), fromfile=target.name,
                                               tofile=f"revised/{target.name}", lineterm=""))
            if len(diff) > 20000:
                raise ValueError("The proposed change is too large to preview safely. Request a smaller edit.")
            if self.cancelled():
                raise ValueError("Editing cancelled.")
            newline = "\r\n" if b"\r\n" in original else "\n"
            encoded = replacement.replace("\r\n", "\n").replace("\n", newline).encode("utf-8")
            if original.startswith(b"\xef\xbb\xbf"):
                encoded = b"\xef\xbb\xbf" + encoded
            if len(encoded) > MAX_EDIT_BYTES:
                raise ValueError("Encoded replacement exceeds the size limit.")
            with self._lock:
                if self._generation != generation:
                    raise ValueError("A newer edit replaced this proposal.")
                self._pending = {"proposal_id": generation, "path": str(target), "digest": hashlib.sha256(original).hexdigest(),
                                 "bytes": encoded, "created": time.monotonic(), "diff": diff, "explanation": explanation}
            return self.preview()
        except (OSError, ValueError, SyntaxError, TypeError) as exc:
            # JSON/parser exception excerpts may contain model-generated private text.
            return CommandResult(False, f"Edit proposal rejected ({type(exc).__name__}). Check file type, size, encoding, sensitive content and replacement syntax; nothing was saved.")

    def preview(self):
        with self._lock:
            item = self._pending
            if not item or time.monotonic() - item["created"] >= 300:
                self._pending = None
                return CommandResult(False, "No current edit proposal. Proposals expire after five minutes.")
            return CommandResult(True, f"{item['explanation']}\n\n{item['diff']}\n\nPreview only. Save an edited copy after review; the original will remain unchanged.",
                                 metadata={"proposal_id": item["proposal_id"], "source_path": item["path"], "diff": item["diff"], "saved": False})

    def save_copy(self, proposal_id: str, destination: str):
        try:
            with self._lock:
                item = self._pending
                if not self.preview().ok or item["proposal_id"] != proposal_id:
                    raise ValueError("Edit proposal changed or expired; request a new preview.")
                target, data, _ = self._read(item["path"])
                if hashlib.sha256(data).hexdigest() != item["digest"]:
                    raise ValueError("Source file changed since the preview; request a new proposal.")
                if not isinstance(destination, str) or not self.local_files.explicit_path(destination):
                    raise ValueError("Choose an explicit destination folder and new filename.")
                output = self.local_files._destination(destination)
                if output.suffix.casefold() != target.suffix.casefold():
                    raise ValueError("Keep the original file extension for the revised copy.")
                if self.cancelled():
                    raise ValueError("Editing cancelled; nothing saved.")
                if self.dry_run:
                    return CommandResult(True, f"Would save revised copy {output}; dry run writes nothing.")
                with tempfile.TemporaryDirectory(prefix=".jarvis-", dir=output.parent) as staging:
                    staged = Path(staging) / "revised"
                    staged.write_bytes(item["bytes"])
                    if self.cancelled():
                        raise ValueError("Editing cancelled; nothing saved.")
                    self.local_files._publish(staged, output, time.monotonic() + 30)
                self._pending = None
                return CommandResult(True, f"Saved revised copy: {output}. Original unchanged. Code was not executed or runtime-tested.",
                                     metadata={"path": str(output), "source_path": str(target), "original_preserved": True, "executed": False})
        except (OSError, ValueError, RuntimeError) as exc:
            return CommandResult(False, str(exc))
