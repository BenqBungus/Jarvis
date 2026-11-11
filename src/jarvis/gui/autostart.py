from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from ..processes import background_process_options, powershell_command

STARTUP_SHORTCUT_NAME = "Jarvis.lnk"


def _startup_folder() -> Path:
    appdata = os.environ.get("APPDATA", "")
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def default_shortcut_path() -> Path:
    return _startup_folder() / STARTUP_SHORTCUT_NAME


def _repo_root() -> Path:
    # src/jarvis/gui/autostart.py -> parents[3] is the repo root.
    return Path(__file__).resolve().parents[3]


def _target_and_args() -> tuple[str, str, str]:
    """Returns (target_exe, arguments, working_directory).

    WorkingDirectory is never left unset: every persistence path in this
    codebase (data/settings.json, logs/audit.jsonl, data/rollback_state.json,
    the workspace root for create_folder/create_file, ...) is resolved
    relative to the process's current working directory, not the script/exe
    location. Items launched from the Windows Startup folder are well-known
    to inherit CWD=C:\\Windows\\System32 unless the shortcut sets one
    explicitly -- an unset one would silently reset the user's settings/
    aliases/app-index on every auto-start, with no visible error.
    """
    if getattr(sys, "frozen", False):
        # Packaged build: the .spec targets gui/__main__.py directly, so the
        # built exe always launches straight into the GUI -- no args needed.
        target = sys.executable
        return target, "", str(Path(target).parent)

    python_dir = Path(sys.executable).parent
    pythonw = python_dir / "pythonw.exe"
    # pythonw.exe (not python.exe) so a GUI launch never flashes/holds open
    # a console window.
    target = str(pythonw) if pythonw.exists() else sys.executable
    return target, "-m jarvis --gui", str(_repo_root())


def is_enabled(shortcut_path: Path | None = None) -> bool:
    """Checks the filesystem directly rather than a cached settings flag,
    so the Settings checkbox can never drift from what will actually
    happen at next login."""
    return (shortcut_path or default_shortcut_path()).exists()


def enable(shortcut_path: Path | None = None) -> bool:
    destination = shortcut_path or default_shortcut_path()
    target, arguments, working_directory = _target_and_args()
    destination.parent.mkdir(parents=True, exist_ok=True)
    script = f"""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut("{_powershell_string(str(destination))}")
$shortcut.TargetPath = "{_powershell_string(target)}"
$shortcut.Arguments = "{_powershell_string(arguments)}"
$shortcut.WorkingDirectory = "{_powershell_string(working_directory)}"
$shortcut.IconLocation = "{_powershell_string(target)},0"
$shortcut.Save()
""".strip()
    return _run_powershell(script)


def disable(shortcut_path: Path | None = None) -> bool:
    destination = shortcut_path or default_shortcut_path()
    if not destination.exists():
        return True
    try:
        destination.unlink()
        return True
    except OSError:
        return False


def _run_powershell(script: str) -> bool:
    try:
        completed = subprocess.run(
            powershell_command(script),
            capture_output=True,
            text=True,
            timeout=15.0,
            check=False,
            encoding="utf-8",
            errors="replace",
            **background_process_options(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _powershell_string(value: str) -> str:
    return value.replace("`", "``").replace('"', '`"').replace("$", "`$")
