from __future__ import annotations

import builtins

from jarvis.intent_parser import ParsedIntent
from jarvis.models import CommandResult
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.tool_registry import ToolCall
from jarvis.windows_actions import WindowsActions
from jarvis.workflows import WorkflowPlan, WorkflowStep


class FakePlannerAI:
    dry_run = False

    def __init__(self, plan: WorkflowPlan) -> None:
        self.plan = plan

    def plan_workflow(self, _message, _registry, history=None):
        return self.plan

    def parse_intent(self, _message, _registry, history=None):
        return ParsedIntent(kind="unknown")

    def answer_conversation(self, message, history=None):
        return CommandResult(True, f"chat: {message}")

    def answer_with_web_search(self, question):
        return CommandResult(True, f"web: {question}")


def make_router(plan: WorkflowPlan, auto_confirm: bool = True) -> CommandRouter:
    return CommandRouter(
        actions=WindowsActions(dry_run=True),
        safety=SafetyPolicy(auto_confirm=auto_confirm),
        ai=FakePlannerAI(plan),
    )


def test_router_executes_ai_planned_safe_workflow():
    router = make_router(
        WorkflowPlan(
            name="open_and_remember",
            reason="Open a page and remember the preference.",
            steps=[
                WorkflowStep("Open Facebook", ToolCall("open_url", {"url": "https://facebook.com"})),
                WorkflowStep("Remember preference", ToolCall("remember", {"content": "User likes Facebook shortcuts"})),
            ],
        )
    )

    result = router.handle("jarvis провери facebook и запомни че го ползвам често")

    assert result.ok
    assert result.intent == "llm.workflow"
    assert result.action == "open_and_remember"
    assert result.metadata["workflow_reason"] == "Open a page and remember the preference."
    assert result.metadata["workflow_requires_approval"] is False
    assert result.metadata["workflow_planner_metadata"] == {}
    assert [step["tool"] for step in result.metadata["workflow_steps"]] == ["open_url", "remember"]


def test_router_preserves_workflow_planner_metadata():
    router = make_router(
        WorkflowPlan(
            name="open_page",
            steps=[WorkflowStep("Open page", ToolCall("open_url", {"url": "https://example.com"}))],
            reason="Planner trace demo.",
            metadata={"ai_trace": {"model": "gpt-test", "usage": {"total_tokens": 9}}},
        )
    )

    result = router.handle("jarvis провери example и запомни че е готово")

    assert result.ok
    assert result.metadata["workflow_planner_metadata"]["ai_trace"]["model"] == "gpt-test"
    assert result.metadata["workflow_planner_metadata"]["ai_trace"]["usage"]["total_tokens"] == 9


def test_router_planned_workflow_plan_approval_can_cancel_before_steps(monkeypatch):
    router = make_router(
        WorkflowPlan(
            name="network_change",
            reason="Disable internet.",
            steps=[WorkflowStep("Disable internet", ToolCall("disable_internet"))],
        ),
        auto_confirm=False,
    )
    monkeypatch.setattr(builtins, "input", lambda _: "NO")

    result = router.handle("jarvis провери мрежата и направи промяна")

    assert not result.ok
    assert result.intent == "llm.workflow"
    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.metadata["workflow_requires_approval"] is True
    assert result.metadata["workflow_steps"] == []


def test_router_planned_workflow_step_confirmation_can_cancel_after_plan_approval(monkeypatch):
    router = make_router(
        WorkflowPlan(
            name="network_change",
            reason="Disable internet.",
            steps=[WorkflowStep("Disable internet", ToolCall("disable_internet"))],
        ),
        auto_confirm=False,
    )
    answers = iter(["YES", "NO"])
    monkeypatch.setattr(builtins, "input", lambda _: next(answers))

    result = router.handle("jarvis провери мрежата и направи промяна")

    assert not result.ok
    assert result.intent == "llm.workflow"
    assert result.requires_confirmation is True
    assert result.confirmed is False
    assert result.metadata["workflow_requires_approval"] is True
    assert result.metadata["workflow_steps"][0]["tool"] == "disable_internet"


def test_router_ignores_failed_planner_and_falls_back_to_conversation():
    router = make_router(WorkflowPlan(name="unknown", steps=[], error="No safe plan."))

    result = router.handle("jarvis скучно ми е и не знам какво да правя")

    assert result.ok
    assert result.intent == "conversation.chat"
