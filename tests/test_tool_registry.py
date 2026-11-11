from __future__ import annotations

from jarvis.models import CommandResult
from jarvis.audit import AuditLogger
from jarvis.browser import BrowserController, PageReader, SearchResult, WebResearcher
from jarvis.memory import ConversationMemory, EpisodicMemory, LongTermMemory, SemanticMemorySearch
from jarvis.permissions import ADMIN, CONFIRM, SAFE
from jarvis.tool_registry import ToolCall, ToolParameter, ToolRegistry, ToolSpec, build_core_tool_registry
from jarvis.windows_actions import WindowsActions
from jarvis.web_context import WebCandidate, WebContext


def test_tool_spec_exports_json_schema():
    spec = ToolSpec(
        name="set_volume",
        description="Set volume.",
        permission=SAFE,
        category="system",
        parameters=(ToolParameter("percent", "integer", "Volume percent."),),
    )

    schema = spec.to_json_schema()

    assert schema["name"] == "set_volume"
    assert schema["parameters"]["required"] == ["percent"]
    assert schema["metadata"]["permission"] == SAFE
    assert schema["metadata"]["requires_confirmation"] is False


def test_registry_rejects_missing_and_unexpected_arguments():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="demo",
            description="Demo tool.",
            parameters=(ToolParameter("value", "string", "Value."),),
        ),
        lambda value: CommandResult(True, value),
    )

    missing = registry.execute(ToolCall("demo"))
    blank = registry.execute(ToolCall("demo", {"value": "  "}))
    none_value = registry.execute(ToolCall("demo", {"value": None}))
    unexpected = registry.execute(ToolCall("demo", {"value": "ok", "extra": "no"}))

    assert not missing.ok
    assert "missing" in missing.message.lower()
    assert not blank.ok
    assert "missing" in blank.message.lower()
    assert not none_value.ok
    assert "missing" in none_value.message.lower()
    assert not unexpected.ok
    assert "unexpected" in unexpected.message.lower()


def test_core_registry_contains_permissioned_backend_tools():
    registry = build_core_tool_registry(WindowsActions(dry_run=True))
    specs = {spec.name: spec for spec in registry.list_specs()}

    assert specs["open_url"].permission == SAFE
    assert specs["voice_diagnostics"].permission == SAFE
    assert specs["voice_diagnostics"].category == "voice"
    assert specs["check_driver_updates"].permission == ADMIN
    assert specs["cleanup_temp_files"].permission == CONFIRM
    assert specs["restart"].permission == CONFIRM
    assert specs["disable_internet"].requires_confirmation is True


def test_core_registry_executes_dry_run_tool():
    registry = build_core_tool_registry(WindowsActions(dry_run=True))
    result = registry.execute(ToolCall("set_volume", {"percent": 30}))

    assert result.ok
    assert "30" in result.message
    assert result.action == "set_volume"
    assert result.metadata["tool"] == "set_volume"


def test_core_registry_executes_voice_diagnostics_tool(monkeypatch):
    from jarvis.audio import diagnostics

    monkeypatch.setattr(
        diagnostics,
        "build_voice_diagnostics",
        lambda settings=None: CommandResult(True, "Voice Doctor ready", metadata={"voice_diagnostics": {}}),
    )
    registry = build_core_tool_registry(WindowsActions(dry_run=True))

    result = registry.execute(ToolCall("voice_diagnostics"))

    assert result.ok
    assert "Voice Doctor" in result.message
    assert result.metadata["tool"] == "voice_diagnostics"


def test_core_registry_can_expose_memory_tools(tmp_path):
    memory = LongTermMemory(path=tmp_path / "memory.sqlite3")
    registry = build_core_tool_registry(WindowsActions(dry_run=True), memory=memory)
    specs = {spec.name: spec for spec in registry.list_specs()}

    assert "remember" in specs
    assert "search_memory" in specs
    remembered = registry.execute(ToolCall("remember", {"content": "Call me Berk"}))
    found = registry.execute(ToolCall("search_memory", {"query": "Berk"}))
    updated = registry.execute(
        ToolCall(
            "update_memory",
            {
                "memory_id": remembered.metadata["memory_id"],
                "content": "Call me Berk Tonchev",
                "category": "preference",
            },
        )
    )
    categories = registry.execute(ToolCall("list_memory_categories"))

    assert remembered.ok
    assert found.ok
    assert "Call me Berk" in found.message
    assert specs["update_memory"].category == "memory"
    assert specs["set_memory_category"].category == "memory"
    assert specs["list_memory_categories"].category == "memory"
    assert updated.ok
    assert updated.metadata["memory_category"] == "preference"
    assert categories.metadata["memory_categories"]["preference"] == 1


def test_core_registry_redacts_sensitive_memory_tool_values(tmp_path):
    memory = LongTermMemory(path=tmp_path / "memory.sqlite3")
    registry = build_core_tool_registry(WindowsActions(dry_run=True), memory=memory)

    result = registry.execute(ToolCall("remember", {"content": "api_key: abcdefghijk12345"}))
    found = registry.execute(ToolCall("search_memory"))

    assert result.ok
    assert result.metadata["privacy_redacted"] is True
    assert "abcdefghijk12345" not in result.message
    assert "[REDACTED_SECRET]" in result.message
    assert "abcdefghijk12345" not in found.message
    assert result.metadata["tool_arguments"]["content"] == "api_key: [REDACTED_SECRET]"


def test_core_registry_can_expose_episodic_memory_tools(tmp_path):
    conversation = ConversationMemory(path=tmp_path / "conversation.jsonl")
    conversation.add_turn("user", "Jarvis project")
    conversation.add_turn("assistant", "Added episodic memory")
    episodic = EpisodicMemory(
        path=tmp_path / "episodes.jsonl",
        state_path=tmp_path / "episodes_state.json",
        min_new_turns=2,
    )
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    audit.log(
        "jarvis отвори facebook",
        CommandResult(True, "Opened", action="open_url"),
        dry_run=True,
        source="cli",
        latency_ms=1.0,
    )
    registry = build_core_tool_registry(
        WindowsActions(dry_run=True),
        conversation_memory=conversation,
        episodic_memory=episodic,
        audit=audit,
    )
    specs = {spec.name: spec for spec in registry.list_specs()}

    created = registry.execute(ToolCall("summarize_conversation_episode", {"force": True}))
    listed = registry.execute(ToolCall("list_episode_summaries", {"query": "jarvis"}))
    actions = registry.execute(ToolCall("summarize_action_episode", {"minutes": 60}))

    assert specs["summarize_conversation_episode"].category == "memory"
    assert specs["list_episode_summaries"].category == "memory"
    assert specs["summarize_action_episode"].category == "memory"
    assert created.ok
    assert listed.ok
    assert actions.ok
    assert "Conversation episode" in listed.message
    assert actions.metadata["action_count"] == 1


def test_core_registry_can_expose_semantic_memory_search(tmp_path):
    memory = LongTermMemory(path=tmp_path / "memory.sqlite3")
    memory.remember("Preferred browser is Opera GX", category="preference", importance=5)
    semantic_memory = SemanticMemorySearch(long_term_memory=memory)
    registry = build_core_tool_registry(
        WindowsActions(dry_run=True),
        memory=memory,
        semantic_memory=semantic_memory,
    )
    specs = {spec.name: spec for spec in registry.list_specs()}

    result = registry.execute(ToolCall("semantic_memory_search", {"query": "любим браузър"}))

    assert specs["semantic_memory_search"].category == "memory"
    assert result.ok
    assert result.metadata["tool"] == "semantic_memory_search"
    assert "Preferred browser is Opera GX" in result.message


def test_core_registry_can_expose_developer_trace_tool(tmp_path):
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    registry = build_core_tool_registry(WindowsActions(dry_run=True), audit=audit)
    specs = {spec.name: spec for spec in registry.list_specs()}

    result = registry.execute(ToolCall("latest_developer_trace"))

    assert "latest_developer_trace" in specs
    assert result.ok
    assert "developer trace" in result.message.lower()


def test_core_registry_can_filter_developer_traces(tmp_path):
    audit = AuditLogger(path=tmp_path / "audit.jsonl")
    audit.log(
        "jarvis отвори facebook",
        CommandResult(True, "Opened", intent="apps_or_web.open", action="open_url"),
        dry_run=True,
        source="cli",
    )
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
    registry = build_core_tool_registry(WindowsActions(dry_run=True), audit=audit)
    specs = {spec.name: spec for spec in registry.list_specs()}

    result = registry.execute(ToolCall("filtered_developer_traces", {"action": "open_url", "ok": True}))
    error_result = registry.execute(ToolCall("filtered_developer_traces", {"error_type": "blocked_action"}))

    assert specs["filtered_developer_traces"].category == "developer"
    assert result.ok
    assert result.metadata["trace_filter_count"] == 1
    assert "open_url" in result.message
    assert error_result.ok
    assert error_result.metadata["trace_filter_count"] == 1
    assert error_result.metadata["trace_filter"]["error_type"] == "blocked_action"


def test_core_registry_can_save_deal_candidates(tmp_path):
    web_context = WebContext(path=tmp_path / "web_context.json")
    registry = build_core_tool_registry(WindowsActions(dry_run=True), web_context=web_context)

    result = registry.execute(ToolCall("save_deal_candidates", {"query": "gaming mouse"}))

    assert result.ok
    assert "Plasico" in result.message
    assert web_context.pick(1) is not None


def test_core_registry_can_expose_page_reader_tool(tmp_path):
    page_reader = PageReader(fetch_bytes=lambda *_args: b"<title>Demo</title><p>Hello page.</p>")
    web_context = WebContext(path=tmp_path / "web_context.json")
    web_context.save_candidates([WebCandidate("Demo saved", "https://example.com/saved")], query="demo")
    registry = build_core_tool_registry(WindowsActions(dry_run=True), web_context=web_context, page_reader=page_reader)
    specs = {spec.name: spec for spec in registry.list_specs()}

    result = registry.execute(ToolCall("extract_webpage", {"url": "https://example.com"}))
    saved = registry.execute(ToolCall("extract_saved_web_result_matching", {"query": "saved"}))
    web_context.record_read(url="https://example.com/second", title="Second", excerpt="Second page.", text_length=12)
    session = registry.execute(ToolCall("show_browser_session"))
    compared = registry.execute(ToolCall("compare_browser_session_pages"))
    answered = registry.execute(ToolCall("answer_browser_session_question", {"question": "saved"}))

    assert specs["extract_webpage"].category == "browser"
    assert specs["extract_saved_web_result_matching"].category == "browser"
    assert specs["show_browser_session"].category == "browser"
    assert specs["compare_browser_session_pages"].category == "browser"
    assert specs["answer_browser_session_question"].category == "browser"
    assert result.ok
    assert "Hello page" in result.message
    assert saved.ok
    assert saved.metadata["ordinal"] == 1
    assert web_context.recent_read_pages()[0].url == "https://example.com/saved"
    assert session.ok
    assert compared.ok
    assert len(compared.metadata["compared_pages"]) == 2
    assert answered.ok
    assert answered.metadata["browser_session_question"] == "saved"


def test_core_registry_uses_ai_for_browser_session_compare(tmp_path):
    class FakeAI:
        dry_run = False

        def answer_with_web_search(self, question):
            return CommandResult(True, f"web: {question}")

        def answer_conversation(self, message):
            return CommandResult(True, f"chat: {message}")

        def compare_browser_session_pages(self, pages, question="Compare these browser session pages."):
            return CommandResult(True, f"ai compared {len(pages)} pages", metadata={"ai_trace": {"operation": "browser_session_compare"}})

        def answer_browser_session_question(self, pages, question):
            return CommandResult(True, f"ai answered {question} from {len(pages)} pages", metadata={"ai_trace": {"operation": "browser_session_answer"}})

    web_context = WebContext(path=tmp_path / "web_context.json")
    web_context.save_candidates([], query="demo")
    web_context.record_read(url="https://example.com/one", title="One", excerpt="One page.", text_length=9)
    web_context.record_read(url="https://example.com/two", title="Two", excerpt="Two page.", text_length=9)
    registry = build_core_tool_registry(WindowsActions(dry_run=True), ai=FakeAI(), web_context=web_context)

    result = registry.execute(ToolCall("compare_browser_session_pages"))

    assert result.ok
    assert result.message == "ai compared 2 pages"
    assert result.metadata["browser_session_ai_compare"] is True
    assert result.metadata["ai_trace"]["operation"] == "browser_session_compare"

    answered = registry.execute(ToolCall("answer_browser_session_question", {"question": "battery"}))

    assert answered.ok
    assert answered.message == "ai answered battery from 2 pages"
    assert answered.metadata["browser_session_ai_answer"] is True
    assert answered.metadata["ai_trace"]["operation"] == "browser_session_answer"


def test_core_registry_can_expose_research_tool(tmp_path):
    class FakeSearchProvider:
        def search(self, _query: str, max_results: int = 6) -> list[SearchResult]:
            return [SearchResult("Demo result", "https://example.com/demo")][:max_results]

    page_reader = PageReader(fetch_bytes=lambda *_args: b"<title>Demo</title><p>Research evidence.</p>")
    researcher = WebResearcher(
        search_provider=FakeSearchProvider(),
        page_reader=page_reader,
        web_context=WebContext(path=tmp_path / "web_context.json"),
    )
    registry = build_core_tool_registry(WindowsActions(dry_run=True), researcher=researcher)
    specs = {spec.name: spec for spec in registry.list_specs()}

    result = registry.execute(ToolCall("research_web", {"query": "demo"}))

    assert specs["research_web"].category == "research"
    assert result.ok
    assert "Sources:" in result.message


def test_core_registry_can_expose_browser_controller_tools(tmp_path):
    class FakeSearchProvider:
        def search(self, _query: str, max_results: int = 6) -> list[SearchResult]:
            return [SearchResult("Demo result", "https://example.com/demo")][:max_results]

    browser = BrowserController(
        actions=WindowsActions(dry_run=True),
        web_context=WebContext(path=tmp_path / "web_context.json"),
        search_provider=FakeSearchProvider(),
    )
    registry = build_core_tool_registry(WindowsActions(dry_run=True), browser=browser)
    specs = {spec.name: spec for spec in registry.list_specs()}

    search_result = registry.execute(ToolCall("browser_search", {"query": "demo"}))
    open_result = registry.execute(ToolCall("browser_open_result", {"ordinal": 1}))
    open_matching = registry.execute(ToolCall("browser_open_matching_result", {"query": "demo"}))

    assert specs["browser_search"].category == "browser"
    assert specs["browser_open_result"].category == "browser"
    assert specs["browser_open_matching_result"].category == "browser"
    assert search_result.ok
    assert open_result.ok
    assert open_matching.ok
    assert "Would open https://example.com/demo" in open_result.message
    assert "Would open https://example.com/demo" in open_matching.message


def test_core_registry_can_expose_screen_vision_tools():
    class FakeScreenVision:
        def describe(self, prompt: str = "What is on my screen?") -> CommandResult:
            return CommandResult(True, f"screen: {prompt}")

        @staticmethod
        def status() -> CommandResult:
            return CommandResult(True, "ready")

    registry = build_core_tool_registry(WindowsActions(dry_run=True), screen_vision=FakeScreenVision())
    specs = {spec.name: spec for spec in registry.list_specs()}

    result = registry.execute(ToolCall("screen_describe", {"prompt": "какво гледам"}))

    assert specs["screen_describe"].category == "vision"
    assert specs["screen_describe"].permission == CONFIRM
    assert specs["screen_describe"].requires_confirmation is True
    assert result.ok
    assert "какво гледам" in result.message
