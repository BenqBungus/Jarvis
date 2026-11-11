from unittest.mock import Mock

from jarvis.app_database import AppDatabase, AppEntry
from jarvis.windows_actions import WindowsActions
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy


def test_installed_application_selection_clarifies_ambiguity_and_never_runs_shell_text(monkeypatch):
    monkeypatch.setattr(AppDatabase, "load", lambda _: [AppEntry("Editor", "editor-id"), AppEntry("Editor Preview", "preview-id")])
    actions = WindowsActions()
    launch = Mock(return_value="launched")
    monkeypatch.setattr(actions, "_start_app_id", launch)
    assert not actions.launch_installed_app("Edit").ok
    assert not actions.open_application("powershell -Command Remove-Item").ok
    launch.assert_not_called()
    assert actions.launch_installed_app("Editor") == "launched"
    launch.assert_called_once_with("editor-id", "Editor")


def test_local_executable_is_launched_as_one_argument_not_a_shell_command(monkeypatch, tmp_path):
    executable = tmp_path / "App With Spaces.exe"
    executable.write_bytes(b"fixture")
    launch = Mock()
    monkeypatch.setattr("jarvis.windows_actions.subprocess.Popen", launch)
    actions = WindowsActions()
    assert actions.open_application(str(executable)).ok
    launch.assert_called_once_with([str(executable)], shell=False)
    launch.reset_mock()
    assert not actions.open_application(str(executable) + " --script evil").ok
    launch.assert_not_called()


def test_task_manager_and_installed_launcher_are_available_without_raw_shell():
    router = CommandRouter(WindowsActions(dry_run=True), SafetyPolicy())
    result = router.handle("open task manager")
    assert result.ok and result.action == "open_task_manager" and "Would" in result.message
    assert router.tools.get("launch_installed_app")
    assert router.tools.get("open_application").spec.requires_confirmation
