from __future__ import annotations

import builtins

from jarvis.intent_parser import ParsedIntent
from jarvis.models import CommandResult
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.tool_registry import ToolCall
from jarvis.windows_actions import WindowsActions
from jarvis.workflows import AdaptiveWorkflowDecision


class FakeAdaptiveAI:
    dry_run = False

    def __init__(self, decisions: list[AdaptiveWorkflowDecision]) -> None:
        self.decisions = list(decisions)
        self.previous_lengths: list[int] = []

    def decide_next_workflow_step(self, _goal, _registry, previous_steps, history=None):
        self.previous_lengths.append(len(previous_steps))
        return self.decisions.pop(0)

    def plan_workflow(self, *_args, **_kwargs):
        from jarvis.workflows import WorkflowPlan

        return WorkflowPlan(name="none", steps=[], error="No planned workflow.")

    def parse_intent(self, *_args, **_kwargs):
        return ParsedIntent(kind="unknown")

    def answer_conversation(self, message, history=None):
        return CommandResult(True, f"chat: {message}")

    def answer_with_web_search(self, question):
        return CommandResult(True, f"web: {question}")


def make_router(decisions: list[AdaptiveWorkflowDecision], auto_confirm: bool = True) -> tuple[CommandRouter, FakeAdaptiveAI]:
    ai = FakeAdaptiveAI(decisions)
    router = CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=auto_confirm),
        ai=ai,
    )
    return router, ai


def test_router_adaptive_workflow_can_finish_after_tool_result():
    router, ai = make_router(
        [
            AdaptiveWorkflowDecision("tool_call", "Open Facebook", ToolCall("open_url", {"url": "https://facebook.com"})),
            AdaptiveWorkflowDecision("finish", message="Done."),
        ]
    )

    result = router.handle("jarvis адаптивно отвори facebook и после реши дали е готово")

    assert result.ok
    assert result.intent == "llm.adaptive_workflow"
    assert result.metadata["adaptive_workflow"] is True
    assert result.metadata["adaptive_goal"] == "отвори facebook и после реши дали е готово"
    assert [step["tool"] for step in result.metadata["workflow_steps"]] == ["open_url"]
    assert ai.previous_lengths == [0, 1]


def test_adaptive_goals_preserve_url_case_and_bypass_single_intent_parser():
    router, ai = make_router([AdaptiveWorkflowDecision("finish", message="preview")])

    def unexpected(*args, **kwargs):
        raise AssertionError("Explicit agent goals should not use the single-intent parser")

    ai.parse_intent = unexpected
    result = router.handle("Jarvis Agent Mode read https://example.com/SomePath?Token=ABC")
    assert result.metadata["adaptive_goal"] == "read https://example.com/SomePath?Token=ABC"


def test_router_adaptive_workflow_confirmation_can_cancel(monkeypatch):
    router, _ai = make_router(
        [AdaptiveWorkflowDecision("tool_call", "Disable internet", ToolCall("disable_internet"))],
        auto_confirm=False,
    )
    monkeypatch.setattr(builtins, "input", lambda _: "NO")

    result = router.handle("jarvis adaptive mode make a careful network change")

    assert not result.ok
    assert result.intent == "llm.adaptive_workflow"
    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.metadata["workflow_steps"][0]["tool"] == "disable_internet"
