from __future__ import annotations

from jarvis.models import CommandResult
from jarvis.permissions import CONFIRM
from jarvis.tool_registry import ToolCall, ToolParameter, ToolRegistry, ToolSpec
from jarvis.workflows import (
    AdaptiveWorkflowDecision,
    WorkflowPlan,
    WorkflowRunner,
    WorkflowStep,
    adaptive_workflow_decision_schema,
    parse_adaptive_workflow_decision_json,
    parse_workflow_plan_json,
    preview_workflow_plan,
    workflow_plan_schema,
)


def test_workflow_runner_executes_steps_in_order():
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec("one", "First."),
        lambda: calls.append("one") or CommandResult(True, "one done", metadata={"url": "https://example.com"}),
    )
    registry.register(ToolSpec("two", "Second."), lambda: calls.append("two") or CommandResult(True, "two done"))

    result = WorkflowRunner(registry).run(
        "demo",
        [
            WorkflowStep("Step one", ToolCall("one")),
            WorkflowStep("Step two", ToolCall("two")),
        ],
    )

    assert result.ok
    assert calls == ["one", "two"]
    assert result.metadata["workflow"] == "demo"
    assert [step["tool"] for step in result.metadata["workflow_steps"]] == ["one", "two"]
    assert result.metadata["workflow_steps"][0]["result_metadata"]["url"] == "https://example.com"


def test_workflow_runner_stops_on_failure():
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(ToolSpec("fail", "Fails."), lambda: calls.append("fail") or CommandResult(False, "nope"))
    registry.register(ToolSpec("later", "Later."), lambda: calls.append("later") or CommandResult(True, "later"))

    result = WorkflowRunner(registry).run(
        "demo",
        [
            WorkflowStep("Fail", ToolCall("fail")),
            WorkflowStep("Later", ToolCall("later")),
        ],
    )

    assert not result.ok
    assert calls == ["fail"]
    assert "Workflow stopped" in result.message


def test_workflow_runner_adds_recovery_metadata_on_failure():
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec("flaky_source", "Flaky source.", category="browser"),
        lambda: calls.append("flaky_source") or CommandResult(False, "temporary source failure"),
    )

    result = WorkflowRunner(registry).run(
        "demo",
        [WorkflowStep("Read source", ToolCall("flaky_source"))],
        max_retries=1,
        retryable_tools={"flaky_source"},
    )

    recovery = result.metadata["workflow_recovery"]
    step = result.metadata["workflow_steps"][0]
    assert not result.ok
    assert calls == ["flaky_source", "flaky_source"]
    assert recovery["failed_tool"] == "flaky_source"
    assert recovery["attempts"] == 2
    assert recovery["retry_exhausted"] is True
    assert recovery["recommended_action"] == "try_alternative_tool_or_report_failure"
    assert step["result_metadata"]["workflow_recovery"] == recovery


def test_workflow_runner_recovery_metadata_identifies_argument_failure():
    registry = ToolRegistry()
    registry.register(
        ToolSpec("open_url", "Open URL.", parameters=(ToolParameter("url", "string", "URL."),)),
        lambda url: CommandResult(True, f"opened {url}"),
    )

    result = WorkflowRunner(registry).run("demo", [WorkflowStep("Open", ToolCall("open_url"))])

    recovery = result.metadata["workflow_recovery"]
    assert not result.ok
    assert recovery["failed_tool"] == "open_url"
    assert recovery["recommended_action"] == "fix_missing_arguments"
    assert recovery["retry_allowed"] is False


def test_workflow_runner_retries_allowlisted_safe_step_once():
    calls: list[str] = []
    registry = ToolRegistry()

    def flaky() -> CommandResult:
        calls.append("flaky")
        if len(calls) == 1:
            return CommandResult(False, "temporary failure")
        return CommandResult(True, "recovered")

    registry.register(ToolSpec("flaky", "Flaky safe tool."), flaky)

    result = WorkflowRunner(registry).run(
        "demo",
        [WorkflowStep("Flaky", ToolCall("flaky"))],
        max_retries=1,
        retryable_tools={"flaky"},
    )

    assert result.ok
    assert calls == ["flaky", "flaky"]
    assert result.metadata["workflow_steps"][0]["attempts"] == 2
    assert result.metadata["workflow_steps"][0]["result_metadata"]["workflow_retried"] is True


def test_workflow_runner_does_not_retry_unlisted_safe_step():
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(ToolSpec("fail", "Fails."), lambda: calls.append("fail") or CommandResult(False, "nope"))

    result = WorkflowRunner(registry).run(
        "demo",
        [WorkflowStep("Fail", ToolCall("fail"))],
        max_retries=1,
        retryable_tools={"other"},
    )

    assert not result.ok
    assert calls == ["fail"]
    assert result.metadata["workflow_steps"][0]["attempts"] == 1
    assert result.metadata["workflow_steps"][0]["result_metadata"]["workflow_retried"] is False


def test_workflow_runner_does_not_retry_confirmation_step():
    calls: list[str] = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec("danger", "Danger.", permission=CONFIRM, requires_confirmation=True),
        lambda: calls.append("danger") or CommandResult(False, "nope"),
    )

    result = WorkflowRunner(registry).run(
        "demo",
        [WorkflowStep("Danger", ToolCall("danger"))],
        confirm=lambda _spec, _call: True,
        max_retries=2,
        retryable_tools={"danger"},
    )

    assert not result.ok
    assert calls == ["danger"]
    assert result.metadata["workflow_steps"][0]["attempts"] == 1


def test_workflow_runner_requires_confirmation_for_confirm_step():
    registry = ToolRegistry()
    registry.register(ToolSpec("danger", "Danger.", permission=CONFIRM, requires_confirmation=True), lambda: CommandResult(True, "done"))

    result = WorkflowRunner(registry).run("demo", [WorkflowStep("Danger", ToolCall("danger"))], confirm=lambda _spec, _call: False)

    assert not result.ok
    assert result.metadata["workflow_steps"][0]["requires_confirmation"] is True


def test_parse_workflow_plan_json_accepts_registered_steps():
    registry = ToolRegistry()
    registry.register(ToolSpec("open_url", "Open URL."), lambda: CommandResult(True, "opened"))

    plan = parse_workflow_plan_json(
        {
            "name": "open_site",
            "steps": [{"title": "Open site", "tool": "open_url", "arguments": {}}],
            "reason": "User asked for a simple workflow.",
        },
        registry,
    )

    assert plan.ok
    assert plan.name == "open_site"
    assert plan.steps[0].tool_call.name == "open_url"


def test_parse_workflow_plan_json_rejects_unregistered_tool():
    plan = parse_workflow_plan_json(
        {
            "name": "bad",
            "steps": [{"title": "Run shell", "tool": "run_shell", "arguments": {}}],
            "reason": "Bad.",
        },
        ToolRegistry(),
    )

    assert not plan.ok
    assert "unregistered" in plan.error.lower()


def test_parse_workflow_plan_json_rejects_unexpected_arguments():
    registry = ToolRegistry()
    registry.register(ToolSpec("safe", "Safe."), lambda: CommandResult(True, "ok"))

    plan = parse_workflow_plan_json(
        {
            "name": "bad_args",
            "steps": [{"title": "Safe", "tool": "safe", "arguments": {"extra": "no"}}],
            "reason": "Bad argument.",
        },
        registry,
    )

    assert not plan.ok
    assert "unexpected" in plan.error.lower()


def test_parse_workflow_plan_json_rejects_missing_required_arguments():
    registry = ToolRegistry()
    registry.register(
        ToolSpec("open_url", "Open URL.", parameters=(ToolParameter("url", "string", "URL."),)),
        lambda url: CommandResult(True, f"opened {url}"),
    )

    plan = parse_workflow_plan_json(
        {
            "name": "bad_args",
            "steps": [{"title": "Open", "tool": "open_url", "arguments": {}}],
            "reason": "Missing URL.",
        },
        registry,
    )

    assert not plan.ok
    assert "missing required" in plan.error.lower()
    assert "url" in plan.error


def test_parse_workflow_plan_json_rejects_blank_required_arguments():
    registry = ToolRegistry()
    registry.register(
        ToolSpec("open_url", "Open URL.", parameters=(ToolParameter("url", "string", "URL."),)),
        lambda url: CommandResult(True, f"opened {url}"),
    )

    plan = parse_workflow_plan_json(
        {
            "name": "bad_args",
            "steps": [{"title": "Open", "tool": "open_url", "arguments": {"url": "  "}}],
            "reason": "Blank URL.",
        },
        registry,
    )

    assert not plan.ok
    assert "missing required" in plan.error.lower()
    assert "url" in plan.error


def test_workflow_plan_schema_limits_tools_and_argument_names():
    schema = workflow_plan_schema(["open_url"], ["url"])
    step_schema = schema["schema"]["properties"]["steps"]["items"]

    assert step_schema["properties"]["tool"]["enum"] == ["open_url"]
    assert "url" in step_schema["properties"]["arguments"]["properties"]
    assert step_schema["properties"]["arguments"]["additionalProperties"] is False


def test_preview_workflow_plan_flags_risky_steps():
    registry = ToolRegistry()
    registry.register(ToolSpec("open_url", "Open URL."), lambda: CommandResult(True, "opened"))
    registry.register(
        ToolSpec("restart", "Restart.", permission=CONFIRM, requires_confirmation=True),
        lambda: CommandResult(True, "restarted"),
    )

    preview = preview_workflow_plan(
        WorkflowPlan(
            name="mixed",
            steps=[
                WorkflowStep("Open", ToolCall("open_url")),
                WorkflowStep("Restart", ToolCall("restart")),
            ],
            reason="Demo.",
        ),
        registry,
    )

    assert preview.requires_approval is True
    assert preview.highest_permission == CONFIRM
    assert preview.risky_tools == ["restart"]
    assert "Approval required" in preview.to_message()


def test_preview_workflow_plan_allows_safe_steps_without_approval():
    registry = ToolRegistry()
    registry.register(ToolSpec("open_url", "Open URL."), lambda: CommandResult(True, "opened"))

    preview = preview_workflow_plan(
        WorkflowPlan(name="safe", steps=[WorkflowStep("Open", ToolCall("open_url"))]),
        registry,
    )

    assert preview.requires_approval is False
    assert preview.highest_permission == "safe"


def test_parse_adaptive_workflow_decision_accepts_tool_call():
    registry = ToolRegistry()
    registry.register(ToolSpec("open_url", "Open URL."), lambda: CommandResult(True, "opened"))

    decision = parse_adaptive_workflow_decision_json(
        {
            "action": "tool_call",
            "title": "Open site",
            "tool": "open_url",
            "arguments": {},
            "message": "",
            "reason": "Need to open the page.",
        },
        registry,
    )

    assert decision.ok
    assert decision.tool_call == ToolCall("open_url", {})


def test_parse_adaptive_workflow_decision_rejects_unregistered_tool():
    decision = parse_adaptive_workflow_decision_json(
        {
            "action": "tool_call",
            "title": "Run shell",
            "tool": "run_shell",
            "arguments": {},
            "message": "",
            "reason": "Bad.",
        },
        ToolRegistry(),
    )

    assert not decision.ok
    assert "unregistered" in decision.error.lower()


def test_parse_adaptive_workflow_decision_rejects_missing_required_arguments():
    registry = ToolRegistry()
    registry.register(
        ToolSpec("open_url", "Open URL.", parameters=(ToolParameter("url", "string", "URL."),)),
        lambda url: CommandResult(True, f"opened {url}"),
    )

    decision = parse_adaptive_workflow_decision_json(
        {
            "action": "tool_call",
            "title": "Open site",
            "tool": "open_url",
            "arguments": {},
            "message": "",
            "reason": "Missing URL.",
        },
        registry,
    )

    assert not decision.ok
    assert "missing required" in decision.error.lower()
    assert "url" in decision.error


def test_parse_adaptive_workflow_decision_rejects_blank_required_arguments():
    registry = ToolRegistry()
    registry.register(
        ToolSpec("open_url", "Open URL.", parameters=(ToolParameter("url", "string", "URL."),)),
        lambda url: CommandResult(True, f"opened {url}"),
    )

    decision = parse_adaptive_workflow_decision_json(
        {
            "action": "tool_call",
            "title": "Open site",
            "tool": "open_url",
            "arguments": {"url": "  "},
            "message": "",
            "reason": "Blank URL.",
        },
        registry,
    )

    assert not decision.ok
    assert "missing required" in decision.error.lower()
    assert "url" in decision.error


def test_adaptive_workflow_decision_schema_limits_tools():
    schema = adaptive_workflow_decision_schema(["open_url"], ["url"])

    assert schema["schema"]["properties"]["tool"]["enum"] == ["open_url", None]
    assert "url" in schema["schema"]["properties"]["arguments"]["properties"]


def test_adaptive_workflow_runner_uses_previous_results_to_continue():
    registry = ToolRegistry()
    registry.register(ToolSpec("one", "First."), lambda: CommandResult(True, "one done"))
    registry.register(ToolSpec("two", "Second."), lambda: CommandResult(True, "two done"))

    def decide(previous_steps):
        if not previous_steps:
            return AdaptiveWorkflowDecision("tool_call", "First", ToolCall("one"))
        if len(previous_steps) == 1:
            return AdaptiveWorkflowDecision("tool_call", "Second", ToolCall("two"))
        return AdaptiveWorkflowDecision("finish", message="done")

    result = WorkflowRunner(registry).run_adaptive("adaptive", "demo", decide_next=decide)

    assert result.ok
    assert result.metadata["adaptive_workflow"] is True
    assert [step["tool"] for step in result.metadata["workflow_steps"]] == ["one", "two"]
    assert result.metadata["adaptive_decisions"][-1]["action"] == "finish"


def test_adaptive_workflow_runner_adds_recovery_metadata_on_failure():
    registry = ToolRegistry()
    registry.register(ToolSpec("source", "Source.", category="research"), lambda: CommandResult(False, "source failed"))

    result = WorkflowRunner(registry).run_adaptive(
        "adaptive",
        "research",
        decide_next=lambda _previous_steps: AdaptiveWorkflowDecision("tool_call", "Read source", ToolCall("source")),
        max_retries=1,
        retryable_tools={"source"},
    )

    recovery = result.metadata["workflow_recovery"]
    assert not result.ok
    assert result.metadata["adaptive_workflow"] is True
    assert recovery["failed_tool"] == "source"
    assert recovery["retry_exhausted"] is True
    assert result.metadata["workflow_steps"][0]["result_metadata"]["workflow_recovery"] == recovery
