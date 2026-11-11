from pathlib import Path
from types import SimpleNamespace
import stat
import zipfile

import pytest

from jarvis.local_file_actions import LocalFileActions
from jarvis.router import CommandRouter
from jarvis.realtime import RealtimeVoiceSession
from jarvis.windows_actions import WindowsActions
from jarvis.rollback import RollbackManager


@pytest.fixture
def local_fs(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    desktop = tmp_path / "Desktop"
    documents = tmp_path / "Documents"
    for folder in (workspace, desktop, documents):
        folder.mkdir()
    monkeypatch.chdir(workspace)
    folders = {"desktop": desktop, "documents": documents}
    monkeypatch.setattr("jarvis.files.FileSearchService._known_folders", staticmethod(lambda: folders))
    return LocalFileActions(folders=folders), desktop, documents


def test_create_rename_move_copy_outside_workspace_without_overwrite(local_fs):
    files, desktop, documents = local_fs
    assert files.create_local_folder("Desktop/Work/Notes").ok
    assert files.create_local_file("Desktop/Work/Notes/Idea.txt", "Hello\nWorld").ok
    assert not files.create_local_file("Desktop/Work/Notes/Idea.txt", "overwritten").ok
    assert files.rename_local_path("Desktop/Work/Notes/Idea.txt", "Plan.txt").ok
    assert files.copy_local_file("Desktop/Work/Notes/Plan.txt", "Documents/Copy.txt").ok
    assert files.move_local_path("Desktop/Work/Notes", "Documents/Notes").ok
    assert not (desktop / "Work/Notes").exists()
    assert (documents / "Notes/Plan.txt").read_text() == "Hello\nWorld"
    assert (documents / "Copy.txt").read_text() == "Hello\nWorld"
    assert not files.move_local_path("Documents/Notes/Plan.txt", "Documents/Copy.txt").ok
    assert (documents / "Notes/Plan.txt").exists()
    assert files.list_local_folder("Documents").ok


def test_rename_then_folder_move_undo_in_reverse_order_after_restart(local_fs):
    files, desktop, documents = local_fs
    files.create_local_folder("Desktop/Work")
    files.create_local_file("Desktop/Work/Original.txt", "keep me")
    assert files.rename_local_path("Desktop/Work/Original.txt", "Plan.txt").metadata["undo_available"]
    assert files.move_local_path("Desktop/Work", "Documents/Work").metadata["undo_available"]
    manager = RollbackManager()
    assert len(manager.load()) == 2
    assert all(row.undo_type == "local_path_move" for row in manager.load())
    actions = WindowsActions()  # History and identities survive a new service instance.
    assert actions.undo_last_action().metadata["undo_record_removed"]
    assert (desktop / "Work/Plan.txt").read_text() == "keep me"
    assert not (documents / "Work").exists()
    assert len(manager.load()) == 1
    assert actions.undo_last_action().ok
    assert (desktop / "Work/Original.txt").read_text() == "keep me"
    assert manager.load() == []


@pytest.mark.parametrize("kind", ["file", "folder"])
def test_undo_refuses_replaced_object_even_with_same_name_and_content(local_fs, kind):
    files, desktop, documents = local_fs
    original = desktop / "Original"
    moved = documents / "Moved"
    if kind == "file":
        original.write_text("same")
    else:
        original.mkdir()
    assert files.move_local_path(str(original), str(moved)).ok
    recorded = RollbackManager().peek()
    moved.rename(documents / "SavedElsewhere")
    if kind == "file":
        moved.write_text("same")
    else:
        moved.mkdir()
    result = WindowsActions().undo_last_action()
    assert not result.ok
    assert "replaced" in result.message
    assert not original.exists()
    assert moved.exists()
    assert RollbackManager().peek() == recorded


def test_undo_never_overwrites_recreated_original_path_and_can_be_retried(local_fs):
    files, desktop, documents = local_fs
    original = desktop / "Original.txt"
    original.write_text("original")
    assert files.move_local_path(str(original), "Documents/Moved.txt").ok
    original.write_text("unrelated")
    assert not WindowsActions().undo_last_action().ok
    assert original.read_text() == "unrelated"
    assert (documents / "Moved.txt").read_text() == "original"
    assert len(RollbackManager().load()) == 1
    original.rename(desktop / "Unrelated.txt")
    assert WindowsActions().undo_last_action().ok
    assert original.read_text() == "original"


def test_undo_restores_path_not_old_contents(local_fs):
    files, desktop, documents = local_fs
    (desktop / "Original.txt").write_text("original")
    assert files.move_local_path("Desktop/Original.txt", "Documents/Moved.txt").ok
    (documents / "Moved.txt").write_text("new edits on the same file")
    assert WindowsActions().undo_last_action().ok
    assert (desktop / "Original.txt").read_text() == "new edits on the same file"


@pytest.mark.parametrize("missing", ["source", "parent"])
def test_missing_undo_source_or_parent_retains_history(local_fs, missing):
    files, desktop, documents = local_fs
    files.create_local_folder("Desktop/Work")
    files.create_local_file("Desktop/Work/Original.txt", "content")
    assert files.move_local_path("Desktop/Work/Original.txt", "Documents/Moved.txt").ok
    if missing == "source":
        (documents / "Moved.txt").rename(documents / "Elsewhere.txt")
    else:
        (desktop / "Work").rename(desktop / "RenamedParent")
    assert not WindowsActions().undo_last_action().ok
    assert RollbackManager().peek() is not None


def test_undo_denial_dry_run_and_stale_snapshot_leave_file_untouched(local_fs):
    from jarvis.safety import SafetyPolicy

    files, _, documents = local_fs
    files.create_local_file("Desktop/Original.txt", "content")
    assert files.move_local_path("Desktop/Original.txt", "Documents/Moved.txt").ok
    stamp = RollbackManager().peek().timestamp
    router = CommandRouter(WindowsActions(), SafetyPolicy(auto_confirm=False))
    router.safety.confirm = lambda *args: False
    denied = router.handle("local undo last action")
    assert not denied.ok and denied.confirmed is False
    assert WindowsActions(dry_run=True).undo_last_action().ok
    assert RollbackManager().peek().timestamp == stamp
    assert not WindowsActions().undo_last_action(expected_timestamp="stale").ok
    assert (documents / "Moved.txt").exists()


def test_local_undo_confirms_specific_action_and_never_calls_ai(local_fs):
    from unittest.mock import Mock
    from jarvis.safety import SafetyPolicy

    files, desktop, _ = local_fs
    files.create_local_file("Desktop/Original.txt", "content")
    assert files.rename_local_path("Desktop/Original.txt", "Plan.txt").ok
    safety = SafetyPolicy(auto_confirm=True)
    safety.confirm = Mock(return_value=True)
    ai = Mock()
    ai.parse_intent.side_effect = AssertionError("Undo must stay local")
    router = CommandRouter(WindowsActions(), safety, ai=ai)
    result = router.handle("local undo last action")
    assert result.ok and result.confirmed
    assert (desktop / "Original.txt").exists()
    assert "Original.txt" in safety.confirm.call_args.args[1]
    assert "Plan.txt" in safety.confirm.call_args.args[1]
    ai.parse_intent.assert_not_called()


def test_changed_history_during_confirmation_cannot_undo_new_action(local_fs):
    from jarvis.safety import SafetyPolicy

    files, _, documents = local_fs
    files.create_local_file("Desktop/Original.txt", "content")
    assert files.move_local_path("Desktop/Original.txt", "Documents/Moved.txt").ok
    safety = SafetyPolicy(auto_confirm=True)

    def confirm(*args):
        RollbackManager().push("Newer action", "volume", {"percent": 50})
        return True

    safety.confirm = confirm
    result = CommandRouter(WindowsActions(), safety).handle("local undo")
    assert not result.ok
    assert "history changed" in result.message
    assert (documents / "Moved.txt").exists()
    assert len(RollbackManager().load()) == 2


def test_failed_move_and_dry_run_do_not_add_undo_records(local_fs):
    files, _, _ = local_fs
    files.create_local_file("Desktop/Original.txt", "content")
    assert not files.move_local_path("Desktop/Original.txt", "Desktop/Original.txt").ok
    files.dry_run = True
    result = files.rename_local_path("Desktop/Original.txt", "Plan.txt")
    assert result.ok and not result.metadata["undo_available"]
    assert not result.metadata["change_completed"]
    assert RollbackManager().load() == []


def test_history_write_failure_reports_completed_move_truthfully(local_fs, monkeypatch):
    files, desktop, documents = local_fs
    files.create_local_file("Desktop/Original.txt", "content")

    def fail(*args):
        raise OSError("Simulated disk error")

    monkeypatch.setattr(RollbackManager, "push", fail)
    result = files.move_local_path("Desktop/Original.txt", "Documents/Moved.txt")
    assert result.ok and result.metadata["change_completed"]
    assert not result.metadata["undo_available"]
    assert "undo history could not be saved" in result.message
    assert not (desktop / "Original.txt").exists()
    assert (documents / "Moved.txt").exists()


def test_history_cleanup_failure_reports_completed_restore_without_moving_twice(local_fs, monkeypatch):
    files, desktop, _ = local_fs
    files.create_local_file("Desktop/Original.txt", "content")
    assert files.rename_local_path("Desktop/Original.txt", "Plan.txt").ok

    def fail(*args):
        raise OSError("Simulated disk error")

    monkeypatch.setattr(RollbackManager, "discard_if_latest", fail)
    actions = WindowsActions()
    result = actions.undo_last_action()
    assert result.ok and result.metadata["change_completed"]
    assert not result.metadata["undo_record_removed"]
    assert "history could not be updated" in result.message
    assert not actions.undo_last_action().ok
    assert (desktop / "Original.txt").read_text() == "content"


@pytest.mark.parametrize("payload", [{}, {"version": 1, "identity": {}},
    {"version": 1, "identity": {}, "source": "relative", "destination": "Desktop/file"}])
def test_malformed_move_undo_fails_normally_and_retains_record(local_fs, payload):
    RollbackManager().push("Malformed", "local_path_move", payload)
    assert not WindowsActions().undo_last_action().ok
    assert RollbackManager().peek() is not None


def test_undo_revalidates_system_path_protection(local_fs, monkeypatch):
    files, desktop, documents = local_fs
    files.create_local_file("Desktop/Original.txt", "content")
    assert files.move_local_path("Desktop/Original.txt", "Documents/Moved.txt").ok
    monkeypatch.setenv("WINDIR", str(desktop))
    assert not WindowsActions().undo_last_action().ok
    assert (documents / "Moved.txt").exists()
    assert RollbackManager().peek() is not None


def test_cancelled_undo_retains_record_and_file(local_fs):
    files, _, documents = local_fs
    files.create_local_file("Desktop/Original.txt", "content")
    assert files.move_local_path("Desktop/Original.txt", "Documents/Moved.txt").ok
    actions = WindowsActions()
    actions.local_files.cancelled = lambda: True
    assert not actions.undo_last_action().ok
    assert (documents / "Moved.txt").exists()
    assert RollbackManager().peek() is not None


def test_undo_destination_race_does_not_overwrite(local_fs, monkeypatch):
    files, desktop, documents = local_fs
    files.create_local_file("Desktop/Original.txt", "content")
    assert files.move_local_path("Desktop/Original.txt", "Documents/Moved.txt").ok
    original_rename = Path.rename

    def race(path, target):
        if path == documents / "Moved.txt":
            (desktop / "Original.txt").write_text("created concurrently")
        return original_rename(path, target)

    monkeypatch.setattr(Path, "rename", race)
    assert not WindowsActions().undo_last_action().ok
    assert (desktop / "Original.txt").read_text() == "created concurrently"
    assert (documents / "Moved.txt").read_text() == "content"
    assert RollbackManager().peek() is not None


def test_corrupt_history_is_a_normal_undo_failure(local_fs):
    from jarvis.safety import SafetyPolicy

    path = RollbackManager().path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not JSON")
    assert not WindowsActions().undo_last_action().ok
    router = CommandRouter(WindowsActions(), SafetyPolicy(auto_confirm=True))
    assert not router.handle("local undo").ok
    assert path.read_text() == "not JSON"


@pytest.mark.parametrize("path", [r"\\server\share\file", r"\\?\C:\Windows\file", "Desktop/../escape",
    "Desktop/CON.txt", "Desktop/file:stream", "Desktop/trailing.", "Desktop/.env", "Desktop/.ssh/key", "C:relative"])
def test_unsafe_paths_are_rejected(local_fs, path):
    files, _, _ = local_fs
    assert not files.create_local_folder(path).ok
    assert not files.create_local_file(path).ok


def test_protected_system_path_and_root_rename_are_rejected(local_fs, monkeypatch, tmp_path):
    files, desktop, _ = local_fs
    system = tmp_path / "system"
    monkeypatch.setenv("WINDIR", str(system))
    assert not files.create_local_folder(str(system / "Bad")).ok
    assert not files.rename_local_path("Desktop", "Other").ok
    assert not files.rename_local_path("Desktop", "../Other").ok
    assert desktop.exists()


def test_linked_paths_are_not_followed(local_fs):
    files, desktop, documents = local_fs
    link = desktop / "linked"
    try:
        link.symlink_to(documents, target_is_directory=True)
    except OSError:
        pytest.skip("Creating Windows test symlinks is unavailable")
    assert not files.create_local_file("Desktop/linked/new.txt").ok
    assert not files.create_zip("Desktop/linked", "Desktop/archive.zip").ok
    assert not (documents / "new.txt").exists()


def test_windows_reparse_attribute_is_rejected_without_following_it(local_fs, monkeypatch):
    files, desktop, _ = local_fs
    linked = desktop / "placeholder"
    linked.mkdir()
    original = Path.lstat

    def attributes(path, *args, **kwargs):
        if path == linked:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", attributes)
    assert not files.create_local_file("Desktop/placeholder/new.txt").ok
    assert not (linked / "new.txt").exists()


def test_dry_run_does_not_create_change_or_publish(local_fs):
    files, desktop, documents = local_fs
    (desktop / "source.txt").write_text("original")
    files.dry_run = True
    assert files.create_local_folder("Desktop/New").ok
    assert files.create_local_file("Desktop/New.txt", "content").ok
    assert files.rename_local_path("Desktop/source.txt", "changed.txt").ok
    assert files.copy_local_file("Desktop/source.txt", "Documents/Copy.txt").ok
    assert files.create_zip("Desktop/source.txt", "Documents/archive.zip").ok
    assert sorted(p.name for p in desktop.iterdir()) == ["source.txt"]
    assert not list(documents.iterdir())


def test_zip_roundtrip_preserves_files_empty_folders_and_unicode(local_fs):
    files, desktop, documents = local_fs
    root = desktop / "Source"
    (root / "Empty").mkdir(parents=True)
    (root / "Notes.txt").write_text("Hello \u0411\u0435\u0440\u043a", encoding="utf-8")
    assert files.create_zip("Desktop/Source", "Documents/Archive.zip").ok
    assert files.extract_zip("Documents/Archive.zip", "Desktop/Restored").ok
    assert (desktop / "Restored/Source/Notes.txt").read_text(encoding="utf-8") == "Hello \u0411\u0435\u0440\u043a"
    assert (desktop / "Restored/Source/Empty").is_dir()
    assert not files.extract_zip("Documents/Archive.zip", "Desktop/Restored").ok
    assert not list(desktop.glob(".jarvis-*"))
    assert not list(documents.glob(".jarvis-*"))


@pytest.mark.parametrize("names", [["../escape.txt"], ["/absolute.txt"], ["C:/escape.txt"],
    ["folder\\escape.txt"], ["CON"], ["a:stream"], [".env"], ["File.txt", "file.txt"],
    ["a", "a/b.txt"], ["a/b.txt", "a"]])
def test_unsafe_zip_is_rejected_before_destination_creation(local_fs, names):
    files, desktop, _ = local_fs
    with zipfile.ZipFile(desktop / "bad.zip", "w") as archive:
        for name in names:
            archive.writestr(name, b"test")
    if names == ["folder\\escape.txt"]:
        path = desktop / "bad.zip"
        path.write_bytes(path.read_bytes().replace(b"folder/escape.txt", b"folder\\escape.txt"))
    result = files.extract_zip("Desktop/bad.zip", "Desktop/Extracted")
    assert not result.ok
    assert not (desktop / "Extracted").exists()
    assert not list(desktop.glob(".jarvis-*"))


def test_zip_links_are_rejected_and_output_cannot_be_inside_source(local_fs):
    files, desktop, _ = local_fs
    link = zipfile.ZipInfo("link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(desktop / "link.zip", "w") as archive:
        archive.writestr(link, "../outside")
    assert not files.extract_zip("Desktop/link.zip", "Desktop/Extracted").ok
    assert files.create_local_folder("Desktop/Source").ok
    assert not files.create_zip("Desktop/Source", "Desktop/Source/archive.zip").ok


def test_limits_cancelled_copy_and_failed_zip_leave_no_partial_destination(local_fs, monkeypatch):
    files, desktop, documents = local_fs
    (desktop / "source.txt").write_text("source content")
    monkeypatch.setattr("jarvis.local_file_actions.MAX_BYTES", 3)
    assert not files.create_zip("Desktop/source.txt", "Documents/Large.zip").ok
    assert not (documents / "Large.zip").exists()
    monkeypatch.setattr("jarvis.local_file_actions.MAX_BYTES", 512 * 1024 * 1024)
    calls = []
    files.cancelled = lambda: calls.append(True) is None and len(calls) > 1
    result = files.copy_local_file("Desktop/source.txt", "Documents/Cancelled.txt")
    assert not result.ok and "cancelled" in result.message
    assert not (documents / "Cancelled.txt").exists()
    assert not list(documents.glob(".jarvis-*"))


def test_destination_created_during_copy_is_never_overwritten(local_fs, monkeypatch):
    files, desktop, documents = local_fs
    (desktop / "source.txt").write_text("new content")
    original = files._copy_stream

    def raced_copy(*args, **kwargs):
        count = original(*args, **kwargs)
        (documents / "Target.txt").write_text("user content")
        return count

    monkeypatch.setattr(files, "_copy_stream", raced_copy)
    assert not files.copy_local_file("Desktop/source.txt", "Documents/Target.txt").ok
    assert (documents / "Target.txt").read_text() == "user content"
    assert not list(documents.glob(".jarvis-*"))


def test_corrupt_zip_fails_without_publishing_partial_output(local_fs):
    files, desktop, _ = local_fs
    target = desktop / "corrupt.zip"
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("note.txt", b"known fixture bytes")
    target.write_bytes(target.read_bytes().replace(b"known fixture bytes", b"wrong fixture bytes"))
    assert not files.extract_zip("Desktop/corrupt.zip", "Desktop/Result").ok
    assert not (desktop / "Result").exists()
    assert not list(desktop.glob(".jarvis-*"))


def test_expired_deadline_and_archive_entry_limits_are_enforced(local_fs, monkeypatch):
    files, desktop, _ = local_fs
    with pytest.raises(RuntimeError, match="limit"):
        files._tick(0)
    target = desktop / "many.zip"
    with zipfile.ZipFile(target, "w") as archive:
        archive.writestr("one.txt", b"1")
        archive.writestr("two.txt", b"2")
    monkeypatch.setattr("jarvis.local_file_actions.MAX_ENTRIES", 1)
    assert not files.extract_zip("Desktop/many.zip", "Desktop/Result").ok
    assert not (desktop / "Result").exists()


def test_all_new_mutations_require_voice_confirmation(local_fs):
    _, desktop, _ = local_fs
    router = CommandRouter(WindowsActions(), SimpleNamespace(confirm=lambda *args: False))
    tools = ["create_local_folder", "create_local_file", "rename_local_path", "move_local_path",
             "copy_local_file", "create_zip", "extract_zip"]
    for name in tools:
        assert router.tools.get(name).spec.requires_confirmation
        result = RealtimeVoiceSession.tool_executor_from_router(router)(name, {"path": str(desktop / "Denied")})
        assert result["confirmed"] is False and not result["ok"]
    assert not (desktop / "Denied").exists()


def test_local_overlay_external_creation_rename_and_zip_match_voice_tools(local_fs):
    _, desktop, documents = local_fs
    prompts = []
    router = CommandRouter(WindowsActions(), SimpleNamespace(confirm=lambda *args: prompts.append(args) or True))
    assert router.handle("local create folder Test on Desktop").ok
    assert router.handle("local create text file Desktop/Test/Note.txt with content Hello").ok
    assert router.handle('local rename "Desktop/Test/Note.txt" to "Plan.txt"').ok
    assert router.handle('local zip "Desktop/Test" to "Documents/Test.zip"').ok
    assert router.handle('local unzip "Documents/Test.zip" to "Desktop/Restored"').ok
    assert (desktop / "Restored/Test/Plan.txt").read_text() == "Hello"
    assert router.handle("local list folder Desktop/Restored").ok
    assert (documents / "Test.zip").exists() and len(prompts) == 5
