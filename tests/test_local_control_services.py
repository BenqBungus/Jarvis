from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from jarvis.files import FileSearchService
from jarvis.local_commands import TeachingService
from jarvis.models import CommandResult
from jarvis.rollback import RollbackManager
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.user_settings import JarvisSettings
from jarvis.windows_actions import WindowsActions


@pytest.fixture
def router(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ai = Mock()
    ai.parse_intent.side_effect = AssertionError("Must not call cloud intent parsing")
    ai.answer_conversation.side_effect = AssertionError("Must not call cloud conversation")
    value = CommandRouter(WindowsActions(dry_run=True), SafetyPolicy(auto_confirm=False), ai=ai)
    value.files.folders = {"desktop": tmp_path}
    return value


@pytest.mark.parametrize("text, fragment", [("звук на 30", "30%"), ("volume 0", "0%"),
    ("намали звука на 100", "100%"), ("отвори NitroSense", "NitroSense"), ("отвори калкулатор", "калкулатор")])
def test_local_rules_work_without_ai(router, text, fragment):
    result = router.handle("локално " + text)
    assert result.ok
    assert fragment in result.message
    assert not router.ai.parse_intent.called


@pytest.mark.parametrize("text", ["volume 101", "volume -1", "отвори unknown.exe", "рестартирай лаптопа",
                                    "run powershell", "потърси в интернет", "как си"])
def test_unknown_or_unapproved_local_commands_do_not_fall_back_to_cloud(router, text):
    result = router.local_commands.handle(text)
    assert not result.ok
    assert not router.ai.parse_intent.called


def test_teach_mode_never_calls_action_router(router):
    router.actions.set_volume = Mock(side_effect=AssertionError("Must not execute"))
    result = router.handle("научи ме как да променя звука")
    assert result.ok
    assert result.metadata["instruction_only"]
    assert not result.metadata["action_executed"]
    assert not router.ai.parse_intent.called


@pytest.mark.parametrize("topic", ["volume", "NitroSense Performance", "Windows Update", "файл"])
def test_teaching_guides_are_local_and_explicitly_not_screen_observations(topic):
    result = TeachingService().explain(topic)
    assert result.ok
    assert result.metadata["local_only"]
    assert not result.metadata["screen_observed"]


def test_teaching_unknown_topic_does_not_pretend_to_be_implemented():
    result = TeachingService().explain("quantum teleportation")
    assert not result.ok
    assert result.metadata["instruction_only"]


def test_file_search_returns_multiple_observed_paths_and_never_opens_them(router, tmp_path, monkeypatch):
    (tmp_path / "podcast-one.txt").write_text("private contents", encoding="utf-8")
    (tmp_path / "podcast-two").mkdir()
    monkeypatch.setattr("os.startfile", lambda *_: pytest.fail("Search must never launch"))
    result = router.local_commands.handle("намери podcast в Desktop")
    assert result.ok
    assert len(result.metadata["file_results"]) == 2
    assert "private contents" not in str(result)
    assert not result.metadata["content_read"]


def test_search_reports_bounds_and_invalid_paths(tmp_path):
    service = FileSearchService(folders={"desktop": tmp_path})
    for index in range(5):
        (tmp_path / f"file{index}.txt").touch()
    result = service.search("file", max_entries=2)
    assert result.metadata["partial"]
    assert result.metadata["entries_checked"] == 2
    assert not service.search("file", root="Z:\\not-a-real-root").ok
    assert not service.search("x").ok


@pytest.mark.parametrize("suffix", [".exe", ".bat", ".ps1", ".lnk", ".url", ".vbs", ".docm", ".unknown"])
def test_local_open_rejects_executable_and_unknown_types(tmp_path, suffix):
    path = tmp_path / ("file" + suffix)
    path.touch()
    assert not FileSearchService(dry_run=True).open_path(str(path)).ok


@pytest.mark.parametrize("path", [r"\\server\share\file.txt", r"\\?\C:\secret.txt", "https://example.org", "relative.txt"])
def test_local_paths_cannot_be_remote_or_device_paths(path):
    assert not FileSearchService(dry_run=True).open_path(path).ok


def test_document_open_is_only_reported_as_launch_acceptance(tmp_path, monkeypatch):
    target = tmp_path / "example.txt"
    target.write_text("example", encoding="utf-8")
    launched = []
    monkeypatch.setattr("os.startfile", lambda path: launched.append(path))
    result = FileSearchService().open_path(str(target))
    assert result.ok
    assert result.metadata["verification"] == "launch_request_accepted"
    assert not result.metadata["window_verified"]
    assert launched == [str(target)]


def test_failed_undo_is_retained_and_successful_undo_is_removed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = RollbackManager()
    manager.push("Previous volume", "volume", {"percent": 37})
    actions = WindowsActions()
    monkeypatch.setattr(actions, "set_volume", lambda percent: CommandResult(False, "Device unavailable"))
    assert not actions.undo_last_action().ok
    assert manager.peek().payload["percent"] == 37
    monkeypatch.setattr(actions, "set_volume", lambda percent: CommandResult(True, "Restored"))
    assert actions.undo_last_action().ok
    assert manager.peek() is None


def test_undo_center_snapshot_cannot_undo_a_different_new_action(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    manager = RollbackManager()
    manager.push("First", "volume", {"percent": 50})
    old_stamp = manager.peek().timestamp
    manager.push("Second", "volume", {"percent": 60})
    actions = WindowsActions()
    monkeypatch.setattr(actions, "set_volume", lambda *_: pytest.fail("Stale undo must not execute"))
    assert not actions.undo_last_action(expected_timestamp=old_stamp).ok
    assert len(manager.load()) == 2


def test_volume_is_read_back_and_mismatch_is_not_success(tmp_path, monkeypatch):
    from jarvis import volume
    monkeypatch.chdir(tmp_path)
    values = iter([50, 60])
    monkeypatch.setattr(volume, "get_master_volume_percent", lambda: next(values))
    monkeypatch.setattr(volume, "set_master_volume_percent", lambda percent: None)
    result = WindowsActions().set_volume(30)
    assert not result.ok
    assert result.metadata["observed"] == 60
    assert RollbackManager().peek().payload["percent"] == 50


def test_gaming_does_not_close_apps_without_a_user_list():
    result = WindowsActions(dry_run=True, settings=JarvisSettings()).game_mode()
    assert result.ok
    assert result.metadata["close_processes"] == []


@pytest.mark.parametrize("name", ["*", "Discord*", "svchost", "lsass.exe", "[abc]", "one;two"])
def test_gaming_rejects_wildcard_or_system_process_targets(name):
    result = WindowsActions(dry_run=True, settings=JarvisSettings(gaming={"close_processes": [name]})).game_mode()
    assert not result.ok
