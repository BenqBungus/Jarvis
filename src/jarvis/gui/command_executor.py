from __future__ import annotations

import logging
import queue
import threading
import json
import time
import re
from copy import deepcopy
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from ..audit import AuditLogger
from ..config import WAKE_WORDS
from ..models import CommandResult
from ..privacy import redact_sensitive_text
from ..router import CommandRouter
from ..session import CommandSession
from ..tool_registry import ToolSpec

logger = logging.getLogger(__name__)


@dataclass
class CommandJob:
    text: str
    source: str
    reply: "queue.Queue[CommandResult] | None" = None
    tool_name: str = ""
    arguments: dict | None = None
    generation: int = 0


class CommandExecutor(QObject):
    """Serialize GUI actions; status and cancellation bypass the work queue.

    Mutating tools always use this queue and the router's confirmation gate.
    AuditLogger serializes writes from both the worker and control requests.
    """

    result_ready = Signal(str, str, object)  # source, text, CommandResult
    task_state_changed = Signal(bool, str)
    task_progress = Signal(str)
    cancellation_requested = Signal()

    def __init__(self, router: CommandRouter, audit: AuditLogger, dry_run: bool = False, parent=None) -> None:
        super().__init__(parent)
        self._router = router
        self._audit = audit
        self._dry_run = dry_run
        self._jobs: queue.Queue = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-command-executor")
        self._state_lock = threading.Lock()
        self._generation = 0
        self._stopping = False
        self._current_job: CommandJob | None = None
        self._started_at = 0.0
        self._progress = ""
        self._cancel_requested = False
        self._last_task: dict = {}
        registry = getattr(router, "tools", None)
        if registry is not None:
            registry.register(ToolSpec(
                "get_active_task_status",
                "Read the current task, latest observed step, elapsed time and cancellation state, "
                "without waiting for that task to finish. Use when asked about progress; never invent progress.",
                category="agent",
            ), self.task_status_result)
        runner = getattr(router, "workflow_runner", None)
        if runner:
            runner.on_progress = self._report_progress
            runner.on_step_result = lambda call, result, latency: self._audit.log(
                json.dumps({"tool": call.name, "arguments": call.arguments}, ensure_ascii=False),
                result, self._dry_run, source="gui_workflow_step", latency_ms=latency)

    def _report_progress(self, message: str) -> None:
        clean = redact_sensitive_text(message).text[:300]
        with self._state_lock:
            self._progress = clean
        self.task_progress.emit(clean)

    def task_status_result(self) -> CommandResult:
        with self._state_lock:
            job = self._current_job
            snapshot = {
                "active": job is not None,
                "title": self._job_title(job) if job else "",
                "tool": job.tool_name if job else "",
                "progress": self._progress if job else "",
                "elapsed_seconds": round(time.monotonic() - self._started_at, 1) if job else 0,
                "cancel_requested": self._cancel_requested if job else False,
                "queued_entries": self._jobs.qsize(),
                "last_task": deepcopy(self._last_task),
            }
        if snapshot["active"]:
            message = f"Working on {snapshot['title']} ({snapshot['elapsed_seconds']}s). {snapshot['progress']}"
            if snapshot["cancel_requested"]:
                message += " Stop requested; waiting for the current operation to return."
        elif snapshot["last_task"]:
            last = snapshot["last_task"]
            message = f"No active task. Last task: {last['title']}. {last['message']}"
        else:
            message = "No task is running or has completed in this session."
        return CommandResult(True, message, action="get_active_task_status", metadata={"task_status": snapshot})

    @staticmethod
    def _job_title(job: CommandJob) -> str:
        text = (job.arguments or {}).get("goal", job.text) if job.tool_name == "run_autonomous_task" else job.text
        return redact_sensitive_text(str(text)).text[:300]

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.cancel_pending()
        with self._state_lock:
            if not self._stopping:
                self._stopping = True
                self._jobs.put(None)

    def cancel_pending(self) -> CommandResult:
        with self._state_lock:
            self._generation += 1
            self._cancel_requested = True
            runner = getattr(self._router, "workflow_runner", None)
            if runner:
                runner.cancelled.set()
        self.task_progress.emit("Stopping after the current operation")
        self.cancellation_requested.emit()
        return CommandResult(True, "Stop requested. Completed actions are not undone.", metadata={"cancel_requested": True})

    def _enqueue(self, job: CommandJob) -> None:
        control_text = job.text.strip().casefold()
        for wake in WAKE_WORDS:
            if control_text.startswith(wake + " ") or control_text.startswith(wake + ","):
                control_text = control_text[len(wake):].lstrip(" ,")
                break
        control_text = re.sub(r"^(?:local|локално)\s*[: ]\s*", "", control_text)
        status_text = control_text.rstrip("?.!") in {"task status", "how is the task going",
                         "what are you working on", "is the task done", "are you done"}
        if job.source != "overlay_teach" and ((not job.tool_name and status_text)
                or (job.tool_name == "get_active_task_status" and not job.arguments)):
            result = self.task_status_result()
            self._audit.log(job.text, result, self._dry_run, source=f"gui_{job.source}")
            if job.reply:
                job.reply.put(result)
            self.result_ready.emit(job.source, job.text, result)
            return
        cancel_text = control_text in {"stop task", "cancel task", "stop current task", "cancel current task", "спри задачата", "отмени задачата"}
        if (job.source != "overlay_teach" and ((not job.tool_name and cancel_text)
                or (job.tool_name == "cancel_task" and not job.arguments))):
            result = self.cancel_pending()
            self._audit.log(job.text, result, self._dry_run, source=f"gui_{job.source}")
            if job.reply:
                job.reply.put(result)
            self.result_ready.emit(job.source, job.text, result)
            return
        with self._state_lock:
            if self._stopping:
                result = CommandResult(False, "Jarvis is shutting down.")
                if job.reply:
                    job.reply.put(result)
                return
            job.generation = self._generation
            self._jobs.put(job)

    def submit(self, text: str, source: str = "text") -> None:
        """Fire-and-forget from the GUI thread; result arrives via result_ready."""
        self._enqueue(CommandJob(text, source))

    def submit_tool(self, name: str, arguments: dict, source: str = "control") -> None:
        self._enqueue(CommandJob(name, source, tool_name=name, arguments=arguments))

    def submit_blocking(self, text: str, source: str = "voice") -> CommandResult:
        """Queue a command and block for its result. Safe from any thread
        except this executor's own worker thread (that would deadlock)."""
        reply: queue.Queue = queue.Queue(maxsize=1)
        self._enqueue(CommandJob(text, source, reply))
        return reply.get()

    def submit_tool_blocking(self, name: str, arguments: dict) -> dict:
        from ..realtime import _command_result_payload

        if name == "get_active_task_status":
            result = (self.task_status_result() if not arguments else
                      CommandResult(False, "get_active_task_status accepts no arguments."))
            self._audit.log(name, result, self._dry_run, source="gui_realtime")
            return _command_result_payload(result)
        if name == "cancel_task" and not arguments:
            result = self.cancel_pending()
            self._audit.log(name, result, self._dry_run, source="gui_realtime")
            return _command_result_payload(result)
        if name == "stop_screen_sharing" and not arguments:
            result = self._router.screen_sharing.stop()
            self._audit.log(name, result, self._dry_run, source="gui_realtime")
            return _command_result_payload(result)
        reply: queue.Queue = queue.Queue(maxsize=1)
        self._enqueue(CommandJob(name, "realtime", reply, name, arguments))
        return _command_result_payload(reply.get())

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            if job is None:
                browser = getattr(self._router, "browser", None)
                if browser:
                    browser.close()
                return
            with self._state_lock:
                cancelled = job.generation != self._generation
                self._current_job = job
                self._started_at = time.monotonic()
                self._progress = "Starting"
                self._cancel_requested = cancelled
                runner = getattr(self._router, "workflow_runner", None)
                if runner and not cancelled:
                    runner.cancelled.clear()
            self.task_state_changed.emit(True, redact_sensitive_text(job.text).text[:160])
            try:
                if cancelled:
                    result = CommandResult(False, "Queued command cancelled before execution.", metadata={"cancelled": True})
                    self._audit.log(job.text, result, self._dry_run, source=f"gui_{job.source}")
                elif job.tool_name:
                    from ..realtime import RealtimeVoiceSession

                    started = time.monotonic()
                    payload = RealtimeVoiceSession.tool_executor_from_router(self._router)(job.tool_name, job.arguments or {})
                    result = CommandResult(**payload)
                    if job.tool_name.startswith("gmail_"):
                        result = result.with_metadata(metadata={**result.metadata, "private_content": True})
                    self._audit.log(json.dumps({"tool": job.tool_name, "arguments": job.arguments}, ensure_ascii=False),
                                    result, self._dry_run, source=f"gui_{job.source}",
                                    latency_ms=(time.monotonic() - started) * 1000)
                elif job.source in {"overlay_local", "overlay_teach"}:
                    handler = (self._router.local_commands.handle if job.source == "overlay_local"
                               else self._router.teaching.explain)
                    started = time.monotonic()
                    result = handler(job.text)
                    self._audit.log(job.text, result, self._dry_run, source=f"gui_{job.source}",
                                    latency_ms=(time.monotonic() - started) * 1000)
                else:
                    result = CommandSession(
                        router=self._router,
                        audit=self._audit,
                        dry_run=self._dry_run,
                    ).execute(job.text, source=f"gui_{job.source}")
            except Exception as exc:  # pragma: no cover - defensive, mirrors BackgroundMonitor._run_loop
                logger.exception("Command execution failed")
                result = CommandResult(False, f"Internal error: {redact_sensitive_text(str(exc)).text}")
            with self._state_lock:
                self._last_task = {
                    "title": self._job_title(job), "ok": result.ok,
                    "message": redact_sensitive_text(result.message).text[:600],
                    "elapsed_seconds": round(time.monotonic() - self._started_at, 1),
                    "cancel_requested": self._cancel_requested,
                    "completion_evidence": self._completion_evidence(result),
                }
                self._current_job = None
            if job.reply is not None:
                job.reply.put(result)
            self.result_ready.emit(job.source, job.text, result)
            self.task_state_changed.emit(False, "Completed" if result.ok else "Stopped / failed")

    @staticmethod
    def _completion_evidence(result: CommandResult) -> list[dict]:
        from ..workflows import WorkflowRunner

        evidence = result.metadata.get("completion_evidence")
        if not isinstance(evidence, list):
            evidence = [{"tool": result.action,
                         "status": WorkflowRunner.completion_status(result.ok, result.metadata),
                         "scope": result.metadata.get("verification_scope", "")}]
        return [{key: redact_sensitive_text(str(item.get(key, ""))).text[:160]
                 for key in ("tool", "status", "scope")}
                for item in evidence[:8] if isinstance(item, dict)]
