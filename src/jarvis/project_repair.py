"""Bounded, review-gated project repair sessions; no model-selected commands."""
import hashlib
import json
import threading
import time

from .models import CommandResult
from .privacy import redact_sensitive_text
from .project_checks import ProjectChecks
from .project_workspace import ProjectReader


class ProjectRepair:
    MAX_DIAGNOSES = 2
    MAX_SECONDS = 900

    def __init__(self, changes, diagnose, *, profile="syntax", runtime=""):
        if profile not in {"syntax", "pytest"}:
            raise ValueError("Unsupported repair check profile.")
        self.changes, self.diagnose = changes, diagnose
        self.profile, self.runtime = profile, runtime
        self.checks = ProjectChecks(changes.workspace)
        self.state = "idle"
        self.diagnoses = 0
        self.check_count = 0
        self.events = []
        self.proposal_id = None
        self._seen = set()
        self._cancelled = threading.Event()
        self._lock = threading.Lock()
        self._deadline = 0
        self._timer = None

    @property
    def active(self):
        return self.state in {"checking", "diagnosing", "awaiting_review", "applying"}

    def stopped(self):
        return (self._cancelled.is_set() or self.changes.revoked or not self.changes.enabled
                or (self._deadline > 0 and time.monotonic() >= self._deadline))

    def cancel(self):
        self._cancelled.set()
        self.checks.cancel()
        self.changes.discard()
        if self._timer is not None:
            self._timer.cancel()
        if self.active:
            self.state = "cancelled"

    def _result(self, state, message):
        if self.stopped() and state != "cancelled":
            state = "cancelled"
            message = "Repair stopped or permission expired. Already applied edits remain; use Undo for the latest patch."
        self.state = state
        if not self.active and self._timer is not None:
            self._timer.cancel()
        if state != "awaiting_review":
            self.changes.discard()
        return CommandResult(state in {"passed", "awaiting_review"}, message, metadata={
            "repair_state": state, "profile": self.profile, "checks_run": self.check_count,
            "diagnoses": self.diagnoses, "proposal_id": self.proposal_id,
            "events": list(self.events), "verification_scope": "Selected check only, not all project behavior."})

    def _stopped_result(self):
        return self._result("cancelled", "Repair stopped or permission expired. Already applied edits remain; use Undo to restore the latest patch.")

    def start(self, *, confirmed=False):
        if not self._lock.acquire(blocking=False):
            return CommandResult(False, "A repair operation is already running.")
        try:
            if self.state != "idle" or not confirmed or self.stopped() or self.changes.preview():
                return CommandResult(False, "Approve a fresh repair session with proposals enabled and no pending patch.")
            self._deadline = time.monotonic() + self.MAX_SECONDS
            self._timer = threading.Timer(self.MAX_SECONDS, self.cancel)
            self._timer.daemon = True
            self._timer.start()
            return self._check_and_diagnose()
        except Exception:
            return self._result("failed", "Repair could not continue. No successful verification is recorded.")
        finally:
            self._lock.release()

    def approve(self, proposal_id, *, confirmed=False):
        if not self._lock.acquire(blocking=False):
            return CommandResult(False, "A repair operation is already running.")
        try:
            if self.stopped():
                return self._stopped_result()
            if self.state != "awaiting_review" or not confirmed:
                return CommandResult(False, "Review and approve the pending repair patch first.")
            pending = self.changes.preview()
            if not pending or proposal_id != self.proposal_id or pending["proposal_id"] != proposal_id:
                return self._result("failed", "The reviewed patch changed. Start a new repair session.")
            self.state = "applying"
            applied = self.changes.apply(proposal_id, confirmed=True)
            self.events.append({"action": "apply", "ok": applied.ok, "files": applied.metadata.get("files", [])})
            if self.stopped():
                return self._stopped_result()
            if not applied.ok:
                return self._result("failed", applied.message)
            return self._check_and_diagnose()
        except Exception:
            return self._result("failed", "Repair could not continue. Applied edits may remain; inspect the project and Undo record.")
        finally:
            self._lock.release()

    def _check_and_diagnose(self):
        if self.stopped():
            return self._stopped_result()
        self.state = "checking"
        self.check_count += 1
        check = (self.checks.syntax() if self.profile == "syntax" else
                 self.checks.pytest(self.runtime, confirmed=True, timeout=min(120, max(0.1, self._deadline - time.monotonic()))))
        self.events.append({"action": "check", "ok": check.ok, "profile": self.profile,
                            "exit_code": check.metadata.get("exit_code")})
        if self.stopped():
            return self._stopped_result()
        if check.ok:
            return self._result("passed", "Selected check passed. This does not prove the whole project is correct.\n" + check.message)
        diagnostic = (bool(check.metadata.get("errors")) if self.profile == "syntax" else
                      check.metadata.get("exit_code") in {1, 2} and not check.metadata.get("interrupted"))
        if not diagnostic or self.diagnoses >= self.MAX_DIAGNOSES:
            return self._result("stopped", "No further repair attempt: check unavailable, incomplete, or attempt limit reached.\n" + check.message)
        self.state = "diagnosing"
        self.diagnoses += 1
        reader = ProjectReader(self.changes.workspace, cancelled=self.stopped, changes=self.changes)
        evidence = redact_sensitive_text(check.message + "\n" + json.dumps(check.metadata, ensure_ascii=True)).text[:16000]
        diagnosis = self.diagnose(evidence, reader)
        self.events.extend({"action": "project_tool", **item} for item in reader.audit)
        if self.stopped():
            return self._stopped_result()
        if not diagnosis.ok:
            return self._result("failed", diagnosis.message)
        proposal = self.changes.preview()
        if not proposal:
            return self._result("stopped", "No applicable patch proposed.\n" + diagnosis.message)
        fingerprint = hashlib.sha256(proposal["diff"].encode("utf-8")).hexdigest()
        if fingerprint in self._seen:
            return self._result("stopped", "Repeated patch proposal detected. No further automatic attempts.")
        self._seen.add(fingerprint)
        self.proposal_id = proposal["proposal_id"]
        return self._result("awaiting_review", "Review the patch before applying. The same check will run again after approval.\n" + diagnosis.message)
