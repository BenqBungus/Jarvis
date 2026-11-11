from __future__ import annotations

from jarvis.error_taxonomy import classify_error, enrich_error_metadata
from jarvis.models import CommandResult


def test_classify_error_detects_missing_argument():
    result = CommandResult(False, "Missing required tool arguments: url")

    classification = classify_error(result)

    assert classification["error_type"] == "missing_argument"
    assert classification["recommended_action"] == "ask_for_missing_argument"
    assert classification["retryable"] is False


def test_enrich_error_metadata_does_not_overwrite_existing_error_type():
    result = CommandResult(False, "failed", metadata={"error_type": "custom"})

    enriched = enrich_error_metadata(result)

    assert enriched.metadata == {"error_type": "custom"}


def test_classify_error_detects_transient_failure():
    result = CommandResult(False, "Network timeout while reading source")

    classification = classify_error(result)

    assert classification["error_type"] == "transient_external_failure"
    assert classification["recommended_action"] == "retry_or_try_alternative_source"
    assert classification["retryable"] is True
