from __future__ import annotations

import pytest

from jarvis.models import CommandResult
from jarvis.permissions import ADMIN, BLOCKED, CONFIRM
from jarvis.tool_registry import ToolCall, ToolParameter, ToolRegistry, ToolSpec
from jarvis.workflows import AdaptiveWorkflowDecision, WorkflowRunner, WorkflowStep


@pytest.mark.parametrize("adaptive", [False, True])
@pytest.mark.parametrize("permission", [ADMIN, CONFIRM, BLOCKED])
def test_permission_enforced_even_without_confirmation_flag(adaptive, permission):
    registry = ToolRegistry()
    called = []
    registry.register(ToolSpec("risky", "Risky", permission=permission),
                      lambda: called.append(True) or CommandResult(True, "done"))
    runner = WorkflowRunner(registry)
    if adaptive:
        result = runner.run_adaptive("task", "goal", decide_next=lambda steps:
            AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("risky")))
    else:
        result = runner.run("task", [WorkflowStep("Risky", ToolCall("risky"))])
    assert not result.ok
    assert called == []


def test_cancel_after_confirmation_does_not_execute():
    registry = ToolRegistry()
    called = []
    registry.register(ToolSpec("risky", "Risky", permission=CONFIRM),
                      lambda: called.append(True) or CommandResult(True, "done"))
    runner = WorkflowRunner(registry)

    def confirm(*_args):
        runner.cancelled.set()
        return True

    result = runner.run("task", [WorkflowStep("Risky", ToolCall("risky"))], confirm=confirm)
    assert not result.ok and result.metadata["cancelled"]
    assert not called


def test_adaptive_recovers_read_failure_with_a_different_tool():
    registry = ToolRegistry()
    registry.register(ToolSpec("read_one", "Read one"), lambda: CommandResult(False, "source unavailable"))
    registry.register(ToolSpec("read_two", "Read two"), lambda: CommandResult(True, "verified", metadata={"evidence": "source"}))
    decisions = iter([AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("read_one")),
                      AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("read_two")),
                      AdaptiveWorkflowDecision("finish", message="Verified from the second source")])
    result = WorkflowRunner(registry).run_adaptive("task", "goal", decide_next=lambda _: next(decisions),
        recover_safe_failures=True, retryable_tools={"read_one", "read_two"})
    assert result.ok
    assert [s["ok"] for s in result.metadata["workflow_steps"]] == [False, True]


def test_cannot_finish_successfully_after_failed_read():
    registry = ToolRegistry()
    registry.register(ToolSpec("read", "Read"), lambda: CommandResult(False, "failed"))
    result = WorkflowRunner(registry).run_adaptive("task", "goal", decide_next=lambda steps:
        AdaptiveWorkflowDecision("finish", message="done") if steps else
        AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("read")),
        recover_safe_failures=True, retryable_tools={"read"})
    assert not result.ok


def test_cancel_during_planning_prevents_next_tool():
    registry = ToolRegistry()
    called = []
    registry.register(ToolSpec("read", "Read"), lambda: called.append(True) or CommandResult(True, "done"))
    runner = WorkflowRunner(registry)

    def decide(_steps):
        runner.cancelled.set()
        return AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("read"))

    result = runner.run_adaptive("task", "goal", decide_next=decide)
    assert not result.ok and result.metadata["cancelled"]
    assert not called


def test_exceptions_and_repeated_failed_actions_stop_cleanly():
    registry = ToolRegistry()
    calls = []

    def fail():
        calls.append(True)
        raise RuntimeError("unavailable")

    registry.register(ToolSpec("read", "Read"), fail)
    result = WorkflowRunner(registry).run_adaptive("task", "goal", decide_next=lambda steps:
        AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("read")),
        recover_safe_failures=True, retryable_tools={"read"})
    assert not result.ok
    assert "repeated failed" in result.message
    assert len(calls) == 1


def test_blocked_tool_cannot_be_called_directly():
    registry = ToolRegistry()
    registry.register(ToolSpec("blocked", "Blocked", permission=BLOCKED),
                      lambda: pytest.fail("must not execute"))
    assert not registry.execute(ToolCall("blocked")).ok


def test_boolean_strings_and_boolean_integers_do_not_reach_handlers():
    registry = ToolRegistry()
    registry.register(ToolSpec("tool", "Typed", parameters=(ToolParameter("new_tab", "boolean", "Boolean"),
        ToolParameter("count", "integer", "Count"))), lambda **args: pytest.fail("must not execute"))
    assert not registry.execute(ToolCall("tool", {"new_tab": "false", "count": 2})).ok
    assert not registry.execute(ToolCall("tool", {"new_tab": True, "count": False})).ok
