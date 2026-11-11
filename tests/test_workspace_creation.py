from pathlib import Path

import pytest

from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


def test_folder_and_utf8_file_can_be_created_and_listed_without_overwriting(tmp_path):
    actions = WindowsActions()
    result = actions.create_folder("Projects/My Notes")
    assert result.ok and result.metadata["created"]
    assert actions.create_folder("Projects/My Notes").metadata["created"] is False
    assert actions.create_text_file("Projects/My Notes/Notes.txt", "Hello Berk\nSecond line").ok
    before = Path("Projects/My Notes/Notes.txt").stat().st_mtime_ns
    assert not actions.create_file("Projects/My Notes/Notes.txt").ok
    assert Path("Projects/My Notes/Notes.txt").read_text() == "Hello Berk\nSecond line"
    assert Path("Projects/My Notes/Notes.txt").stat().st_mtime_ns == before
    assert actions.list_folder("Projects/My Notes").metadata["entries"] == [{"name": "Notes.txt", "kind": "file"}]


@pytest.mark.parametrize("target", ["", "../outside", "nul", "CON.txt", "a:stream", "bad?.txt", "trailing.", "bad\x00name"])
def test_invalid_or_outside_paths_are_rejected(target):
    actions = WindowsActions()
    assert not actions.create_folder(target).ok
    assert not actions.create_file(target).ok
    assert not actions.list_folder(target).ok


def test_file_folder_conflicts_and_missing_folders_return_errors():
    actions = WindowsActions()
    assert actions.create_file("exists.txt").ok
    assert not actions.create_folder("exists.txt").ok
    assert not actions.create_file("exists.txt/child.txt").ok
    assert not actions.list_folder("exists.txt").ok
    assert not actions.list_folder("missing").ok


def test_dry_run_does_not_create_and_content_limit_is_enforced():
    assert WindowsActions(dry_run=True).create_text_file("new/File.txt", "text").ok
    assert not Path("new").exists()
    assert not WindowsActions().create_text_file("large.txt", "x" * 1_000_001).ok
    assert not Path("large.txt").exists()


@pytest.mark.parametrize("prefix", ["", "local "])
def test_clear_creation_commands_preserve_case_and_work_without_ai(prefix):
    router = CommandRouter(WindowsActions(), SafetyPolicy())
    result = router.handle(prefix + 'create a folder called "Projects/My Notes"')
    assert result.ok and result.action == "create_folder"
    assert "My Notes" in result.metadata["path"]
    result = router.handle(prefix + 'create text file "Projects/My Notes/ReadMe.txt" with content Hello Berk')
    assert result.ok
    assert Path("Projects/My Notes/ReadMe.txt").read_text() == "Hello Berk"
    assert router.handle(prefix + 'list folder "Projects/My Notes"').ok
