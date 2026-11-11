from unittest.mock import Mock

import pytest

from jarvis.models import CommandResult
from jarvis.tool_registry import ToolCall, ToolParameter, ToolRegistry, ToolSpec
from jarvis.workflows import AdaptiveWorkflowDecision, WorkflowRunner, WorkflowStep


@pytest.mark.parametrize("arguments,code,hint", [
    ({}, "missing_arguments", "fix_missing_arguments"),
    ({"query": "value", "extra": True}, "unexpected_arguments", "remove_unexpected_arguments"),
    ({"query": 123}, "invalid_argument_types", "fix_argument_types"),
])
def test_invalid_arguments_are_not_retried_even_for_allowlisted_tool(arguments, code, hint):
    registry = ToolRegistry()
    handler = Mock(return_value=CommandResult(True, "read"))
    registry.register(ToolSpec("read", "Read", parameters=(ToolParameter("query", "string", "Query"),)), handler)
    result = WorkflowRunner(registry).run("read", [WorkflowStep("read", ToolCall("read", arguments))],
        max_retries=3, retryable_tools={"read"})
    handler.assert_not_called()
    assert not result.ok
    step = result.metadata["workflow_steps"][0]
    assert step["attempts"] == 1 and step["result_metadata"]["error_code"] == code
    assert step["result_metadata"]["executed"] is False
    assert result.metadata["workflow_recovery"]["recommended_action"] == hint
    assert not result.metadata["workflow_recovery"]["retry_allowed"]


def test_adaptive_can_fix_arguments_without_repeating_the_invalid_call():
    registry = ToolRegistry()
    handler = Mock(return_value=CommandResult(True, "Observed fixture result"))
    registry.register(ToolSpec("read", "Read", parameters=(ToolParameter("query", "string", "Query"),)), handler)
    def decide(results):
        if not results:
            return AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("read", {"query": 123}))
        if len(results) == 1:
            assert results[0].attempts == 1
            assert results[0].result_metadata["workflow_recovery"]["recommended_action"] == "fix_argument_types"
            return AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("read", {"query": "fixture"}))
        return AdaptiveWorkflowDecision("finish", message="Fixture observed")
    result = WorkflowRunner(registry).run_adaptive("read", "read fixture", decide_next=decide,
        max_retries=3, retryable_tools={"read"}, recover_safe_failures=True)
    assert result.ok
    handler.assert_called_once_with(query="fixture")


def test_retry_obeys_remaining_adaptive_time_budget(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("jarvis.workflows.perf_counter", lambda: clock[0])
    registry = ToolRegistry()
    def slow_failure():
        clock[0] = 2.0
        return CommandResult(False, "Temporary fixture failure")
    handler = Mock(side_effect=slow_failure)
    registry.register(ToolSpec("read", "Read"), handler)
    decide = Mock(return_value=AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("read")))
    runner = WorkflowRunner(registry)
    audit = Mock()
    runner.on_step_result = audit
    result = runner.run_adaptive("read", "read", decide_next=decide, max_seconds=1,
        max_retries=3, retryable_tools={"read"}, recover_safe_failures=True)
    assert not result.ok
    assert result.metadata["budget_exhausted"]
    handler.assert_called_once()
    decide.assert_called_once()
    audit.assert_called_once()
    recovery = result.metadata["workflow_recovery"]
    assert recovery["recommended_action"] == "report_time_limit_do_not_repeat"
    assert not recovery["retry_allowed"] and recovery["attempts"] == 1


@pytest.mark.parametrize("metadata", [{"retryable": False}, {"cancelled": True}, {"budget_exhausted": True}])
def test_explicit_stop_flags_prevent_retry(metadata):
    registry = ToolRegistry()
    handler = Mock(return_value=CommandResult(False, "Fixture stopped", metadata=metadata))
    registry.register(ToolSpec("read", "Read"), handler)
    result = WorkflowRunner(registry).run("read", [WorkflowStep("read", ToolCall("read"))],
        max_retries=5, retryable_tools={"read"})
    assert not result.ok
    handler.assert_called_once()
    assert not result.metadata["workflow_recovery"]["retry_allowed"]


def test_cancelled_tool_result_cannot_trigger_alternative_planning():
    registry = ToolRegistry()
    registry.register(ToolSpec("read", "Read"), lambda: CommandResult(False, "Stopped", metadata={"cancelled": True}))
    decide = Mock(return_value=AdaptiveWorkflowDecision("tool_call", tool_call=ToolCall("read")))
    result = WorkflowRunner(registry).run_adaptive("read", "read", decide_next=decide,
        max_retries=2, retryable_tools={"read"}, recover_safe_failures=True)
    assert not result.ok
    decide.assert_called_once()
    assert result.metadata["cancelled"]
    assert result.metadata["workflow_recovery"]["recommended_action"] == "stop_cancelled_task"
