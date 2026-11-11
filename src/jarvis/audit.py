from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from threading import Lock

from .models import CommandResult
from .privacy import redact_sensitive_data, redact_sensitive_text, contains_private_content


AUDIT_LOG_PATH = Path("logs/audit.jsonl")
_WRITE_LOCK = Lock()


@dataclass(frozen=True)
class AuditRecord:
    timestamp: str
    raw_text: str
    intent: str
    action: str
    permission: str
    requires_confirmation: bool
    confirmed: bool | None
    ok: bool
    message: str
    error: str
    dry_run: bool
    source: str = "unknown"
    latency_ms: float | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class TraceFilter:
    minutes: int = 24 * 60
    limit: int = 20
    source: str = ""
    intent: str = ""
    action: str = ""
    permission: str = ""
    ok: bool | None = None
    error_type: str = ""
    recommended_action: str = ""


class AuditLogger:
    def __init__(self, path: Path = AUDIT_LOG_PATH) -> None:
        self.path = path
        self.profile_id = ""  # the active profile (profiles.py), kept with each record

    def log(
        self,
        raw_text: str,
        result: CommandResult,
        dry_run: bool,
        *,
        source: str = "unknown",
        latency_ms: float | None = None,
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        private = contains_private_content(result.metadata) or result.action.startswith("gmail_")
        omitted = "[Private content omitted from audit]"
        record = AuditRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            raw_text=omitted if private else redact_sensitive_text(raw_text).text,
            intent=result.intent,
            action=result.action,
            permission=result.permission,
            requires_confirmation=result.requires_confirmation,
            confirmed=result.confirmed,
            ok=result.ok,
            message=omitted if private else redact_sensitive_text(result.message).text,
            error=(omitted if result.error else "") if private else redact_sensitive_text(result.error).text,
            dry_run=dry_run,
            source=source,
            latency_ms=latency_ms,
            metadata=self._with_profile({"private_content": True} if private else self._safe_metadata(result.metadata)),
        )
        with _WRITE_LOCK:
            with self.path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def recent(self, minutes: int = 10, limit: int = 20) -> list[AuditRecord]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        records = [record for record in self._read_records() if self._timestamp(record) >= cutoff]
        return records[-limit:]

    def filtered(
        self,
        *,
        minutes: int = 24 * 60,
        limit: int = 20,
        source: str = "",
        intent: str = "",
        action: str = "",
        permission: str = "",
        ok: bool | None = None,
        error_type: str = "",
        recommended_action: str = "",
    ) -> list[AuditRecord]:
        trace_filter = TraceFilter(
            minutes=max(1, min(7 * 24 * 60, int(minutes))),
            limit=max(1, min(500, int(limit))),
            source=source.strip(),
            intent=intent.strip(),
            action=action.strip(),
            permission=permission.strip(),
            ok=ok,
            error_type=error_type.strip(),
            recommended_action=recommended_action.strip(),
        )
        records = self.recent(minutes=trace_filter.minutes, limit=5000)
        filtered = [record for record in records if self._matches_filter(record, trace_filter)]
        return filtered[-trace_filter.limit :]

    def summarize_recent(self, minutes: int = 10, limit: int = 20) -> str:
        records = self.recent(minutes=minutes, limit=limit)
        if not records:
            return f"I do not have recorded actions from the last {minutes} minutes."
        lines = [f"Actions from the last {minutes} minutes:"]
        for record in records:
            timestamp = datetime.fromisoformat(record.timestamp).astimezone().strftime("%H:%M")
            status = "ok" if record.ok else "failed"
            dry_run = " dry-run" if record.dry_run else ""
            message = self._compact_message(record.message)
            lines.append(f"- {timestamp} [{status}{dry_run}] {record.action}: {message}")
        return "\n".join(lines)

    def summarize_filtered(
        self,
        *,
        minutes: int = 24 * 60,
        limit: int = 20,
        source: str = "",
        intent: str = "",
        action: str = "",
        permission: str = "",
        ok: bool | None = None,
        error_type: str = "",
        recommended_action: str = "",
    ) -> str:
        records = self.filtered(
            minutes=minutes,
            limit=limit,
            source=source,
            intent=intent,
            action=action,
            permission=permission,
            ok=ok,
            error_type=error_type,
            recommended_action=recommended_action,
        )
        filters = self._filter_summary(
            TraceFilter(
                minutes=minutes,
                limit=limit,
                source=source,
                intent=intent,
                action=action,
                permission=permission,
                ok=ok,
                error_type=error_type,
                recommended_action=recommended_action,
            )
        )
        if not records:
            return f"I do not have developer traces matching {filters}."
        lines = [f"Developer traces matching {filters}:"]
        for record in records:
            timestamp = datetime.fromisoformat(record.timestamp).astimezone().strftime("%H:%M")
            status = "ok" if record.ok else "failed"
            latency = f", {record.latency_ms:.1f} ms" if record.latency_ms is not None else ""
            lines.append(
                f"- {timestamp} [{status}{latency}] {record.source} {record.intent} -> {record.action}: "
                f"{self._compact_message(record.message)}"
            )
        return "\n".join(lines)

    def latest_trace(self) -> AuditRecord | None:
        records = self._read_records()
        return records[-1] if records else None

    def summarize_latest_trace(self) -> str:
        record = self.latest_trace()
        if record is None:
            return "I do not have a developer trace yet."

        timestamp = datetime.fromisoformat(record.timestamp).astimezone().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            "Latest developer trace:",
            f"- time: {timestamp}",
            f"- source: {record.source}",
            f"- raw text: {record.raw_text}",
            f"- intent: {record.intent}",
            f"- action/tool: {record.action}",
            f"- permission: {record.permission}",
            f"- confirmation: {self._confirmation_text(record)}",
            f"- result: {'ok' if record.ok else 'failed'}",
        ]
        if record.latency_ms is not None:
            lines.append(f"- latency: {record.latency_ms:.1f} ms")
        if record.error:
            lines.append(f"- error: {record.error}")
        if record.metadata:
            error_type = record.metadata.get("error_type")
            if error_type:
                lines.append(f"- error type: {error_type}")
            recommended_action = record.metadata.get("recommended_action")
            if recommended_action:
                lines.append(f"- recommended action: {recommended_action}")
            metadata = self._compact_message(json.dumps(record.metadata, ensure_ascii=False), max_length=500)
            lines.append(f"- metadata: {metadata}")
        lines.append(f"- response: {self._compact_message(record.message, max_length=300)}")
        return "\n".join(lines)

    @staticmethod
    def _compact_message(message: str, max_length: int = 140) -> str:
        first_line = message.splitlines()[0] if message else ""
        if len(first_line) <= max_length:
            return first_line
        return f"{first_line[: max_length - 3]}..."

    def _with_profile(self, metadata: dict[str, Any] | None) -> dict[str, Any] | None:
        if not self.profile_id:
            return metadata
        return {**(metadata or {}), "profile_id": self.profile_id}

    @staticmethod
    def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        redacted = redact_sensitive_data(metadata)
        try:
            json.dumps(redacted, ensure_ascii=False)
            return redacted
        except (TypeError, ValueError):
            return {key: redact_sensitive_text(str(value)).text for key, value in redacted.items()}

    @staticmethod
    def _record_from_dict(raw: dict[str, Any]) -> AuditRecord:
        return AuditRecord(
            timestamp=str(raw.get("timestamp", "")),
            raw_text=str(raw.get("raw_text", "")),
            intent=str(raw.get("intent", "unknown")),
            action=str(raw.get("action", "unknown")),
            permission=str(raw.get("permission", "safe")),
            requires_confirmation=bool(raw.get("requires_confirmation", False)),
            confirmed=raw.get("confirmed") if raw.get("confirmed") in {True, False, None} else None,
            ok=bool(raw.get("ok", False)),
            message=str(raw.get("message", "")),
            error=str(raw.get("error", "")),
            dry_run=bool(raw.get("dry_run", False)),
            source=str(raw.get("source", "unknown")),
            latency_ms=float(raw["latency_ms"]) if raw.get("latency_ms") is not None else None,
            metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        )

    @staticmethod
    def _confirmation_text(record: AuditRecord) -> str:
        if not record.requires_confirmation:
            return "not required"
        if record.confirmed is True:
            return "confirmed"
        if record.confirmed is False:
            return "denied"
        return "required"

    def _read_records(self) -> list[AuditRecord]:
        if not self.path.exists():
            return []
        records: list[AuditRecord] = []
        with self.path.open("r", encoding="utf-8") as file:
            for line in file:
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    records.append(self._record_from_dict(raw))
                except (TypeError, ValueError):
                    continue
        return records

    @staticmethod
    def _timestamp(record: AuditRecord) -> datetime:
        try:
            timestamp = datetime.fromisoformat(record.timestamp)
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
        if timestamp.tzinfo is None:
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp

    @classmethod
    def _matches_filter(cls, record: AuditRecord, trace_filter: TraceFilter) -> bool:
        if trace_filter.ok is not None and record.ok is not trace_filter.ok:
            return False
        return (
            cls._matches_text(record.source, trace_filter.source)
            and cls._matches_text(record.intent, trace_filter.intent)
            and cls._matches_text(record.action, trace_filter.action)
            and cls._matches_text(record.permission, trace_filter.permission)
            and cls._matches_metadata(record, "error_type", trace_filter.error_type)
            and cls._matches_metadata(record, "recommended_action", trace_filter.recommended_action)
        )

    @staticmethod
    def _matches_text(value: str, query: str) -> bool:
        return not query or query.lower() in value.lower()

    @staticmethod
    def _matches_metadata(record: AuditRecord, key: str, query: str) -> bool:
        if not query:
            return True
        metadata = record.metadata or {}
        return query.lower() in str(metadata.get(key, "")).lower()

    @staticmethod
    def _filter_summary(trace_filter: TraceFilter) -> str:
        parts = [f"last {trace_filter.minutes} min"]
        if trace_filter.source:
            parts.append(f"source={trace_filter.source}")
        if trace_filter.intent:
            parts.append(f"intent={trace_filter.intent}")
        if trace_filter.action:
            parts.append(f"action={trace_filter.action}")
        if trace_filter.permission:
            parts.append(f"permission={trace_filter.permission}")
        if trace_filter.ok is not None:
            parts.append(f"status={'ok' if trace_filter.ok else 'failed'}")
        if trace_filter.error_type:
            parts.append(f"error_type={trace_filter.error_type}")
        if trace_filter.recommended_action:
            parts.append(f"recommended_action={trace_filter.recommended_action}")
        return ", ".join(parts)
