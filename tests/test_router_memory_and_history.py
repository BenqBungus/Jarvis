from __future__ import annotations

from jarvis.audit import AuditLogger
from jarvis.ai_client import JarvisAI
from jarvis.memory import ConversationMemory, LongTermMemory
from jarvis.models import CommandResult
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


def make_router(tmp_path) -> CommandRouter:
    router = CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=True),
        ai=JarvisAI(dry_run=True),
    )
    router.long_term_memory = LongTermMemory(path=tmp_path / "memory.sqlite3")
    router.audit_reader = AuditLogger(path=tmp_path / "audit.jsonl")
    return router


def test_router_remember_show_and_forget_memory(tmp_path):
    router = make_router(tmp_path)

    remembered = router.handle("jarvis запомни това любимият ми браузър е opera gx")
    shown = router.handle("jarvis какво помниш")
    forgotten = router.handle("jarvis забрави opera gx")

    assert remembered.ok
    assert remembered.intent == "memory.remember"
    assert "opera gx" in shown.message
    assert forgotten.ok
    assert "Forgot 1" in forgotten.message


def test_router_redacts_sensitive_values_before_storing_memory(tmp_path):
    router = make_router(tmp_path)

    remembered = router.handle("jarvis запомни това openai key is sk-proj-abcdefghijklmnopqrstuvwxyz123456")
    shown = router.handle("jarvis какво помниш")

    assert remembered.ok
    assert remembered.metadata["privacy_redacted"] is True
    assert remembered.metadata["privacy_findings"] == ["openai_api_key"]
    assert "sk-proj-" not in remembered.message
    assert "[REDACTED_SECRET]" in remembered.message
    assert "sk-proj-" not in shown.message
    assert "[REDACTED_SECRET]" in shown.message


def test_router_redacts_sensitive_values_in_conversation_history(tmp_path):
    router = make_router(tmp_path)
    router.conversation_memory = ConversationMemory(path=tmp_path / "conversation.jsonl")

    result = router.handle("jarvis скучно ми е password: hunter2")
    history = router.conversation_memory.recent(limit=4)

    assert result.ok
    assert history
    assert "hunter2" not in history[0].content
    assert "[REDACTED_SECRET]" in history[0].content


def test_router_remembers_with_category_and_updates_memory(tmp_path):
    router = make_router(tmp_path)

    remembered = router.handle("jarvis запомни като preference любимият ми браузър е chrome")
    updated = router.handle(f"jarvis промени памет {remembered.metadata['memory_id']} на любимият ми браузър е opera gx")
    moved = router.handle(f"jarvis сложи памет {remembered.metadata['memory_id']} в категория website")
    shown = router.handle("jarvis какво помниш opera gx")

    assert remembered.ok
    assert remembered.intent == "memory.remember_categorized"
    assert remembered.metadata["memory_category"] == "preference"
    assert updated.ok
    assert updated.intent == "memory.update"
    assert moved.ok
    assert moved.intent == "memory.set_category"
    assert moved.metadata["memory_category"] == "website"
    assert "opera gx" in shown.message


def test_router_lists_memory_categories(tmp_path):
    router = make_router(tmp_path)
    router.long_term_memory.remember("Favorite game is Minecraft", category="game")

    result = router.handle("jarvis покажи категории памет")

    assert result.ok
    assert result.intent == "memory.categories"
    assert result.action == "list_memory_categories"
    assert result.metadata["memory_categories"]["game"] == 1


def test_router_action_history_reads_audit_log(tmp_path):
    router = make_router(tmp_path)
    router.audit_reader.log(
        "jarvis отвори facebook",
        CommandResult(True, "Would open https://www.facebook.com", action="open_url"),
        dry_run=True,
    )

    result = router.handle("jarvis какво направи през последните 10 минути")

    assert result.ok
    assert result.intent == "developer.action_history"
    assert "open_url" in result.message
    assert result.metadata["action_history_count"] == 1


def test_router_latest_trace_reads_audit_log(tmp_path):
    router = make_router(tmp_path)
    router.audit_reader.log(
        "jarvis отвори facebook",
        CommandResult(
            True,
            "Would open https://www.facebook.com",
            intent="apps_or_web.open",
            action="open_url",
            metadata={"tool": "open_url"},
        ),
        dry_run=True,
        source="cli",
        latency_ms=9.5,
    )

    result = router.handle("jarvis покажи последния trace")

    assert result.ok
    assert result.intent == "developer.latest_trace"
    assert "Latest developer trace" in result.message
    assert "apps_or_web.open" in result.message
    assert result.metadata["trace_action"] == "open_url"


def test_router_filters_developer_traces(tmp_path):
    router = make_router(tmp_path)
    router.audit_reader.log(
        "jarvis отвори facebook",
        CommandResult(True, "Opened", intent="apps_or_web.open", action="open_url", permission="safe"),
        dry_run=True,
        source="cli",
        latency_ms=3.0,
    )
    router.audit_reader.log(
        "jarvis спри интернета",
        CommandResult(False, "Cancelled", intent="network.disable_internet", action="disable_internet", permission="admin"),
        dry_run=True,
        source="gui",
        latency_ms=4.0,
    )

    result = router.handle("jarvis покажи trace action open_url")

    assert result.ok
    assert result.intent == "developer.trace_filter"
    assert result.action == "filtered_developer_traces"
    assert result.metadata["trace_filter_count"] == 1
    assert result.metadata["traces"][0]["action"] == "open_url"


def test_router_filters_developer_traces_by_error_type_shortcut(tmp_path):
    router = make_router(tmp_path)
    router.audit_reader.log(
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
        latency_ms=3.0,
    )
    router.audit_reader.log(
        "jarvis отвори missing app",
        CommandResult(
            False,
            "Not found",
            intent="apps.open",
            action="open_application",
            metadata={"error_type": "not_found", "recommended_action": "ask_for_another_target_or_search_again"},
        ),
        dry_run=True,
        source="cli",
        latency_ms=4.0,
    )

    result = router.handle("jarvis покажи blocked errors")

    assert result.ok
    assert result.intent == "developer.trace_filter"
    assert result.metadata["trace_filter"]["error_type"] == "blocked_action"
    assert result.metadata["trace_filter_count"] == 1
    assert result.metadata["traces"][0]["metadata"]["error_type"] == "blocked_action"
