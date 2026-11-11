from __future__ import annotations

from jarvis.gui import autostart


def test_is_enabled_false_when_shortcut_absent(tmp_path):
    assert autostart.is_enabled(tmp_path / "Jarvis.lnk") is False


def test_default_shortcut_path_points_at_the_real_startup_folder():
    path = autostart.default_shortcut_path()
    assert path.name == "Jarvis.lnk"
    assert "Startup" in str(path)
    assert "Start Menu" in str(path)


def test_target_and_args_dev_mode_uses_pythonw_and_module_flag():
    target, arguments, working_directory = autostart._target_and_args()
    assert target.lower().endswith("pythonw.exe") or target.lower().endswith("python.exe")
    assert arguments == "-m jarvis --gui"
    assert working_directory  # never empty -- this is the CWD-safety fix


def test_target_and_args_working_directory_is_the_real_repo_root():
    _target, _arguments, working_directory = autostart._target_and_args()
    from pathlib import Path

    # The repo root must contain pyproject.toml -- a cheap, real sanity
    # check that _repo_root()'s parents[3] offset is still correct.
    assert (Path(working_directory) / "pyproject.toml").exists()


def test_target_and_args_frozen_mode_targets_the_exe_directly(monkeypatch):
    import sys

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\Jarvis\Jarvis.exe")
    target, arguments, working_directory = autostart._target_and_args()
    assert target == r"C:\Program Files\Jarvis\Jarvis.exe"
    assert arguments == ""
    assert working_directory == r"C:\Program Files\Jarvis"


def test_enable_disable_round_trip_against_a_real_temp_location(tmp_path):
    # Real PowerShell + WScript.Shell COM call, not mocked -- verifies the
    # actual shortcut-creation mechanism works, but points at tmp_path
    # rather than the real Windows Startup folder so this test never
    # actually enables autostart on the machine running it.
    shortcut_path = tmp_path / "Jarvis.lnk"
    assert autostart.is_enabled(shortcut_path) is False

    assert autostart.enable(shortcut_path) is True
    assert shortcut_path.exists()
    assert autostart.is_enabled(shortcut_path) is True

    assert autostart.disable(shortcut_path) is True
    assert not shortcut_path.exists()
    assert autostart.is_enabled(shortcut_path) is False


def test_disable_when_already_disabled_is_a_safe_noop(tmp_path):
    shortcut_path = tmp_path / "does_not_exist.lnk"
    assert autostart.disable(shortcut_path) is True


def test_powershell_string_escapes_special_characters():
    # A path or argument containing a literal double quote or backtick
    # must not break out of the PowerShell string it's embedded in.
    escaped = autostart._powershell_string('C:\\Program Files\\Weird "Name"\\app.exe')
    assert '`"' in escaped
    assert '""' not in escaped.replace('`"', "")
