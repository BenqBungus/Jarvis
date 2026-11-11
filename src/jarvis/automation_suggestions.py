from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from .audit import AuditRecord
from .privacy import redact_sensitive_data


_CANDIDATES = {"open_url", "open_nitrosense", "open_local_path", "set_volume"}


@dataclass(frozen=True)
class AutomationSuggestion:
    action: str
    arguments: dict
    count: int
    last_seen: str
    enabled: bool = False


def suggest_repetitions(records: list[AuditRecord]) -> list[dict]:
    """Observed repeats only. No scheduler, action callbacks or persistent enable state."""
    groups: dict[str, list[AuditRecord]] = {}
    for record in records:
        if not record.ok or record.dry_run or record.permission != "safe" or record.action not in _CANDIDATES:
            continue
        args = (record.metadata or {}).get("tool_arguments")
        if not isinstance(args, dict):
            continue  # Do not infer target/parameters from prose.
        key = json.dumps([record.action, args], sort_keys=True, ensure_ascii=False)
        groups.setdefault(key, []).append(record)
    suggestions = []
    for rows in groups.values():
        if len(rows) >= 3:
            latest = max(rows, key=lambda row: row.timestamp)
            suggestions.append(asdict(AutomationSuggestion(latest.action,
                redact_sensitive_data(latest.metadata["tool_arguments"]), len(rows), latest.timestamp)))
    return sorted(suggestions, key=lambda item: item["last_seen"], reverse=True)
