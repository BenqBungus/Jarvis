from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .tool_registry import ToolCall, ToolRegistry


INTENT_KINDS = ("tool_call", "conversation", "web_answer", "unknown")


@dataclass(frozen=True)
class ParsedIntent:
    kind: str
    tool: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    reason: str = ""
    confidence: float = 1.0
    clarification_question: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_tool_call(self) -> bool:
        return self.kind == "tool_call" and bool(self.tool)

    def to_tool_call(self) -> ToolCall | None:
        if not self.is_tool_call or self.tool is None:
            return None
        return ToolCall(name=self.tool, arguments=self.arguments)


def intent_schema(tool_names: list[str], argument_names: list[str] | None = None) -> dict[str, Any]:
    argument_properties = {
        name: {
            "type": ["string", "integer", "boolean", "number", "null"],
            "description": f"Argument value for {name}.",
        }
        for name in sorted(set(argument_names or []))
    }
    return {
        "name": "jarvis_intent",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "tool", "arguments", "message", "reason", "confidence", "clarification_question"],
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": list(INTENT_KINDS),
                    "description": "Whether the user wants a tool action, web-backed answer, normal conversation, or an unknown unsupported action.",
                },
                "tool": {
                    "type": ["string", "null"],
                    "enum": [*tool_names, None],
                    "description": "Registered Jarvis tool name for tool_call, otherwise null.",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments for the selected tool. Empty object unless kind is tool_call.",
                    "additionalProperties": False,
                    "properties": argument_properties,
                },
                "message": {
                    "type": "string",
                    "description": "Conversation text or clarified user request. Empty string for direct tool calls.",
                },
                "reason": {
                    "type": "string",
                    "description": "Short non-private routing summary for developer mode.",
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Confidence that the selected kind/tool is what the user intended. Use lower values for ambiguous or underspecified requests.",
                },
                "clarification_question": {
                    "type": "string",
                    "description": "A short question to ask before acting when the request is ambiguous. Empty string when no clarification is needed.",
                },
            },
        },
    }


def parse_intent_json(payload: str | dict[str, Any], registry: ToolRegistry) -> ParsedIntent:
    if isinstance(payload, str):
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            return ParsedIntent(kind="unknown", reason="Model did not return valid JSON.")
    else:
        record = payload

    if not isinstance(record, dict):
        return ParsedIntent(kind="unknown", reason="Intent payload is not an object.")

    kind = str(record.get("kind", "unknown")).strip()
    if kind not in INTENT_KINDS:
        return ParsedIntent(kind="unknown", reason=f"Unsupported intent kind: {kind}")

    tool = record.get("tool")
    tool_name = str(tool).strip() if tool is not None else None
    if kind == "tool_call":
        if not tool_name:
            return ParsedIntent(kind="unknown", reason="Tool call intent did not include a tool.")
        if registry.get(tool_name) is None:
            return ParsedIntent(kind="unknown", reason=f"Unregistered tool requested: {tool_name}")
    else:
        tool_name = None

    arguments = record.get("arguments", {})
    if not isinstance(arguments, dict):
        return ParsedIntent(kind="unknown", reason="Tool arguments must be an object.")

    message = str(record.get("message", "")).strip()
    reason = str(record.get("reason", "")).strip()
    confidence = _coerce_confidence(record.get("confidence", 1.0))
    clarification_question = str(record.get("clarification_question", "")).strip()
    return ParsedIntent(
        kind=kind,
        tool=tool_name,
        arguments=arguments,
        message=message,
        reason=reason,
        confidence=confidence,
        clarification_question=clarification_question,
    )


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, confidence))
