from __future__ import annotations

import os
import subprocess
import sys
from types import SimpleNamespace

import psutil
import pytest

from jarvis.process_control import ProcessControl
from jarvis.realtime import RealtimeVoiceSession, realtime_tool_schemas
from jarvis.router import CommandRouter
from jarvis.windows_actions import WindowsActions


class Process:
    def __init__(self, pid, root, name="demo.exe"):
        self.pid, self.root, self.label = pid, root, name
        self.created, self.owner, self.running = 10.0, "local-user", True
        self.stops = 0
        self.wait_error = None
        self.arguments = [name]

    def name(self): return self.label
    def exe(self): return str(self.root / self.label)
    def cmdline(self): return self.arguments
    def username(self): return self.owner
    def parents(self): return []
    def memory_info(self): return SimpleNamespace(rss=1024**2)
    def create_time(self): return self.created
    def is_running(self): return self.running
    def terminate(self): self.stops += 1
    def wait(self, timeout):
        assert timeout == 3
        if self.wait_error:
            raise self.wait_error


@pytest.fixture
def processes(monkeypatch, tmp_path):
    current, app = Process(100, tmp_path, "python.exe"), Process(200, tmp_path)
    monkeypatch.setattr(psutil, "Process", lambda pid=None: current if pid is None or pid == 100 else app)
    monkeypatch.setattr(psutil, "process_iter", lambda: iter([current, app]))
    monkeypatch.setattr("jarvis.process_control._window_pids", lambda: {100, 200})
    monkeypatch.setattr("jarvis.process_control._is_critical", lambda pid: False)
    monkeypatch.setattr("jarvis.process_control._service_pids", lambda: set())
    return current, app


def select(control):
    result = control.list_processes("demo")
    assert result.ok
    return result.metadata["processes"][0]["selection_id"]


def test_exact_observed_process_is_ended_once_and_exit_is_verified(processes):
    control = ProcessControl()
    selection = select(control)
    result = control.end_process(selection)
    assert result.ok and result.metadata["exit_verified"]
    assert processes[1].stops == 1
    assert not control.end_process(selection).ok
    assert processes[1].stops == 1


def test_dry_run_does_not_terminate(processes):
    control = ProcessControl(dry_run=True)
    result = control.end_process(select(control))
    assert result.ok and "Would" in result.message
    assert processes[1].stops == 0


@pytest.mark.parametrize("change", ["expired", "pid_reused", "exited", "different_owner", "different_exe", "hidden", "critical"])
@pytest.mark.parametrize("method", ["end_process", "close_app"])
def test_stale_or_unsafe_selection_does_not_stop_anything(processes, monkeypatch, change, method):
    app = processes[1]
    control = ProcessControl()
    selection = select(control)
    if change == "expired":
        monkeypatch.setattr("jarvis.process_control.time.monotonic", lambda: float("inf"))
    elif change == "pid_reused": app.created += 1
    elif change == "exited": app.running = False
    elif change == "different_owner": app.owner = "SYSTEM"
    elif change == "different_exe": app.root = app.root / "other"
    elif change == "hidden": monkeypatch.setattr("jarvis.process_control._window_pids", lambda: set())
    elif change == "critical": monkeypatch.setattr("jarvis.process_control._is_critical", lambda pid: True)
    allowed_background = change == "hidden" and method == "end_process"
    assert getattr(control, method)(selection).ok is allowed_background
    assert app.stops == int(allowed_background)


@pytest.mark.parametrize("name", ["lsass.exe", "msmpeng.exe", "explorer.exe", "Jarvis.exe"])
def test_system_security_and_jarvis_names_are_read_only(processes, name):
    processes[1].label = name
    rows = ProcessControl().list_processes(name).metadata["processes"]
    assert rows and "selection_id" not in rows[0]
    assert "protected" in rows[0]["blocked_reason"]


def test_jarvis_module_and_parent_processes_are_protected(processes):
    current, app = processes
    app.arguments = ["pythonw.exe", "-m", "jarvis", "--gui"]
    row = ProcessControl().list_processes("demo").metadata["processes"][0]
    assert "selection_id" not in row
    app.arguments = ["demo.exe"]
    current.parents = lambda: [app]
    row = ProcessControl().list_processes("demo").metadata["processes"][0]
    assert "selection_id" not in row


def test_uncertain_exit_is_not_reported_as_success(processes):
    control = ProcessControl()
    selection = select(control)
    processes[1].wait_error = psutil.TimeoutExpired(3)
    result = control.end_process(selection)
    assert not result.ok and result.metadata["stop_requested"]
    assert result.metadata["exit_verified"] is False
    assert processes[1].stops == 1


def test_failed_safety_inspection_fails_closed(processes, monkeypatch):
    def denied(pid): raise OSError("access denied")
    monkeypatch.setattr("jarvis.process_control._is_critical", denied)
    row = ProcessControl().list_processes("demo").metadata["processes"][0]
    assert "selection_id" not in row


def test_background_tasks_are_selectable_but_services_are_not(processes, monkeypatch):
    monkeypatch.setattr("jarvis.process_control._window_pids", lambda: set())
    control = ProcessControl()
    assert control.list_processes().metadata["processes"] == []
    row = next(row for row in control.list_processes(include_background=True).metadata["processes"] if row["pid"] == 200)
    assert row["has_window"] is False and "selection_id" in row
    monkeypatch.setattr("jarvis.process_control._service_pids", lambda: {200})
    assert not control.end_process(row["selection_id"]).ok
    assert processes[1].stops == 0
    row = control.list_processes("demo").metadata["processes"][0]
    assert "selection_id" not in row and "service" in row["blocked_reason"]


def test_service_inspection_failure_leaves_list_read_only(processes, monkeypatch):
    def denied(): raise OSError("Cannot inspect services")
    monkeypatch.setattr("jarvis.process_control._service_pids", denied)
    result = ProcessControl().list_processes("demo")
    assert result.ok and result.metadata["service_status_verified"] is False
    assert "selection_id" not in result.metadata["processes"][0]


@pytest.mark.parametrize("method", ["end_process", "close_app"])
def test_process_control_tools_are_exposed_to_voice_and_confirmation_cannot_be_skipped(processes, method):
    actions = WindowsActions()
    router = CommandRouter(actions, SimpleNamespace(confirm=lambda *args: False))
    schemas = {s["name"]: s for s in realtime_tool_schemas(router.tools)}
    assert {"list_processes", "end_process", "close_app", "create_text_file", "list_folder"} <= schemas.keys()
    selection = select(actions.process_control)
    result = RealtimeVoiceSession.tool_executor_from_router(router)(method, {"selection_id": selection})
    assert not result["ok"] and result["confirmed"] is False
    assert processes[1].stops == 0


@pytest.mark.parametrize("waiting", [False, True])
def test_normal_close_never_terminates_and_distinguishes_request_from_exit(processes, monkeypatch, waiting):
    posts = []
    monkeypatch.setattr("jarvis.process_control._post_close", lambda process: (posts.append(process.pid) or 1, []))
    if waiting:
        processes[1].wait_error = psutil.TimeoutExpired(3)
    control = ProcessControl()
    selection = select(control)
    result = control.close_app(selection)
    assert result.ok and result.metadata["close_requested"]
    assert result.metadata["exit_verified"] is not waiting
    assert result.metadata["method"] == "normal_close"
    if waiting:
        assert "still running" in result.message and "Nothing was force-stopped" in result.message
    assert posts == [200] and processes[1].stops == 0
    assert not control.end_process(selection).ok  # A separate selection and confirmation are required.


@pytest.mark.parametrize("outcome", [(0, []), (0, ["access denied"]), (1, ["one window refused"])])
def test_missing_or_partially_closed_windows_do_not_trigger_force_fallback(processes, monkeypatch, outcome):
    monkeypatch.setattr("jarvis.process_control._post_close", lambda process: outcome)
    control = ProcessControl()
    result = control.close_app(select(control))
    assert not result.ok and result.metadata["partial"] == bool(outcome[0])
    assert processes[1].stops == 0


def test_dry_run_normal_close_does_not_send_windows_messages(processes, monkeypatch):
    monkeypatch.setattr("jarvis.process_control._post_close", lambda _: pytest.fail("No message in dry run"))
    control = ProcessControl(dry_run=True)
    result = control.close_app(select(control))
    assert result.ok and "normal close" in result.message and processes[1].stops == 0


@pytest.mark.parametrize("gone", [False, True])
def test_close_verification_errors_preserve_evidence_of_the_sent_request(processes, monkeypatch, gone):
    monkeypatch.setattr("jarvis.process_control._post_close", lambda _: (1, []))
    processes[1].wait_error = psutil.NoSuchProcess(200) if gone else psutil.AccessDenied(200)
    control = ProcessControl()
    result = control.close_app(select(control))
    assert result.ok is gone
    assert result.metadata["close_requested"]
    assert result.metadata["exit_verified"] is gone
    assert processes[1].stops == 0


@pytest.mark.parametrize("command, tool", [("close app demo", "close_app"), ("close demo", "close_app"),
    ("quit demo", "close_app"), ("close application demo", "close_app"), ("force close demo", "end_process")])
def test_plain_close_uses_normal_close_and_force_close_remains_explicit(processes, monkeypatch, command, tool):
    monkeypatch.setattr("jarvis.process_control._post_close", lambda _: (1, []))
    router = CommandRouter(WindowsActions(), SimpleNamespace(confirm=lambda *args: True))
    result = router.handle(command)
    assert result.ok and result.action == tool and result.confirmed
    assert processes[1].stops == (1 if tool == "end_process" else 0)


def test_close_tab_does_not_get_routed_to_process_control(processes):
    router = CommandRouter(WindowsActions(), SimpleNamespace(confirm=lambda *args: pytest.fail("No process action")))
    assert router.local_commands.resource_command("close the current browser tab") is None


@pytest.mark.parametrize("case", ["main", "owned_dialog", "disabled_parent", "hidden", "reused_window", "exited", "denied"])
def test_windows_close_messages_target_only_live_unowned_enabled_windows(processes, monkeypatch, case):
    from unittest.mock import Mock
    from jarvis.process_control import _post_close

    def owner_pid(hwnd, pointer):
        pointer._obj.value = 300 if case == "reused_window" else 200
        return 1

    api = SimpleNamespace(
        GetWindow=Mock(return_value=123 if case == "owned_dialog" else 0),
        IsWindowVisible=Mock(return_value=case != "hidden"),
        IsWindowEnabled=Mock(return_value=case != "disabled_parent"),
        GetWindowThreadProcessId=Mock(side_effect=owner_pid),
        PostMessageW=Mock(return_value=case != "denied"),
    )
    monkeypatch.setattr("jarvis.process_control.ctypes.WinDLL", lambda *args, **kw: api)
    monkeypatch.setattr("jarvis.process_control._desktop_windows", lambda: {200: [42], 999: [77]})
    if case == "exited":
        processes[1].running = False
    count, errors = _post_close(processes[1])
    assert count == (1 if case == "main" else 0)
    if case in {"main", "denied"}:
        api.PostMessageW.assert_called_once_with(42, 0x0010, 0, 0)
    else:
        api.PostMessageW.assert_not_called()
    assert bool(errors) == (case in {"reused_window", "exited", "denied"})


@pytest.mark.skipif(os.name != "nt", reason="Windows message integration")
def test_real_wm_close_delivery_to_a_disposable_zero_area_window(monkeypatch):
    import ctypes
    from ctypes import wintypes
    import time
    from jarvis.process_control import _post_close

    user = ctypes.WinDLL("user32", use_last_error=True)
    user.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
    user.CreateWindowExW.restype = wintypes.HWND
    user.IsWindow.argtypes = [wintypes.HWND]
    user.DestroyWindow.argtypes = [wintypes.HWND]
    user.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user.DispatchMessageW.restype = ctypes.c_ssize_t
    # WS_POPUP | WS_VISIBLE, zero area: a real disposable HWND with no visible
    # desktop content. Never enumerate or send messages to personal app windows.
    window = user.CreateWindowExW(0, "STATIC", "Jarvis close delivery test", 0x90000000,
                                  0, 0, 0, 0, None, None, None, None)
    assert window, ctypes.get_last_error()
    try:
        process = psutil.Process()
        monkeypatch.setattr("jarvis.process_control._desktop_windows", lambda: {process.pid: [window]})
        count, errors = _post_close(process)
        assert count == 1 and errors == []
        message = wintypes.MSG()
        deadline = time.monotonic() + 2
        while user.IsWindow(window) and time.monotonic() < deadline:
            if user.PeekMessageW(ctypes.byref(message), window, 0, 0, 1):
                user.TranslateMessage(ctypes.byref(message))
                user.DispatchMessageW(ctypes.byref(message))
            else:
                time.sleep(.01)
        assert not user.IsWindow(window)
    finally:
        if user.IsWindow(window):
            user.DestroyWindow(window)


def test_end_app_and_cancel_jarvis_task_are_different_actions(processes):
    from jarvis.session import CommandSession

    prompts = []
    router = CommandRouter(WindowsActions(), SimpleNamespace(confirm=lambda *args: prompts.append(args) or True))
    result = CommandSession(router=router).execute("end task demo")
    assert result.ok and result.action == "end_process"
    assert result.confirmed is True
    assert any(event["state"] == "waiting_confirmation" for event in result.metadata["state_timeline"])
    assert router.local_commands.safety is router.safety
    assert "demo.exe:200:" in prompts[0][1]
    assert not router.workflow_runner.cancelled.is_set()
    assert router.handle("cancel current task").ok
    assert router.workflow_runner.cancelled.is_set()
    assert processes[1].stops == 1


def test_multiple_exact_name_matches_require_pid_choice(processes, monkeypatch, tmp_path):
    app2 = Process(300, tmp_path)
    monkeypatch.setattr(psutil, "process_iter", lambda: iter([processes[1], app2]))
    router = CommandRouter(WindowsActions(), SimpleNamespace(confirm=lambda *args: pytest.fail("Must clarify first")))
    result = router.handle("end process demo")
    assert not result.ok and "PID" in result.message
    assert processes[1].stops == app2.stops == 0


def test_normal_close_selects_unique_visible_app_not_background_helpers(processes, monkeypatch, tmp_path):
    app2 = Process(300, tmp_path)
    monkeypatch.setattr(psutil, "process_iter", lambda: iter([processes[1], app2]))
    closed = []
    monkeypatch.setattr("jarvis.process_control._post_close", lambda process: (closed.append(process.pid) or 1, []))
    router = CommandRouter(WindowsActions(), SimpleNamespace(confirm=lambda *args: True))
    result = router.handle("close app demo")
    assert result.ok and closed == [200]
    assert processes[1].stops == app2.stops == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows process API integration")
def test_real_termination_only_of_a_disposable_test_child(monkeypatch):
    from jarvis.processes import background_process_options

    # No user application is touched. Visibility is injected solely for this
    # headless child; identity, owner, Windows critical checks and termination are real.
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                             **background_process_options())
    try:
        monkeypatch.setattr("jarvis.process_control._window_pids", lambda: {child.pid})
        control = ProcessControl()
        result = control.list_processes(str(child.pid))
        assert result.ok
        row = next(row for row in result.metadata["processes"] if row["pid"] == child.pid)
        result = control.end_process(row["selection_id"])
        assert result.ok and result.metadata["exit_verified"]
        child.wait(timeout=3)
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=3)
