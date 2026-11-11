from __future__ import annotations

import json

from jarvis.audit import AuditLogger
from jarvis.models import CommandResult


def test_audit_log_records_trace_fields(tmp_path):
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    audit.log(
        "jarvis отвори facebook",
        CommandResult(True, "Opened Facebook", intent="apps_or_web.open", action="open_url", metadata={"tool": "open_url"}),
        dry_run=False,
        source="cli",
        latency_ms=12.5,
    )

    record = json.loads(audit.path.read_text(encoding="utf-8"))

    assert record["source"] == "cli"
    assert record["latency_ms"] == 12.5
    assert record["metadata"] == {"tool": "open_url"}


def test_audit_reader_accepts_old_records_without_trace_fields(tmp_path):
    path = tmp_path / "audit.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2099-01-01T00:00:00+00:00",
                "raw_text": "jarvis ping",
                "intent": "unknown",
                "action": "unknown",
                "permission": "safe",
                "requires_confirmation": False,
                "confirmed": None,
                "ok": True,
                "message": "pong",
                "error": "",
                "dry_run": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    record = AuditLogger(path=path).latest_trace()

    assert record is not None
    assert record.source == "unknown"
    assert record.latency_ms is None
    assert record.metadata == {}


def test_audit_log_redacts_sensitive_text_and_metadata(tmp_path):
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    audit.log(
        "jarvis remember api_key: abcdefghijk12345",
        CommandResult(
            False,
            "Failed with password: hunter2",
            error="Bearer abcdefghijklmnopqrstuvwxyz",
            metadata={"tool_arguments": {"content": "sk-proj-abcdefghijklmnopqrstuvwxyz123456"}},
        ),
        dry_run=True,
        source="cli",
    )

    record = json.loads(audit.path.read_text(encoding="utf-8"))
    serialized = json.dumps(record, ensure_ascii=False)

    assert "abcdefghijk12345" not in serialized
    assert "hunter2" not in serialized
    assert "sk-proj-" not in serialized
    assert "Bearer abcdefghijklmnopqrstuvwxyz" not in serialized
    assert "[REDACTED_SECRET]" in serialized


def test_latest_trace_summary_includes_developer_details(tmp_path):
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    audit.log(
        "jarvis покажи tools",
        CommandResult(
            True,
            "Available Jarvis tools:\n- open_url",
            intent="developer.list_tools",
            action="list_tools",
            metadata={"tools": ["open_url"]},
        ),
        dry_run=True,
        source="cli",
        latency_ms=4.2,
    )

    summary = audit.summarize_latest_trace()

    assert "Latest developer trace" in summary
    assert "developer.list_tools" in summary
    assert "4.2 ms" in summary
    assert "open_url" in summary


def test_latest_trace_summary_surfaces_error_taxonomy(tmp_path):
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    audit.log(
        "jarvis disable defender",
        CommandResult(
            False,
            "Blocked for safety.",
            intent="blocked.security_sensitive",
            action="blocked",
            permission="blocked",
            error="Blocked for safety.",
            metadata={
                "error_type": "blocked_action",
                "recommended_action": "request_safer_alternative",
            },
        ),
        dry_run=True,
        source="cli",
        latency_ms=1.0,
    )

    summary = audit.summarize_latest_trace()

    assert "error type: blocked_action" in summary
    assert "recommended action: request_safer_alternative" in summary


def test_audit_logger_filters_developer_traces(tmp_path):
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    audit.log(
        "jarvis отвори facebook",
        CommandResult(True, "Opened", intent="apps_or_web.open", action="open_url", permission="safe"),
        dry_run=True,
        source="cli",
        latency_ms=1.0,
    )
    audit.log(
        "jarvis спри интернета",
        CommandResult(False, "Cancelled", intent="network.disable_internet", action="disable_internet", permission="admin"),
        dry_run=True,
        source="gui",
        latency_ms=2.0,
    )

    by_action = audit.filtered(action="open_url")
    failed_gui = audit.filtered(source="gui", ok=False)
    summary = audit.summarize_filtered(permission="admin", ok=False)

    assert [record.action for record in by_action] == ["open_url"]
    assert [record.source for record in failed_gui] == ["gui"]
    assert "network.disable_internet" in summary
    assert "status=failed" in summary


def test_audit_logger_filters_by_error_taxonomy_metadata(tmp_path):
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    audit.log(
        "jarvis disable defender",
        CommandResult(
            False,
            "Blocked",
            intent="blocked.security_sensitive",
            action="blocked",
            metadata={"error_type": "blocked_action", "recommended_action": "request_safer_alternative"},
        ),
        dry_run=True,
        source="cli",
    )
    audit.log(
        "jarvis unknown app",
        CommandResult(
            False,
            "Not found",
            intent="apps.open",
            action="open_application",
            metadata={"error_type": "not_found", "recommended_action": "ask_for_another_target_or_search_again"},
        ),
        dry_run=True,
        source="cli",
    )

    blocked = audit.filtered(error_type="blocked_action")
    summary = audit.summarize_filtered(recommended_action="request_safer_alternative")

    assert [record.action for record in blocked] == ["blocked"]
    assert "error_type=blocked_action" in audit.summarize_filtered(error_type="blocked_action")
    assert "recommended_action=request_safer_alternative" in summary
    assert "blocked.security_sensitive" in summary
