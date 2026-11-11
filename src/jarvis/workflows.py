from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from time import perf_counter
from threading import Event
from typing import Any

from .models import CommandResult
from .permissions import ADMIN, BLOCKED, CONFIRM, SAFE
from .privacy import redact_sensitive_text
from .tool_registry import ToolCall, ToolRegistry, ToolSpec, validate_tool_arguments


ConfirmationCallback = Callable[[ToolSpec, ToolCall], bool]
AdaptiveDecisionCallback = Callable[[list["WorkflowStepResult"]], "AdaptiveWorkflowDecision"]


@dataclass(frozen=True)
class WorkflowStep:
    title: str
    tool_call: ToolCall


@dataclass(frozen=True)
class WorkflowPlan:
    name: str
    steps: list[WorkflowStep]
    reason: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.steps)


@dataclass(frozen=True)
class AdaptiveWorkflowDecision:
    action: str
    title: str = ""
    tool_call: ToolCall | None = None
    message: str = ""
    reason: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error and self.action in {"tool_call", "finish", "abort"}


@dataclass(frozen=True)
class WorkflowPlanPreview:
    name: str
    lines: list[str]
    requires_approval: bool
    highest_permission: str
    step_count: int
    risky_tools: list[str]

    def to_message(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True)
class WorkflowStepResult:
    title: str
    tool: str
    ok: bool
    message: str
    permission: str
    requires_confirmation: bool
    latency_ms: float
    arguments: dict[str, Any] = field(default_factory=dict)
    result_metadata: dict[str, Any] = field(default_factory=dict)
    attempts: int = 1


class WorkflowRunner:
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry
        self.cancelled = Event()
        self.on_progress: Callable[[str], None] | None = None
        self.on_step_result: Callable[[ToolCall, CommandResult, float], None] | None = None

    def _announce(self, message: str) -> None:
        if self.on_progress:
            self.on_progress(redact_sensitive_text(message).text[:300])

    def _authorize(self, spec: ToolSpec, call: ToolCall, confirm) -> CommandResult | None:
        if spec.category == "agent":
            return CommandResult(False, "Nested autonomous tasks are not allowed.")
        if spec.permission == BLOCKED or spec.permission not in {SAFE, ADMIN, CONFIRM}:
            return CommandResult(False, f"Workflow blocked tool: {spec.name}.", permission=BLOCKED)
        if self.cancelled.is_set():
            return self._cancel_result()
        if spec.requires_confirmation or spec.permission in {ADMIN, CONFIRM}:
            if confirm is None or not confirm(spec, call):
                return CommandResult(False, f"Workflow cancelled at {spec.name}.", requires_confirmation=True)
        if self.cancelled.is_set():
            return self._cancel_result()
        return None

    @staticmethod
    def _cancel_result() -> CommandResult:
        return CommandResult(False, "Task stopped. Completed actions have not been undone.",
                             metadata={"cancelled": True})

    def run(
        self,
        name: str,
        steps: list[WorkflowStep],
        *,
        confirm: ConfirmationCallback | None = None,
        max_retries: int = 0,
        retryable_tools: set[str] | frozenset[str] | None = None,
    ) -> CommandResult:
        results: list[WorkflowStepResult] = []

        for step in steps:
            if self.cancelled.is_set():
                return self._finish(name, results, self._cancel_result())
            registered = self.registry.get(step.tool_call.name)
            if registered is None:
                return self._finish(
                    name,
                    results,
                    CommandResult(False, f"Workflow stopped: unknown tool {step.tool_call.name}."),
                )

            spec = registered.spec
            denied = self._authorize(spec, step.tool_call, confirm)
            if denied:
                results.append(
                    WorkflowStepResult(
                        title=step.title,
                        tool=spec.name,
                        ok=False,
                        message=denied.message,
                        permission=spec.permission,
                        requires_confirmation=True,
                        latency_ms=0,
                        arguments=step.tool_call.arguments,
                        result_metadata={},
                    )
                )
                return self._finish(name, results, denied)

            self._announce(f"Step {len(results) + 1}: {step.title}")
            result, latency_ms, attempts = self._execute_with_retries(
                spec,
                step.tool_call,
                max_retries=max_retries,
                retryable_tools=retryable_tools,
            )
            recovery = {}
            if not result.ok:
                recovery = self._recovery_hint(
                    spec,
                    step.tool_call,
                    result,
                    attempts=attempts,
                    max_retries=max_retries,
                    retryable_tools=retryable_tools,
                )
                result = result.with_metadata(metadata={**result.metadata, "workflow_recovery": recovery})
            results.append(
                WorkflowStepResult(
                    title=step.title,
                    tool=spec.name,
                    ok=result.ok,
                    message=result.message,
                    permission=spec.permission,
                    requires_confirmation=spec.requires_confirmation or spec.permission in {ADMIN, CONFIRM},
                    latency_ms=latency_ms,
                    arguments=step.tool_call.arguments,
                    result_metadata=result.metadata,
                    attempts=attempts,
                )
            )
            if not result.ok:
                return self._finish(
                    name,
                    results,
                    CommandResult(
                        False,
                        f"Workflow stopped at {spec.name}: {result.message}",
                        metadata={"workflow_recovery": recovery},
                    ),
                )

        return self._finish(name, results, self._cancel_result() if self.cancelled.is_set()
                            else CommandResult(True, f"Workflow complete: {name}"))

    def run_adaptive(
        self,
        name: str,
        goal: str,
        *,
        decide_next: AdaptiveDecisionCallback,
        confirm: ConfirmationCallback | None = None,
        max_steps: int = 5,
        max_retries: int = 0,
        retryable_tools: set[str] | frozenset[str] | None = None,
        recover_safe_failures: bool = False,
        max_seconds: float = 180,
        preview: bool = False,
    ) -> CommandResult:
        results: list[WorkflowStepResult] = []
        decisions: list[dict[str, Any]] = []
        deadline = perf_counter() + max_seconds

        for _ in range(max_steps):
            if self.cancelled.is_set():
                return self._finish_adaptive(name, goal, decisions, results, self._cancel_result())
            if perf_counter() >= deadline:
                break
            self._announce(f"Planning step {len(results) + 1}")
            try:
                decision = decide_next(results)
            except Exception as exc:
                return self._finish_adaptive(name, goal, decisions, results,
                    CommandResult(False, "Planning failed: " + redact_sensitive_text(str(exc)).text))
            if self.cancelled.is_set():
                return self._finish_adaptive(name, goal, decisions, results, self._cancel_result())
            if perf_counter() >= deadline:
                break
            decisions.append(
                {
                    "action": decision.action,
                    "title": decision.title,
                    "tool": decision.tool_call.name if decision.tool_call else None,
                    "arguments": decision.tool_call.arguments if decision.tool_call else {},
                    "message": decision.message,
                    "reason": decision.reason,
                    "error": decision.error,
                    "decision_metadata": decision.metadata,
                }
            )
            if not decision.ok:
                return self._finish_adaptive(
                    name,
                    goal,
                    decisions,
                    results,
                    CommandResult(False, decision.error or "Adaptive workflow returned an invalid decision."),
                )
            if decision.action == "finish":
                if not results and not preview:
                    return self._finish_adaptive(name, goal, decisions, results,
                        CommandResult(False, "No actions or observations were recorded. The task is not verified.",
                                      metadata={"completion_verified": False, "missing_evidence": True}))
                return self._finish_adaptive(
                    name,
                    goal,
                    decisions,
                    results,
                    CommandResult(False, "The last step failed; the goal has not been verified.")
                    if results and not results[-1].ok else
                    CommandResult(True, ("Dry-run preview: " if preview else "") +
                                  (decision.message or f"Adaptive workflow complete: {name}"),
                                  metadata={"dry_run": preview}),
                )
            if decision.action == "abort":
                return self._finish_adaptive(
                    name,
                    goal,
                    decisions,
                    results,
                    CommandResult(False, decision.message or f"Adaptive workflow aborted: {name}"),
                )
            if decision.tool_call is None:
                return self._finish_adaptive(
                    name,
                    goal,
                    decisions,
                    results,
                    CommandResult(False, "Adaptive workflow asked for a tool call without a tool."),
                )

            registered = self.registry.get(decision.tool_call.name)
            if registered is None:
                return self._finish_adaptive(
                    name,
                    goal,
                    decisions,
                    results,
                    CommandResult(False, f"Adaptive workflow stopped: unknown tool {decision.tool_call.name}."),
                )

            spec = registered.spec
            if any(not step.ok and step.tool == spec.name and step.arguments == decision.tool_call.arguments
                   for step in results):
                return self._finish_adaptive(name, goal, decisions, results,
                    CommandResult(False, "Stopped a repeated failed action. Choose another approach."))
            denied = self._authorize(spec, decision.tool_call, confirm)
            if denied:
                results.append(
                    WorkflowStepResult(
                        title=decision.title or f"Run {spec.name}",
                        tool=spec.name,
                        ok=False,
                        message=denied.message,
                        permission=spec.permission,
                        requires_confirmation=True,
                        latency_ms=0,
                        arguments=decision.tool_call.arguments,
                        result_metadata={},
                    )
                )
                return self._finish_adaptive(
                    name,
                    goal,
                    decisions,
                    results,
                    denied,
                )

            self._announce(f"Step {len(results) + 1}: {decision.title or spec.name}")
            result, latency_ms, attempts = self._execute_with_retries(
                spec,
                decision.tool_call,
                max_retries=max_retries,
                retryable_tools=retryable_tools,
                deadline=deadline,
            )
            recovery = {}
            if not result.ok:
                recovery = self._recovery_hint(
                    spec,
                    decision.tool_call,
                    result,
                    attempts=attempts,
                    max_retries=max_retries,
                    retryable_tools=retryable_tools,
                )
                result = result.with_metadata(metadata={**result.metadata, "workflow_recovery": recovery})
            results.append(
                WorkflowStepResult(
                    title=decision.title or f"Run {spec.name}",
                    tool=spec.name,
                    ok=result.ok,
                    message=result.message,
                    permission=spec.permission,
                    requires_confirmation=spec.requires_confirmation or spec.permission in {ADMIN, CONFIRM},
                    latency_ms=latency_ms,
                    arguments=decision.tool_call.arguments,
                    result_metadata=result.metadata,
                    attempts=attempts,
                )
            )
            if not result.ok:
                if (recover_safe_failures and spec.permission == SAFE and not spec.requires_confirmation
                        and spec.name in (retryable_tools or ()) and not result.metadata.get("outcome_uncertain")
                        and not result.metadata.get("cancelled") and not result.metadata.get("budget_exhausted")):
                    self._announce(f"{spec.name} failed; looking for an alternative")
                    continue
                return self._finish_adaptive(
                    name,
                    goal,
                    decisions,
                    results,
                    CommandResult(
                        False,
                        f"Adaptive workflow stopped at {spec.name}: {result.message}",
                        metadata={"workflow_recovery": recovery},
                    ),
                )

        return self._finish_adaptive(
            name,
            goal,
            decisions,
            results,
            self._cancel_result() if self.cancelled.is_set() else CommandResult(
                False, f"Adaptive workflow stopped at its limit ({max_steps} steps / {max_seconds:g}s).",
                metadata={"budget_exhausted": True}),
        )

    def _execute_with_retries(
        self,
        spec: ToolSpec,
        tool_call: ToolCall,
        *,
        max_retries: int,
        retryable_tools: set[str] | frozenset[str] | None,
        deadline: float | None = None,
    ) -> tuple[CommandResult, float, int]:
        retryable = retryable_tools or frozenset()
        allowed_retries = max(0, max_retries)
        if spec.permission != SAFE or spec.requires_confirmation or spec.name not in retryable:
            allowed_retries = 0

        attempts = 0
        total_latency_ms = 0.0
        while True:
            if self.cancelled.is_set():
                return self._cancel_result(), total_latency_ms, attempts
            if deadline is not None and perf_counter() >= deadline:
                return CommandResult(False, "Task time limit reached; no further tool attempt started.",
                    metadata={"budget_exhausted": True, "retryable": False}), total_latency_ms, attempts
            attempts += 1
            started_at = perf_counter()
            try:
                result = self.registry.execute(tool_call)
            except Exception as exc:
                result = CommandResult(False, "Tool failed: " + redact_sensitive_text(str(exc)).text,
                    metadata={"outcome_uncertain": spec.permission != SAFE})
            # A successful close request is not evidence that the app exited.
            if result.ok and self.completion_status(result.ok, result.metadata) == "not_verified":
                result = replace(result, ok=False,
                    message="Completion was not verified; later steps were stopped. " + result.message,
                    metadata={**result.metadata, "execution_ok": True, "outcome_uncertain": True})
            total_latency_ms += (perf_counter() - started_at) * 1000
            if spec.requires_confirmation or spec.permission in {ADMIN, CONFIRM}:
                result = result.with_metadata(requires_confirmation=True, confirmed=True)
            if self.on_step_result:
                self.on_step_result(tool_call, result.with_metadata(action=spec.name, permission=spec.permission),
                                    (perf_counter() - started_at) * 1000)
            if (result.ok or result.metadata.get("outcome_uncertain") or result.metadata.get("retryable") is False
                    or result.metadata.get("cancelled") or result.metadata.get("budget_exhausted") or attempts > allowed_retries):
                return result.with_metadata(
                    metadata={
                        **result.metadata,
                        "workflow_attempts": attempts,
                        "workflow_retried": attempts > 1,
                    }
                ), total_latency_ms, attempts

    @staticmethod
    def _recovery_hint(
        spec: ToolSpec,
        tool_call: ToolCall,
        result: CommandResult,
        *,
        attempts: int,
        max_retries: int,
        retryable_tools: set[str] | frozenset[str] | None,
    ) -> dict[str, Any]:
        retryable = retryable_tools or frozenset()
        retry_allowed = (
            max_retries > 0
            and spec.permission == SAFE
            and not spec.requires_confirmation
            and spec.name in retryable
        )
        remaining_retries = max(0, max_retries + 1 - attempts) if retry_allowed else 0
        message = result.message.lower()
        if result.metadata.get("retryable") is False or result.metadata.get("cancelled") or result.metadata.get("budget_exhausted"):
            retry_allowed = False
            remaining_retries = 0
        if result.metadata.get("outcome_uncertain"):
            recommended_action = "inspect_result_or_ask_user_do_not_repeat"
            retry_allowed = False
            remaining_retries = 0
        elif result.metadata.get("cancelled"):
            recommended_action = "stop_cancelled_task"
        elif result.metadata.get("budget_exhausted"):
            recommended_action = "report_time_limit_do_not_repeat"
        elif result.metadata.get("error_code") == "missing_arguments" or "missing required tool arguments" in message:
            recommended_action = "fix_missing_arguments"
        elif "unexpected tool arguments" in message:
            recommended_action = "remove_unexpected_arguments"
        elif result.metadata.get("error_code") == "invalid_argument_types":
            recommended_action = "fix_argument_types"
        elif spec.requires_confirmation:
            recommended_action = "ask_user_for_confirmation"
        elif retry_allowed and remaining_retries <= 0:
            recommended_action = "try_alternative_tool_or_report_failure"
        elif spec.category in {"browser", "internet", "research", "shopping"}:
            recommended_action = "try_alternative_source_or_query"
        else:
            recommended_action = "report_failure_to_user"

        return {
            "failed_tool": spec.name,
            "tool_category": spec.category,
            "permission": spec.permission,
            "requires_confirmation": spec.requires_confirmation,
            "arguments": tool_call.arguments,
            "attempts": attempts,
            "retry_allowed": retry_allowed,
            "retry_exhausted": retry_allowed and remaining_retries == 0,
            "remaining_retries": remaining_retries,
            "recommended_action": recommended_action,
            "result_message": result.message,
        }

    @staticmethod
    def completion_status(ok: bool, metadata: dict) -> str:
        if metadata.get("dry_run") is True:
            return "dry_run"
        flags = [metadata[key] for key in ("completion_verified", "exit_verified", "window_closed") if key in metadata]
        if metadata.get("outcome_uncertain") or any(flag is not True for flag in flags):
            return "not_verified"
        if not ok:
            return "failed"
        if flags:
            return "verified"
        if metadata.get("verification") == "launch_request_accepted":
            return "request_accepted"
        return "reported"

    @classmethod
    def _finish(cls, name: str, results: list[WorkflowStepResult], result: CommandResult) -> CommandResult:
        lines = [result.message]
        for index, step_result in enumerate(results, start=1):
            status = "ok" if step_result.ok else "failed"
            lines.append(f"{index}. [{status}] {step_result.title}: {step_result.message}")
        metadata = {
            **result.metadata,
            "workflow": name,
            "completion_evidence": [
                {"step": index, "tool": item.tool,
                 "status": cls.completion_status(item.ok, item.result_metadata),
                 "scope": item.result_metadata.get("verification_scope", "")}
                for index, item in enumerate(results, start=1)
            ],
            "workflow_steps": [
                {
                    "title": item.title,
                    "tool": item.tool,
                    "ok": item.ok,
                    "message": item.message,
                    "permission": item.permission,
                    "requires_confirmation": item.requires_confirmation,
                    "latency_ms": item.latency_ms,
                    "arguments": item.arguments,
                    "result_metadata": item.result_metadata,
                    "attempts": item.attempts,
                }
                for item in results
            ],
        }
        if results:
            for flag in ("cancelled", "budget_exhausted", "outcome_uncertain"):
                if results[-1].result_metadata.get(flag) is True:
                    metadata[flag] = True
        return CommandResult(
            result.ok,
            "\n".join(lines),
            intent=result.intent,
            action=result.action,
            permission=result.permission,
            requires_confirmation=result.requires_confirmation,
            confirmed=result.confirmed,
            error=result.error,
            metadata={
                **metadata,
            },
        )

    @classmethod
    def _finish_adaptive(
        cls,
        name: str,
        goal: str,
        decisions: list[dict[str, Any]],
        results: list[WorkflowStepResult],
        result: CommandResult,
    ) -> CommandResult:
        finished = cls._finish(name, results, result)
        return finished.with_metadata(
            metadata={
                **finished.metadata,
                "adaptive_workflow": True,
                "adaptive_goal": goal,
                "adaptive_decisions": decisions,
            }
        )


def preview_workflow_plan(plan: WorkflowPlan, registry: ToolRegistry) -> WorkflowPlanPreview:
    lines = [f"Workflow plan: {plan.name}"]
    if plan.reason:
        lines.append(f"Reason: {plan.reason}")

    risky_tools: list[str] = []
    permissions: list[str] = []
    for index, step in enumerate(plan.steps, start=1):
        registered = registry.get(step.tool_call.name)
        if registered is None:
            permission = "unknown"
            requires_confirmation = True
        else:
            permission = registered.spec.permission
            requires_confirmation = registered.spec.requires_confirmation
        permissions.append(permission)
        if requires_confirmation or permission in {"admin", "confirm", "blocked"}:
            risky_tools.append(step.tool_call.name)
        lines.append(
            f"{index}. {step.title} -> {step.tool_call.name} "
            f"[{permission}; confirm={requires_confirmation}] args={step.tool_call.arguments}"
        )

    highest_permission = _highest_permission(permissions)
    requires_approval = bool(risky_tools)
    if requires_approval:
        lines.append("Approval required before running this workflow.")
    return WorkflowPlanPreview(
        name=plan.name,
        lines=lines,
        requires_approval=requires_approval,
        highest_permission=highest_permission,
        step_count=len(plan.steps),
        risky_tools=risky_tools,
    )


def _highest_permission(permissions: list[str]) -> str:
    order = {"safe": 0, "admin": 1, "confirm": 2, "blocked": 3, "unknown": 3}
    if not permissions:
        return "safe"
    return max(permissions, key=lambda item: order.get(item, 3))


def workflow_plan_schema(tool_names: list[str], argument_names: list[str] | None = None) -> dict[str, Any]:
    argument_properties = {
        name: {
            "type": ["string", "integer", "boolean", "number", "null"],
            "description": f"Argument value for {name}.",
        }
        for name in sorted(set(argument_names or []))
    }
    return {
        "name": "jarvis_workflow_plan",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["name", "steps", "reason"],
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short snake_case workflow name.",
                },
                "steps": {
                    "type": "array",
                    "minItems": 0,
                    "maxItems": 5,
                    "description": "Ordered registered Jarvis tool calls.",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["title", "tool", "arguments"],
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "Short user-facing step title.",
                            },
                            "tool": {
                                "type": "string",
                                "enum": tool_names,
                                "description": "Registered Jarvis tool name.",
                            },
                            "arguments": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": argument_properties,
                                "required": sorted(argument_properties),
                                "description": "Arguments for the selected tool.",
                            },
                        },
                    },
                },
                "reason": {
                    "type": "string",
                    "description": "Short non-private planning summary for developer mode.",
                },
            },
        },
    }


def adaptive_workflow_decision_schema(tool_names: list[str], argument_names: list[str] | None = None) -> dict[str, Any]:
    argument_properties = {
        name: {
            "type": ["string", "integer", "boolean", "number", "null"],
            "description": f"Argument value for {name}.",
        }
        for name in sorted(set(argument_names or []))
    }
    return {
        "name": "jarvis_adaptive_workflow_decision",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["action", "title", "tool", "arguments", "message", "reason"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["tool_call", "finish", "abort"],
                    "description": "Choose a registered tool, finish successfully, or abort safely.",
                },
                "title": {
                    "type": "string",
                    "description": "Short user-facing title for the next step. Empty unless action is tool_call.",
                },
                "tool": {
                    "type": ["string", "null"],
                    "enum": [*tool_names, None],
                    "description": "Registered tool to call when action is tool_call, otherwise null.",
                },
                "arguments": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": argument_properties,
                    "required": sorted(argument_properties),
                    "description": "Arguments for the selected tool. Empty unless action is tool_call.",
                },
                "message": {
                    "type": "string",
                    "description": "Final/abort message, or empty for tool calls.",
                },
                "reason": {
                    "type": "string",
                    "description": "Short non-private reason for developer traces.",
                },
            },
        },
    }


def parse_adaptive_workflow_decision_json(
    payload: str | dict[str, Any],
    registry: ToolRegistry,
) -> AdaptiveWorkflowDecision:
    if isinstance(payload, str):
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            return AdaptiveWorkflowDecision(action="abort", error="Model did not return valid adaptive workflow JSON.")
    else:
        record = payload

    if not isinstance(record, dict):
        return AdaptiveWorkflowDecision(action="abort", error="Adaptive workflow payload is not an object.")

    action = str(record.get("action", "")).strip()
    if action not in {"tool_call", "finish", "abort"}:
        return AdaptiveWorkflowDecision(action="abort", error=f"Unsupported adaptive workflow action: {action}")

    title = str(record.get("title", "")).strip()
    message = str(record.get("message", "")).strip()
    reason = str(record.get("reason", "")).strip()
    if action in {"finish", "abort"}:
        return AdaptiveWorkflowDecision(action=action, title=title, message=message, reason=reason)

    tool = record.get("tool")
    tool_name = str(tool).strip() if tool is not None else ""
    registered = registry.get(tool_name)
    if registered is None:
        return AdaptiveWorkflowDecision(action="abort", error=f"Unregistered adaptive workflow tool requested: {tool_name}")

    arguments = record.get("arguments", {})
    if not isinstance(arguments, dict):
        return AdaptiveWorkflowDecision(action="abort", error="Adaptive workflow arguments must be an object.")
    arguments = {key: value for key, value in arguments.items() if value is not None}
    missing, unexpected = validate_tool_arguments(registered.spec, arguments)
    if missing:
        return AdaptiveWorkflowDecision(
            action="abort",
            error=f"Missing required adaptive workflow arguments for {tool_name}: {', '.join(missing)}",
        )
    if unexpected:
        return AdaptiveWorkflowDecision(
            action="abort",
            error=f"Unexpected adaptive workflow arguments for {tool_name}: {', '.join(unexpected)}",
        )

    return AdaptiveWorkflowDecision(
        action="tool_call",
        title=title or f"Run {tool_name}",
        tool_call=ToolCall(tool_name, arguments),
        reason=reason,
    )


def parse_workflow_plan_json(
    payload: str | dict[str, Any],
    registry: ToolRegistry,
    *,
    max_steps: int = 5,
) -> WorkflowPlan:
    if isinstance(payload, str):
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            return WorkflowPlan(name="unknown", steps=[], error="Model did not return valid workflow JSON.")
    else:
        record = payload

    if not isinstance(record, dict):
        return WorkflowPlan(name="unknown", steps=[], error="Workflow payload is not an object.")

    name = str(record.get("name", "")).strip() or "planned_workflow"
    reason = str(record.get("reason", "")).strip()
    raw_steps = record.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        return WorkflowPlan(name=name, steps=[], reason=reason, error="Workflow must contain at least one step.")
    if len(raw_steps) > max_steps:
        return WorkflowPlan(name=name, steps=[], reason=reason, error=f"Workflow has too many steps; maximum is {max_steps}.")

    steps: list[WorkflowStep] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            return WorkflowPlan(name=name, steps=[], reason=reason, error=f"Step {index} is not an object.")
        tool = str(raw_step.get("tool", "")).strip()
        registered = registry.get(tool)
        if registered is None:
            return WorkflowPlan(name=name, steps=[], reason=reason, error=f"Step {index} requested unregistered tool: {tool}")
        arguments = raw_step.get("arguments", {})
        if not isinstance(arguments, dict):
            return WorkflowPlan(name=name, steps=[], reason=reason, error=f"Step {index} arguments must be an object.")
        arguments = {key: value for key, value in arguments.items() if value is not None}
        missing, unexpected = validate_tool_arguments(registered.spec, arguments)
        if missing:
            return WorkflowPlan(
                name=name,
                steps=[],
                reason=reason,
                error=f"Step {index} is missing required arguments for {tool}: {', '.join(missing)}",
            )
        if unexpected:
            return WorkflowPlan(
                name=name,
                steps=[],
                reason=reason,
                error=f"Step {index} has unexpected arguments for {tool}: {', '.join(unexpected)}",
            )
        title = str(raw_step.get("title", "")).strip() or f"Run {tool}"
        steps.append(WorkflowStep(title, ToolCall(tool, arguments)))

    return WorkflowPlan(name=name, steps=steps, reason=reason)
