from __future__ import annotations

import os
import subprocess
import sys

import pytest

from jarvis.app_database import AppDatabase
from jarvis.gui import autostart
from jarvis.monitoring import checks
from jarvis import nitrosense
from jarvis.processes import background_process_options, powershell_command
from jarvis.windows_actions import WindowsActions


def test_powershell_is_noninteractive_hidden_and_utf8():
    command = powershell_command("'Hello'")
    assert "-NonInteractive" in command
    assert command[command.index("-WindowStyle") + 1] == "Hidden"
    assert command[-1].endswith("'Hello'")
    assert "UTF8Encoding" in command[-1]


@pytest.mark.parametrize("operation", ["battery", "gpu", "nitrosense", "app_index", "autostart", "action", "readonly", "power_plan"])
def test_every_internal_process_has_no_console_no_stdin_and_a_timeout(monkeypatch, tmp_path, operation):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", run)
    actions = WindowsActions()
    {
        "battery": checks.read_battery,
        "gpu": checks.read_gpu,
        "nitrosense": nitrosense.probe_app_installed,
        "app_index": lambda: AppDatabase(tmp_path / "apps.json").refresh(),
        "autostart": lambda: autostart._run_powershell("'test'"),
        "action": lambda: actions._run_command("Test", ["powercfg", "/getactivescheme"]),
        "readonly": lambda: actions._run_readonly_powershell("Test", "'test'"),
        "power_plan": actions._active_power_scheme_guid,
    }[operation]()
    assert len(calls) == 1
    _, options = calls[0]
    assert options["stdin"] == subprocess.DEVNULL
    assert options["capture_output"] is True
    assert 0 < options["timeout"] <= 120
    if os.name == "nt":
        assert options["creationflags"] & subprocess.CREATE_NO_WINDOW


def test_user_requested_apps_are_not_hidden(monkeypatch):
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: calls.append(kwargs))
    result = WindowsActions().open_app("notepad.exe")
    assert result.ok
    assert calls == [{"shell": False}]


def test_command_timeout_is_reported_without_retry_or_claiming_success(monkeypatch):
    calls = []

    def timeout(command, **kwargs):
        calls.append(command)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)
    actions = WindowsActions()
    result = actions._run_command("Test operation", ["fake-command"])
    assert not result.ok
    assert result.metadata["outcome_uncertain"]
    assert len(calls) == 1
    assert actions._active_power_scheme_guid() is None
    assert not actions._run_readonly_powershell("Test", "'read'").ok
    assert not checks.read_gpu().available
    assert not checks.read_battery().available


@pytest.mark.skipif(os.name != "nt", reason="Windows console allocation regression")
def test_real_child_process_has_no_console_and_cannot_wait_for_input():
    code = "import ctypes,sys; print(int(bool(ctypes.windll.kernel32.GetConsoleWindow()))); print(repr(sys.stdin.read()))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            timeout=10, check=True, **background_process_options())
    assert result.stdout.splitlines() == ["0", "''"]


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell regression")
def test_real_powershell_preserves_bulgarian_and_rejects_read_host():
    result = subprocess.run(powershell_command("'Здравей Берк'"), capture_output=True, text=True,
                            encoding="utf-8", timeout=15, check=True, **background_process_options())
    assert result.stdout.strip() == "Здравей Берк"
    prompt = subprocess.run(powershell_command("Read-Host 'Unexpected prompt'"), capture_output=True,
                            text=True, encoding="utf-8", timeout=15, **background_process_options())
    assert prompt.returncode != 0


def test_failed_probe_output_is_not_reported_as_success(monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda command, **kwargs: subprocess.CompletedProcess(command, 1, '{"Found":true}', "failure"))
    assert nitrosense._run_powershell_json("test") is None
    assert checks._run_powershell_json("test", 1) is None
