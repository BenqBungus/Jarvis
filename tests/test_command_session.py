from __future__ import annotations

import json

from jarvis.audit import AuditLogger
from jarvis.models import CommandResult
from jarvis.session import CommandSession


class FakeSafety:
    def __init__(self, confirmed: bool = True) -> None:
        self.confirmed = confirmed

    def confirm(self, _action_name: str, _reason: str) -> bool:
        return self.confirmed


class FakeRouter:
    def __init__(self, *, needs_confirmation: bool = False, raises: bool = False, secret_confirmation: bool = False) -> None:
        self.safety = FakeSafety()
        self.needs_confirmation = needs_confirmation
        self.raises = raises
        self.secret_confirmation = secret_confirmation

    def handle(self, text: str) -> CommandResult:
        if self.raises:
            raise RuntimeError("boom")
        if self.needs_confirmation:
            reason = "api_key: abcdefghijk12345" if self.secret_confirmation else "Testing confirmation."
            confirmed = self.safety.confirm("Danger", reason)
            return CommandResult(
                confirmed,
                "confirmed" if confirmed else "cancelled",
                action="danger",
                requires_confirmation=True,
                confirmed=confirmed,
            )
        return CommandResult(True, f"handled: {text}", action="demo")


def test_command_session_adds_state_timeline_and_audits(tmp_path):
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    result = CommandSession(router=FakeRouter(), audit=audit, dry_run=True).execute("jarvis ping", source="test")

    assert result.ok
    assert result.metadata["session_id"]
    assert [event["state"] for event in result.metadata["state_timeline"]] == [
        "received",
        "thinking",
        "executing",
        "completed",
    ]

    record = json.loads(audit.path.read_text(encoding="utf-8"))
    assert record["source"] == "test"
    assert record["metadata"]["session_id"] == result.metadata["session_id"]
    assert record["metadata"]["state_timeline"][0]["state"] == "received"


def test_command_session_records_confirmation_states():
    result = CommandSession(router=FakeRouter(needs_confirmation=True), dry_run=True).execute("danger", source="test")

    states = [event["state"] for event in result.metadata["state_timeline"]]
    assert "waiting_confirmation" in states
    assert "confirmation_resolved" in states
    assert result.confirmed is True


def test_command_session_redacts_sensitive_confirmation_timeline_metadata():
    result = CommandSession(router=FakeRouter(needs_confirmation=True, secret_confirmation=True), dry_run=True).execute("danger", source="test")

    serialized = json.dumps(result.metadata["state_timeline"], ensure_ascii=False)
    assert "abcdefghijk12345" not in serialized
    assert "[REDACTED_SECRET]" in serialized


def test_command_session_restores_router_safety_after_execution():
    router = FakeRouter(needs_confirmation=True)
    original_safety = router.safety

    CommandSession(router=router, dry_run=True).execute("danger", source="test")

    assert router.safety is original_safety


def test_command_session_turns_router_exception_into_failed_result():
    result = CommandSession(router=FakeRouter(raises=True), dry_run=True).execute("boom", source="test")

    assert not result.ok
    assert "Internal error" in result.message
    assert result.metadata["error_type"] == "command_failed"
    assert result.metadata["recommended_action"] == "report_failure_to_user"
    assert result.metadata["state_timeline"][-1]["state"] == "failed"
