"""Explicit document analysis, session-bound follow-ups and confirmed DOCX drafts."""
from __future__ import annotations

import hashlib
from dataclasses import replace
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time
from threading import RLock
from uuid import uuid4

from .content_search import content_path_allowed
from .document_extract import MAX_INPUT
from .models import CommandResult
from .privacy import redact_sensitive_text
from .processes import background_process_options


class DocumentService:
    TTL = 30 * 60

    def __init__(self, files, local_files, ai=None, *, cancelled=None, dry_run=False):
        self.files, self.local_files, self.ai = files, local_files, ai
        self.cancelled = cancelled or (lambda: False)
        self.dry_run = dry_run
        self._lock = RLock()
        self._generation = ""
        self._active = None

    def forget(self) -> CommandResult:
        with self._lock:
            self._active = None
            self._generation = uuid4().hex
        return CommandResult(True, "Document context cleared from this session. Existing saved drafts and conversation/audit history are not deleted.")

    def context(self) -> CommandResult:
        try:
            item = self._get()
            return CommandResult(True, f"Active document: {item['name']}\n{item['coverage']}", metadata=self._metadata(item))
        except (ValueError, OSError) as exc:
            return CommandResult(False, str(exc))

    @staticmethod
    def _stamp(attrs):
        return (attrs.st_dev, attrs.st_ino, attrs.st_size, attrs.st_mtime_ns, attrs.st_ctime_ns)

    def _check(self):
        if self.cancelled():
            raise ValueError("Document task cancelled; no new draft was saved.")

    def _get(self, document_id=None):
        with self._lock:
            item = self._active
            if item and time.monotonic() - item["loaded_at"] >= self.TTL:
                self._active = item = None
            if not item or document_id is not None and document_id != item["document_id"]:
                raise ValueError("No matching active document. Analyze the file again; context expires after 30 minutes or restart.")
            target = self.files._path(item["path"])
            if self._stamp(target.stat()) != item["stamp"]:
                raise ValueError("The source document changed. Analyze it again before discussing or drafting.")
            return {**item, "history": list(item["history"])}

    @staticmethod
    def _metadata(item):
        return {key: item[key] for key in ("document_id", "path", "name", "sha256", "coverage", "partial", "redacted")}

    def _extract(self, data, suffix):
        if getattr(sys, "frozen", False):
            worker = Path(sys.executable).with_name("JarvisDocumentWorker.exe")
            if not worker.is_file():
                raise ValueError("Document worker is missing. Extract the entire Jarvis package again.")
            command = [str(worker), suffix]
        else:
            command = [sys.executable, "-m", "jarvis.document_extract", suffix]
        options = background_process_options()
        options["stdin"] = subprocess.PIPE
        env = dict(os.environ)
        env.pop("OPENAI_API_KEY", None)
        env["JARVIS_LOAD_USER_OPENAI_API_KEY"] = "0"
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        with subprocess.Popen(command,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env, **options) as process:
            deadline, first = time.monotonic() + 20, True
            try:
                while True:
                    self._check()
                    if time.monotonic() >= deadline:
                        raise ValueError("Document extraction exceeded 20 seconds; try a smaller document.")
                    try:
                        output, _ = process.communicate(input=data if first else None, timeout=0.2)
                        break
                    except subprocess.TimeoutExpired:
                        first = False
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        if process.returncode or len(output) > 1024 * 1024:
            raise ValueError("Document extraction failed or exceeded its output limit.")
        payload = json.loads(output)
        if not payload.get("ok"):
            raise ValueError(payload.get("error", "Document extraction failed."))
        return payload["document"]

    def analyze(self, path: str, question: str = "Summarize the document, explain its main argument, and give your critical assessment.") -> CommandResult:
        with self._lock:
            self.forget()
            generation = self._generation
        try:
            self._check()
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 3000:
                raise ValueError("Specify a document question of at most 3000 characters.")
            target = self.files._path(path)
            if target.suffix.casefold() not in {".pdf", ".docx"} or not content_path_allowed(target):
                raise ValueError("Choose an explicit PDF or DOCX outside private/system paths.")
            attrs = target.stat()
            if not stat.S_ISREG(attrs.st_mode) or not 0 < attrs.st_size <= MAX_INPUT:
                raise ValueError("Choose an ordinary nonempty document of at most 20 MiB.")
            if self.dry_run:
                return CommandResult(True, f"Would read and analyze {target}; no content read or sent in dry run.", metadata={"dry_run": True})
            if self.ai is None:
                raise ValueError("AI analysis is unavailable. Configure Jarvis AI before analyzing a document.")
            with target.open("rb") as stream:
                if self._stamp(os.fstat(stream.fileno())) != self._stamp(attrs):
                    raise ValueError("Document changed before reading. Try again.")
                data = stream.read(MAX_INPUT + 1)
                if self._stamp(os.fstat(stream.fileno())) != self._stamp(attrs) or len(data) != attrs.st_size:
                    raise ValueError("Document changed during reading. Try again.")
            extracted = self._extract(data, target.suffix.casefold())
            redaction = redact_sensitive_text("\n\n".join(f"[{block['label']}]\n{block['text']}" for block in extracted["blocks"]))
            item = {"document_id": generation, "path": str(target), "name": target.name,
                    "stamp": self._stamp(attrs), "sha256": hashlib.sha256(data).hexdigest(),
                    "text": redaction.text, "redacted": redaction.redacted,
                    "coverage": extracted["coverage"], "partial": extracted["partial"],
                    "history": [], "loaded_at": time.monotonic()}
            self._check()
            with self._lock:
                if generation != self._generation:
                    raise ValueError("A newer document task replaced this one.")
                self._active = item
            return self.ask(generation, question)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return CommandResult(False, f"Document analysis: {exc}")

    def ask(self, document_id: str, question: str) -> CommandResult:
        try:
            self._check()
            if not isinstance(question, str) or not 1 <= len(question.strip()) <= 3000:
                raise ValueError("Specify a document question of at most 3000 characters.")
            item = self._get(document_id)
            if self.ai is None:
                raise ValueError("AI analysis is unavailable.")
            response = self.ai.answer_document(question, source=item["text"], coverage=item["coverage"], history=item["history"])
            self._check()
            self._get(document_id)
            if response.ok:
                with self._lock:
                    if self._active is None or self._active["document_id"] != document_id:
                        raise ValueError("Document context changed; the old answer was discarded.")
                    self._active["history"] = (self._active["history"] + [(question, response.message[:4000])])[-4:]
            return replace(response, metadata={**response.metadata, **self._metadata(item)},
                           message=f"{response.message}\n\nCoverage: {item['coverage']}")
        except (OSError, ValueError) as exc:
            return CommandResult(False, f"Document question: {exc}")

    def draft(self, document_id: str, destination: str, title: str, instructions: str, target_words: int = 1500) -> CommandResult:
        try:
            self._check()
            item = self._get(document_id)
            if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 160
                    or not isinstance(instructions, str) or not 1 <= len(instructions.strip()) <= 3000
                    or type(target_words) is not int or not 300 <= target_words <= 4000):
                raise ValueError("Specify a title, writing instructions and a target of 300-4000 words for one draft/chapter.")
            if not isinstance(destination, str) or not self.local_files.explicit_path(destination):
                raise ValueError("Specify the destination folder and .docx filename explicitly.")
            target = self.local_files._destination(destination)
            if target.suffix.casefold() != ".docx":
                raise ValueError("Draft destination must be a new .docx file in an existing folder.")
            if self.dry_run:
                return CommandResult(True, f"Would draft {target}; nothing generated or saved.", metadata={"dry_run": True})
            if self.ai is None:
                raise ValueError("AI writing is unavailable.")
            response = self.ai.answer_document(instructions, source=item["text"], coverage=item["coverage"],
                                              history=item["history"], draft_title=title, target_words=target_words)
            if not response.ok:
                return response
            self._check()
            self._get(document_id)
            from docx import Document

            from .document_writer import build_draft
            document = build_draft(title, response.message, item["name"], item["coverage"], item["sha256"])
            with tempfile.TemporaryDirectory(prefix=".jarvis-", dir=target.parent) as staging:
                staged = Path(staging) / "draft.docx"
                document.save(staged)
                check = Document(staged)
                if not check.paragraphs or check.paragraphs[0].text != title.strip():
                    raise ValueError("Generated DOCX validation failed; nothing published.")
                with self._lock:
                    self._get(document_id)
                    self._check()
                    self.local_files._publish(staged, target, time.monotonic() + 30)
            words = len(response.message.split())
            return CommandResult(True, f"Saved a source-based draft to {target} ({words} generated words; target {target_words}). "
                                 "It needs your review and any additional research required for a thesis. Nothing was submitted or opened.",
                                 metadata={**self._metadata(item), "output_path": str(target), "word_count": words,
                                           "target_words": target_words, "verification": "docx_reopened", "draft": True,
                                           "visual_layout_verified": False})
        except ImportError:
            return CommandResult(False, "Install Jarvis with the documents extra to write Word files.")
        except (OSError, ValueError, RuntimeError) as exc:
            return CommandResult(False, f"Document draft: {exc}")
