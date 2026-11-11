from __future__ import annotations

from typing import Any

from .models import CommandResult
from .permissions import BLOCKED, CONFIRM, ADMIN


def classify_error(result: CommandResult) -> dict[str, Any]:
    if result.ok:
        return {}
    message = (result.error or result.message).strip()
    lower = message.lower()
    metadata = result.metadata

    if metadata.get("missing_arguments") or "missing required tool arguments" in lower:
        return _classification(
            "missing_argument",
            "low",
            "ask_for_missing_argument",
            retryable=False,
            message=message,
        )
    if metadata.get("unexpected_arguments") or "unexpected tool arguments" in lower:
        return _classification(
            "unexpected_argument",
            "medium",
            "reject_and_reparse_intent",
            retryable=False,
            message=message,
        )
    if result.permission == BLOCKED or result.action == "blocked":
        return _classification(
            "blocked_action",
            "high",
            "request_safer_alternative",
            retryable=False,
            message=message,
        )
    if "cancelled" in lower or "denied" in lower:
        return _classification(
            "user_cancelled",
            "info",
            "ask_user_before_retrying",
            retryable=False,
            message=message,
        )
    if "not installed" in lower or "not configured" in lower or "api key" in lower or "dependency is missing" in lower:
        return _classification(
            "configuration_missing",
            "medium",
            "open_settings_or_install_dependency",
            retryable=False,
            message=message,
        )
    if "unknown tool" in lower or "not registered" in lower or "no longer registered" in lower:
        return _classification(
            "unregistered_tool",
            "high",
            "reject_and_use_registered_tool",
            retryable=False,
            message=message,
        )
    if "not found" in lower or "did not find" in lower or "do not have a saved" in lower or "no saved" in lower:
        return _classification(
            "not_found",
            "low",
            "ask_for_another_target_or_search_again",
            retryable=False,
            message=message,
        )
    if "timeout" in lower or "timed out" in lower or "temporary" in lower or "network" in lower:
        return _classification(
            "transient_external_failure",
            "medium",
            "retry_or_try_alternative_source",
            retryable=True,
            message=message,
        )
    if result.requires_confirmation or result.permission in {CONFIRM, ADMIN}:
        return _classification(
            "protected_action_failed",
            "medium",
            "explain_and_ask_before_retrying",
            retryable=False,
            message=message,
        )
    return _classification(
        "command_failed",
        "medium",
        "report_failure_to_user",
        retryable=False,
        message=message,
    )


def enrich_error_metadata(result: CommandResult) -> CommandResult:
    if result.ok or "error_type" in result.metadata:
        return result
    classification = classify_error(result)
    if not classification:
        return result
    return result.with_metadata(metadata={**result.metadata, **classification})


def _classification(
    error_type: str,
    severity: str,
    recommended_action: str,
    *,
    retryable: bool,
    message: str,
) -> dict[str, Any]:
    return {
        "error_type": error_type,
        "error_severity": severity,
        "recommended_action": recommended_action,
        "retryable": retryable,
        "error_message": message,
    }
