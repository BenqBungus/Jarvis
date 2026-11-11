"""Close observed Explorer windows without terminating the Windows shell."""
from pathlib import Path
import os
import threading
import time
from uuid import uuid4

from .models import CommandResult


class FolderWindows:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self._lock = threading.Lock()
        self._selections = {}

    @staticmethod
    def _observe():
        import psutil
        import win32gui
        import win32process
        windows = []
        user = psutil.Process().username().casefold()
        explorer = (Path(os.environ["WINDIR"]) / "explorer.exe").resolve()
        foreground = win32gui.GetForegroundWindow()

        def visit(hwnd, _):
            try:
                if (win32gui.GetClassName(hwnd) != "CabinetWClass" or not win32gui.IsWindowVisible(hwnd)
                        or not win32gui.IsWindowEnabled(hwnd) or win32gui.GetWindow(hwnd, 4)):
                    return
                pid = win32process.GetWindowThreadProcessId(hwnd)[1]
                process = psutil.Process(pid)
                if Path(process.exe()).resolve() != explorer or process.username().casefold() != user:
                    return
                windows.append({"hwnd": hwnd, "pid": pid, "created": process.create_time(),
                                "title": win32gui.GetWindowText(hwnd), "foreground": hwnd == foreground})
            except (OSError, psutil.Error):
                return
        win32gui.EnumWindows(visit, None)
        return windows

    @staticmethod
    def _identity(row):
        return tuple(row[k] for k in ("hwnd", "pid", "created", "title"))

    def list_windows(self):
        try:
            rows = self._observe()
            now = time.monotonic()
            with self._lock:
                self._selections = {k: v for k, v in self._selections.items() if now - v[0] < 30}
                public = []
                for row in rows[:50]:
                    token = uuid4().hex
                    self._selections[token] = (now, row)
                    public.append({"selection_id": token, "title": row["title"], "foreground": row["foreground"]})
            return CommandResult(True, "\n".join(row["title"] for row in public) or "No folder windows are open.",
                metadata={"folder_windows": public, "partial": len(rows) > 50})
        except Exception:
            return CommandResult(False, "Could not inspect File Explorer windows.")

    @staticmethod
    def _post_close(row):
        import win32gui
        import win32process
        hwnd = row["hwnd"]
        if (win32gui.GetClassName(hwnd) != "CabinetWClass" or not win32gui.IsWindowEnabled(hwnd)
                or win32gui.GetWindow(hwnd, 4) or win32process.GetWindowThreadProcessId(hwnd)[1] != row["pid"]
                or win32gui.GetWindowText(hwnd) != row["title"]):
            raise ValueError("The selected folder window changed.")
        win32gui.PostMessage(hwnd, 0x0010, 0, 0)
        for _ in range(10):
            if not win32gui.IsWindow(hwnd):
                return True
            time.sleep(0.05)
        return False

    def close_window(self, selection_id):
        try:
            with self._lock:
                selected = self._selections.pop(selection_id, None)
            if not selected or time.monotonic() - selected[0] >= 30:
                return CommandResult(False, "List folder windows again; this selection expired.")
            row = selected[1]
            if not any(self._identity(fresh) == self._identity(row) for fresh in self._observe()):
                return CommandResult(False, "The selected folder window changed or closed. Nothing was closed.")
            if self.dry_run:
                return CommandResult(True, "Would close the Explorer window: " + row["title"])
            closed = self._post_close(row)
            return CommandResult(True, ("Closed folder window: " if closed else "Close requested; Windows has not yet closed: ") + row["title"],
                metadata={"close_requested": True, "window_closed": closed, "files_deleted": False, "process_terminated": False})
        except Exception:
            return CommandResult(False, "Windows refused the folder-window close. No files were deleted or processes terminated.")
