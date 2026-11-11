"""Local syntax checks and explicitly approved, console-free Python test runs."""
import ast
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from uuid import uuid4

from .models import CommandResult
from .privacy import redact_sensitive_text
from .project_workspace import ProjectReader


_PYTEST_BOOT = (
    "import sys, os; "
    "gate=sys.stdin.buffer.read(1); "
    "sys.exit(125) if gate != b'G' else None; "
    "import pytest; sys.path.insert(0, os.getcwd()); "
    "sys.exit(pytest.main(['-q', '-p', 'no:cacheprovider']))"
)


class ProjectChecks:
    def __init__(self, workspace):
        self.workspace = workspace
        self.cancelled = threading.Event()
        self._lock = threading.Lock()

    def cancel(self):
        self.cancelled.set()

    @staticmethod
    def _terminate_job(job):
        import win32job
        win32job.TerminateJobObject(job, 1)
        deadline = time.monotonic() + 5
        while win32job.QueryInformationJobObject(job, win32job.JobObjectBasicAccountingInformation)["ActiveProcesses"]:
            if time.monotonic() >= deadline:
                raise RuntimeError("Owned test processes did not finish stopping.")
            time.sleep(0.02)

    def syntax(self, paths=None):
        if not self._lock.acquire(blocking=False):
            return CommandResult(False, "A project check is already running.")
        try:
            reader = ProjectReader(self.workspace, cancelled=self.cancelled.is_set)
            candidates = paths if paths is not None else (
                path for path, info, is_dir in reader._walk() if not is_dir and Path(path).suffix.casefold() in {".py", ".json"})
            checked, errors, skipped = [], [], []
            for path in candidates:
                reader.check()
                suffix = Path(path).suffix.casefold()
                if suffix not in {".py", ".json"}:
                    skipped.append(path)
                    continue
                try:
                    text = reader._text(path)
                except (OSError, ValueError):
                    reader.check()
                    skipped.append(path)
                    continue
                try:
                    if suffix == ".py":
                        ast.parse(text, filename=path)
                    else:
                        json.loads(text)
                    checked.append(path)
                except (SyntaxError, ValueError) as exc:
                    errors.append({"path": path, "line": getattr(exc, "lineno", None), "kind": type(exc).__name__})
            ok = bool(checked) and not errors and not reader.limited and not skipped
            return CommandResult(ok, f"Syntax check: {len(checked)} passed, {len(errors)} failed, {len(skipped)} skipped. "
                "No project code was executed. This is not a runtime test.", metadata={"profile": "syntax", "passed": checked,
                "errors": errors, "skipped": skipped, "limited": reader.limited, "executed": False,
                "coverage": "Eligible Python/JSON files only; excluded paths are not validated."})
        except (ValueError, OSError):
            return CommandResult(False, "Syntax check stopped or project became unavailable.", metadata={"profile": "syntax"})
        finally:
            self._lock.release()

    def pytest(self, python_path, *, confirmed=False, timeout=120):
        if not confirmed:
            return CommandResult(False, "Approve the selected Python runtime and execution of this project's tests first.")
        if not self._lock.acquire(blocking=False):
            return CommandResult(False, "A project check is already running.")
        process = None
        job = None
        output_thread = None
        bytecode_cache = None
        output = bytearray()
        truncated = [False]
        try:
            if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("Invalid check timeout.")
            root = self.workspace.path(".")
            runtime = Path(python_path)
            if (not runtime.is_absolute() or not runtime.is_file()
                    or runtime.name.casefold() not in {"python.exe", "python3.exe", "python", "python3"}):
                raise ValueError("Select a Python executable, not a command string.")
            if self.cancelled.is_set():
                raise ValueError("Check cancelled.")
            env_names = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "TEMP", "TMP", "USERPROFILE", "HOME", "APPDATA",
                         "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMDATA", "PATHEXT"}
            env = {name: value for name, value in os.environ.items() if name.upper() in env_names}
            env["PYTHONIOENCODING"] = "utf-8"
            options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {"start_new_session": True}
            # Same-size edits within one timestamp tick must not reuse old .pyc files.
            bytecode_cache = tempfile.TemporaryDirectory(prefix=".jarvis-check-", dir=root)
            process = subprocess.Popen([str(runtime), "-I", "-B", "-u", "-X", "pycache_prefix=" + bytecode_cache.name,
                "-c", _PYTEST_BOOT], cwd=root, env=env,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=False, **options)
            if os.name == "nt":
                import win32job
                job = win32job.CreateJobObject(None, "JarvisProjectCheck-" + uuid4().hex)
                info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
                info["BasicLimitInformation"]["LimitFlags"] = win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
                win32job.AssignProcessToJobObject(job, int(process._handle))
            # The child waits for this gate so tests cannot spawn descendants before job ownership.
            process.stdin.write(b"G")
            process.stdin.close()
            def drain():
                while chunk := process.stdout.read(4096):
                    remaining = max(0, 64000 - len(output))
                    output.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        truncated[0] = True
            output_thread = threading.Thread(target=drain, daemon=True, name="jarvis-project-output")
            output_thread.start()
            deadline = time.monotonic() + min(max(float(timeout), 0.1), 120)
            stopped = False
            while process.poll() is None:
                if self.cancelled.wait(0.05) or time.monotonic() >= deadline:
                    stopped = True
                    break
            if job is not None:
                self._terminate_job(job)
                job.Close()
                job = None
            elif os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if stopped and process.poll() is None:
                process.kill()
            code = process.wait(timeout=5)
            output_thread.join(timeout=5)
            text = redact_sensitive_text(output.decode("utf-8", errors="replace")).text
            if stopped or self.cancelled.is_set():
                label = "cancelled" if self.cancelled.is_set() else "timed out"
                return CommandResult(False, f"Project tests {label}.\n{text}",
                    metadata={"profile": "pytest", "exit_code": code, "interrupted": True, "executed": True})
            return CommandResult(code == 0, f"pytest exit code: {code}\n{text}", metadata={"profile": "pytest",
                "exit_code": code, "output_truncated": truncated[0], "executed": True, "passed": code == 0})
        except Exception:
            return CommandResult(False, "Project tests could not run. Check the selected Python runtime, installed pytest and process permissions.",
                metadata={"profile": "pytest", "executed": process is not None})
        finally:
            try:
                if job is not None:
                    job.Close()
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                    if process.stdin and not process.stdin.closed:
                        process.stdin.close()
                    if output_thread is not None:
                        output_thread.join(timeout=5)
                    if process.stdout:
                        process.stdout.close()
            finally:
                try:
                    if bytecode_cache is not None:
                        bytecode_cache.cleanup()
                finally:
                    self._lock.release()
