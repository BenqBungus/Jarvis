from __future__ import annotations

from jarvis.intent_parser import intent_schema, parse_intent_json
from jarvis.models import CommandResult
from jarvis.tool_registry import ToolCall, ToolParameter, ToolRegistry, ToolSpec


def make_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="open_url",
            description="Open URL.",
            parameters=(ToolParameter("url", "string", "URL."),),
        ),
        lambda url: CommandResult(True, f"opened {url}"),
    )
    return registry


def test_parse_intent_json_accepts_registered_tool_call():
    parsed = parse_intent_json(
        {
            "kind": "tool_call",
            "tool": "open_url",
            "arguments": {"url": "https://example.com"},
            "message": "",
            "reason": "User asked to open a site.",
            "confidence": 0.92,
            "clarification_question": "",
        },
        make_registry(),
    )

    assert parsed.is_tool_call
    assert parsed.to_tool_call() == ToolCall("open_url", {"url": "https://example.com"})
    assert parsed.confidence == 0.92
    assert parsed.clarification_question == ""


def test_parse_intent_json_defaults_confidence_for_older_payloads():
    parsed = parse_intent_json(
        {
            "kind": "conversation",
            "tool": None,
            "arguments": {},
            "message": "hello",
            "reason": "Old payload.",
        },
        make_registry(),
    )

    assert parsed.kind == "conversation"
    assert parsed.confidence == 1.0


def test_parse_intent_json_rejects_unregistered_tool_call():
    parsed = parse_intent_json(
        '{"kind":"tool_call","tool":"run_shell","arguments":{},"message":"","reason":"bad"}',
        make_registry(),
    )

    assert parsed.kind == "unknown"
    assert "unregistered" in parsed.reason.lower()


def test_parse_intent_json_accepts_conversation():
    parsed = parse_intent_json(
        {
            "kind": "conversation",
            "tool": None,
            "arguments": {},
            "message": "Скучно ти е; хайде да измислим нещо.",
            "reason": "Casual chat.",
        },
        make_registry(),
    )

    assert parsed.kind == "conversation"
    assert parsed.tool is None


def test_intent_schema_limits_tools_and_argument_names():
    schema = intent_schema(["open_url"], ["url"])

    assert "confidence" in schema["schema"]["required"]
    assert "clarification_question" in schema["schema"]["required"]
    assert schema["schema"]["properties"]["tool"]["enum"] == ["open_url", None]
    assert "url" in schema["schema"]["properties"]["arguments"]["properties"]
    assert schema["schema"]["properties"]["arguments"]["additionalProperties"] is False
