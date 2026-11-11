from unittest.mock import Mock

import pytest

from jarvis.folder_windows import FolderWindows
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.user_settings import JarvisSettings
from jarvis.windows_actions import WindowsActions


def row(hwnd=5, title="Downloads", foreground=True):
    return {"hwnd": hwnd, "pid": 123, "created": 50.0, "title": title, "foreground": foreground}


@pytest.mark.parametrize("phrase", ["close folder", "close the folder", "close folder Downloads", "затвори папката"])
def test_full_access_closes_observed_folder_without_deleting_or_ending_explorer(monkeypatch, phrase):
    actions = WindowsActions()
    monkeypatch.setattr(actions.folder_windows, "_observe", lambda: [row()])
    close = Mock(return_value=True)
    monkeypatch.setattr(actions.folder_windows, "_post_close", close)
    monkeypatch.setattr(actions.process_control, "end_process", lambda *a: pytest.fail("Must not terminate Explorer"))
    monkeypatch.setattr(actions.local_files, "recycle_local_path", lambda *a: pytest.fail("Must not delete folder"))
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("Repeated confirmation"))
    router = CommandRouter(actions, SafetyPolicy(), settings=JarvisSettings(safety={"full_access_local": True}))
    result = router.local_commands.resource_command(phrase)
    assert result.ok and result.metadata["window_closed"]
    assert not result.metadata["files_deleted"] and not result.metadata["process_terminated"]
    assert result.metadata["approval_source"] == "trusted_local_setting"
    close.assert_called_once()


def test_ambiguous_folder_windows_need_a_target_not_a_confirmation(monkeypatch):
    actions = WindowsActions()
    monkeypatch.setattr(actions.folder_windows, "_observe", lambda: [row(foreground=False), row(6, "Documents", False)])
    close = Mock()
    monkeypatch.setattr(actions.folder_windows, "_post_close", close)
    router = CommandRouter(actions, SafetyPolicy(), settings=JarvisSettings(safety={"full_access_local": True}))
    assert not router.local_commands.resource_command("close folder").ok
    close.assert_not_called()


def test_changed_and_expired_windows_are_not_closed(monkeypatch):
    windows = FolderWindows()
    observe = Mock(return_value=[row()])
    close = Mock()
    monkeypatch.setattr(windows, "_observe", observe)
    monkeypatch.setattr(windows, "_post_close", close)
    selected = windows.list_windows().metadata["folder_windows"][0]["selection_id"]
    observe.return_value = [row(title="Different folder")]
    assert not windows.close_window(selected).ok
    assert not windows.close_window(selected).ok
    close.assert_not_called()


def test_full_access_off_still_asks_before_close(monkeypatch):
    actions = WindowsActions()
    monkeypatch.setattr(actions.folder_windows, "_observe", lambda: [row()])
    close = Mock()
    monkeypatch.setattr(actions.folder_windows, "_post_close", close)
    monkeypatch.setattr("builtins.input", lambda *a: "NO")
    router = CommandRouter(actions, SafetyPolicy())
    assert not router.local_commands.resource_command("close folder").ok
    close.assert_not_called()
