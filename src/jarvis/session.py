from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from .audit import AuditLogger
from .error_taxonomy import enrich_error_metadata
from .models import CommandResult
from .privacy import redact_sensitive_data

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandStateEvent:
    state: str
    elapsed_ms: float
    detail: str = ""
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _TimelineRecorder:
    def __init__(self) -> None:
        self._started_at = perf_counter()
        self.events: list[CommandStateEvent] = []

    def add(self, state: str, detail: str = "", metadata: dict[str, Any] | None = None) -> None:
        self.events.append(
            CommandStateEvent(
                state=state,
                elapsed_ms=(perf_counter() - self._started_at) * 1000,
                detail=detail,
                metadata=metadata or {},
            )
        )

    def metadata(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events]


class ObservableSafetyPolicy:
    def __init__(self, wrapped: Any, recorder: _TimelineRecorder) -> None:
        self._wrapped = wrapped
        self._recorder = recorder

    def confirm(self, action_name: str, reason: str) -> bool:
        self._recorder.add(
            "waiting_confirmation",
            action_name,
            {"reason": reason},
        )
        try:
            confirmed = bool(self._wrapped.confirm(action_name, reason))
        except Exception as exc:
            self._recorder.add("confirmation_error", action_name, {"error": str(exc)})
            raise
        self._recorder.add(
            "confirmation_resolved",
            action_name,
            {"confirmed": confirmed},
        )
        return confirmed


class CommandSession:
    """Execute one Jarvis command with state timeline and audit logging."""

    def __init__(
        self,
        *,
        router: Any,
        audit: AuditLogger | None = None,
        dry_run: bool = False,
    ) -> None:
        self.router = router
        self.audit = audit
        self.dry_run = dry_run

    def execute(self, text: str, *, source: str = "unknown") -> CommandResult:
        recorder = _TimelineRecorder()
        session_id = str(uuid4())
        recorder.add("received", source)

        original_safety = getattr(self.router, "safety", None)
        local_commands = getattr(self.router, "local_commands", None)
        original_local_safety = getattr(local_commands, "safety", None)
        if original_safety is not None:
            self.router.safety = ObservableSafetyPolicy(original_safety, recorder)
            if original_local_safety is not None:
                local_commands.safety = self.router.safety

        try:
            recorder.add("thinking", "routing")
            recorder.add("executing", "router.handle")
            result = self.router.handle(text)
            recorder.add("completed" if result.ok else "failed", result.action)
        except Exception as exc:  # pragma: no cover - defensive, covered through tests
            recorder.add("failed", "router exception", {"error": str(exc)})
            result = CommandResult(False, f"Internal error: {exc}", error=str(exc))
        finally:
            if original_safety is not None:
                self.router.safety = original_safety
            if original_local_safety is not None:
                local_commands.safety = original_local_safety

        latency_ms = recorder.events[-1].elapsed_ms if recorder.events else 0.0
        result = result.with_metadata(
            metadata={
                **result.metadata,
                "session_id": session_id,
                "state_timeline": redact_sensitive_data(recorder.metadata()),
            }
        )
        result = enrich_error_metadata(result)

        if self.audit is not None:
            try:
                self.audit.log(text, result, dry_run=self.dry_run, source=source, latency_ms=latency_ms)
            except Exception:  # pragma: no cover - audit failure must not break dispatch
                logger.exception("Audit logging failed")

        return result
