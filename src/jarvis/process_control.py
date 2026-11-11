"""Observed, short-lived process selections. No shell commands or process trees."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import threading
import time
import uuid

from .models import CommandResult


PROTECTED = {"system", "registry", "idle", "smss.exe", "csrss.exe", "wininit.exe",
             "winlogon.exe", "services.exe", "lsass.exe", "svchost.exe", "explorer.exe",
             "dwm.exe", "msmpeng.exe", "nissrv.exe", "securityhealthservice.exe",
             "securityhealthsystray.exe", "vgc.exe", "vgtray.exe", "senseir.exe", "mssense.exe",
             "nitrosense.exe"}
WINDOWS_DESKTOP_APPS = {"notepad.exe", "mspaint.exe", "calc.exe"}
PROTECTED_PARTS = {"windows defender", "windows defender advanced threat protection", "eset",
                   "kaspersky lab", "bitdefender", "avast software", "avg", "malwarebytes",
                   "riot vanguard", "easyanticheat", "battleye"}


def _service_pids() -> set[int]:
    import psutil
    if os.name != "nt":
        raise OSError("Windows service inspection is unavailable.")
    return {pid for service in psutil.win_service_iter() if (pid := service.pid()) is not None}


def _desktop_windows() -> dict[int, list[int]]:
    if os.name != "nt":
        raise OSError("Process control requires Windows.")
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumWindows.restype = wintypes.BOOL
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindowVisible.restype = wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    windows = {}

    @callback_type
    def visit(window, _data):
        if user.IsWindowVisible(window):
            pid = wintypes.DWORD()
            user.GetWindowThreadProcessId(window, ctypes.byref(pid))
            windows.setdefault(pid.value, []).append(window)
        return True

    if not user.EnumWindows(visit, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return windows


def _window_pids() -> set[int]:
    return set(_desktop_windows())


def _post_close(process) -> tuple[int, list[str]]:
    """Post only WM_CLOSE to observed unowned windows; never touch Save dialogs."""
    windows = _desktop_windows().get(process.pid, [])
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindowVisible.restype = wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.PostMessageW.restype = wintypes.BOOL
    user.IsWindowEnabled.argtypes = [wintypes.HWND]
    user.IsWindowEnabled.restype = wintypes.BOOL
    requested, errors = 0, []
    for window in windows:
        if (not user.IsWindowVisible(window) or not user.IsWindowEnabled(window)
                or user.GetWindow(window, 4)):  # GW_OWNER; skip modal dialogs and their disabled parent.
            continue
        pid = wintypes.DWORD()
        user.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value != process.pid or not process.is_running():
            errors.append("A window or process identity changed; it was skipped.")
            continue
        if user.PostMessageW(window, 0x0010, 0, 0):  # WM_CLOSE, never WM_QUIT.
            requested += 1
        else:
            errors.append(f"Windows refused a close request (error {ctypes.get_last_error()}).")
    return requested, errors


def _is_critical(pid: int) -> bool:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.IsProcessCritical.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    kernel.IsProcessCritical.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION only.
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        critical = wintypes.BOOL()
        if not kernel.IsProcessCritical(handle, ctypes.byref(critical)):
            raise ctypes.WinError(ctypes.get_last_error())
        return bool(critical.value)
    finally:
        kernel.CloseHandle(handle)


class ProcessControl:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self._selections = {}
        self._lock = threading.Lock()

    @staticmethod
    def _check(process, current, visible, *, services, require_window=False):
        if (process.pid <= 4 or process.pid == current.pid
                or process.pid in {parent.pid for parent in current.parents()}):
            raise ValueError("Jarvis, its parent processes and system processes are protected.")
        name, exe = process.name(), Path(process.exe()).resolve()
        windows = Path(os.environ.get("WINDIR", r"C:\Windows")).resolve()
        command = process.cmdline()
        if name.casefold().startswith("jarvis") or any(
                command[index:index + 2] == ["-m", "jarvis"] for index in range(len(command))):
            raise ValueError("Jarvis instances are protected.")
        if (name.casefold() in PROTECTED or PROTECTED_PARTS.intersection(part.casefold() for part in exe.parts) or exe == windows
                or (windows in exe.parents and name.casefold() not in WINDOWS_DESKTOP_APPS)):
            raise ValueError("Windows and security processes are protected.")
        if process.username().casefold() != current.username().casefold():
            raise ValueError("Only applications owned by the current user may be ended.")
        if services is None or process.pid in services:
            raise ValueError("Windows service processes are protected; service status must be verified.")
        if require_window and process.pid not in visible:
            raise ValueError("Normal close needs a visible desktop window; use an explicit force-end request for a background app.")
        if _is_critical(process.pid):
            raise ValueError("Windows marks this process as critical.")
        return name, str(exe)

    def list_processes(self, query: str = "", include_background: bool = False) -> CommandResult:
        try:
            import psutil
        except ImportError:
            return CommandResult(False, "Process control requires psutil. Install the voice dependencies.")
        query = query.strip().casefold()
        try:
            current, visible = psutil.Process(), _window_pids()
            try:
                services = _service_pids()
            except (OSError, psutil.Error):
                services = None  # Listing remains available, but no stop selection is issued.
            rows = []
            now = time.monotonic()
            with self._lock:
                self._selections = {key: value for key, value in self._selections.items() if value[0] > now}
                for process in psutil.process_iter():
                    try:
                        name = process.name()
                        if not query and not include_background and process.pid not in visible:
                            continue
                        if query and query not in name.casefold() and query != str(process.pid):
                            continue
                        # Do not expose other users' process details.
                        if process.username().casefold() != current.username().casefold():
                            continue
                        row = {"pid": process.pid, "name": name,
                               "has_window": process.pid in visible,
                               "memory_mb": round(process.memory_info().rss / 1024**2, 1)}
                        try:
                            _, exe = self._check(process, current, visible, services=services)
                            created = process.create_time()
                            selection = f"{name}:{process.pid}:{uuid.uuid4().hex[:12]}"
                            self._selections[selection] = (now + 120, process, created, name, exe)
                            row["selection_id"] = selection
                        except (ValueError, OSError, psutil.Error) as exc:
                            row["blocked_reason"] = str(exc)
                        rows.append(row)
                        if len(rows) >= 50:
                            break
                    except psutil.Error:
                        continue
                # Bound retained snapshots across repeated voice requests.
                while len(self._selections) > 200:
                    self._selections.pop(next(iter(self._selections)))
            lines = [f"{r['name']} | PID {r['pid']} | {r['memory_mb']} MB | "
                     + ("selectable" if "selection_id" in r else "protected / read-only") for r in rows]
            return CommandResult(True, "\n".join(lines) or "No matching processes found.",
                                 metadata={"processes": rows, "limit": 50, "partial": len(rows) >= 50,
                                           "selection_ttl_seconds": 120, "service_status_verified": services is not None})
        except (OSError, psutil.Error) as exc:
            return CommandResult(False, f"Could not inspect processes: {exc}")

    def end_process(self, selection_id: str) -> CommandResult:
        return self._act_on_process(selection_id, force=True)

    def close_app(self, selection_id: str) -> CommandResult:
        return self._act_on_process(selection_id, force=False)

    def _act_on_process(self, selection_id: str, *, force: bool) -> CommandResult:
        try:
            import psutil
        except ImportError:
            return CommandResult(False, "Process control requires psutil. Nothing was stopped.")

        with self._lock:
            selection = self._selections.pop(selection_id, None)
        if selection is None or selection[0] < time.monotonic():
            return CommandResult(False, "Process selection expired or is unknown. List processes again; nothing was stopped.")
        _, process, created, name, exe = selection
        metadata = {}
        try:
            fresh = psutil.Process(process.pid)
            if not process.is_running() or fresh.create_time() != created:
                return CommandResult(False, "The selected process exited or its PID was reused. Nothing was stopped.")
            checked_name, checked_exe = self._check(fresh, psutil.Process(), _window_pids(),
                                                   services=_service_pids(), require_window=not force)
            if (checked_name, checked_exe) != (name, exe):
                return CommandResult(False, "Process identity changed. List processes again; nothing was stopped.")
            metadata = {"pid": process.pid, "process_name": name, "reversible": False,
                        "method": "force" if force else "normal_close"}
            if self.dry_run:
                description = "force-end" if force else "request normal close for"
                return CommandResult(True, f"Would {description} {name} (PID {process.pid}). Unsaved work may need attention.", metadata=metadata)
            if not force:
                requested, errors = _post_close(process)
                metadata.update(close_requested=bool(requested), windows_requested=requested, exit_verified=False)
                if errors or not requested:
                    return CommandResult(False, "\n".join(errors) or "No eligible main window found; nothing was closed.",
                                         metadata={**metadata, "partial": bool(requested), "errors": errors})
                try:
                    process.wait(timeout=3)
                except psutil.TimeoutExpired:
                    return CommandResult(True, f"Normal close requested for {name}, but it is still running. "
                                         "It may be waiting for Save, may have declined, or may stay in the tray. "
                                         "Nothing was force-stopped; check the app.", metadata=metadata)
                return CommandResult(True, f"{name} exited after a normal close request.",
                                     metadata={**metadata, "exit_verified": True})
            process.terminate()  # psutil checks PID reuse again before TerminateProcess.
            metadata["stop_requested"] = True
            try:
                process.wait(timeout=3)
            except psutil.TimeoutExpired:
                return CommandResult(False, f"End requested for {name}, but exit was not verified. No retry was made.",
                                     metadata={**metadata, "stop_requested": True, "exit_verified": False})
            return CommandResult(True, f"Ended {name} (PID {process.pid}). This cannot be undone.",
                                 metadata={**metadata, "exit_verified": True})
        except psutil.NoSuchProcess:
            if metadata.get("close_requested") or metadata.get("stop_requested"):
                return CommandResult(True, f"{name} exited after the request.", metadata={**metadata, "exit_verified": True})
            return CommandResult(False, "The selected process already exited. No other process was stopped.")
        except (ValueError, OSError, psutil.Error) as exc:
            return CommandResult(False, f"Could not complete {'force-end' if force else 'normal close'}: {exc}",
                                 metadata={**metadata, "exit_verified": False})
