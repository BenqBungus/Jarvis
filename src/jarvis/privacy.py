from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redacted: bool
    findings: tuple[str, ...] = ()


_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai_api_key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("generic_api_key", re.compile(r"(?i)\b(api[_ -]?key|secret[_ -]?key|access[_ -]?token)\s*[:=]\s*([^\s,;]{8,})")),
    ("password", re.compile(r"(?i)\b(password|парола)\s*[:=]\s*([^\s,;]{4,})")),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
)


def redact_sensitive_text(text: str) -> RedactionResult:
    redacted = str(text or "")
    findings: list[str] = []
    for label, pattern in _SECRET_PATTERNS:
        redacted, count = pattern.subn(lambda match: _replacement(label, match), redacted)
        if count:
            findings.append(label)
    return RedactionResult(redacted, bool(findings), tuple(dict.fromkeys(findings)))


def contains_sensitive_text(text: str) -> bool:
    return redact_sensitive_text(text).redacted


def contains_private_content(value: Any) -> bool:
    """Propagate opt-out even when private tool results are nested in a workflow."""
    if isinstance(value, dict):
        return value.get("private_content") is True or any(contains_private_content(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(contains_private_content(item) for item in value)
    return False


# Values stored under these keys are secrets whatever they look like (e.g. the
# vault_save tool's "password" argument, kept in tool_arguments metadata).
_SECRET_KEYS = frozenset({"password", "passwd", "passphrase", "парола", "pin", "secret", "client_secret", "api_key",
                          "apikey", "token", "access_token", "refresh_token"})


def redact_sensitive_data(value: Any) -> Any:
    if isinstance(value, str):
        return redact_sensitive_text(value).text
    if isinstance(value, dict):
        return {key: _redact_value(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_data(item) for item in value)
    return value


def _redact_value(key: Any, item: Any) -> Any:
    redacted = redact_sensitive_data(item)
    if isinstance(item, str) and item and redacted == item and str(key).strip().casefold() in _SECRET_KEYS:
        return "[REDACTED_SECRET]"
    return redacted


def _replacement(label: str, match: re.Match[str]) -> str:
    if label in {"generic_api_key", "password"} and match.lastindex and match.lastindex >= 1:
        return f"{match.group(1)}: [REDACTED_SECRET]"
    if label == "bearer_token":
        return "Bearer [REDACTED_SECRET]"
    return "[REDACTED_SECRET]"
