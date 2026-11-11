import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jarvis.ai_client import JarvisAI
from jarvis.conversation_policy import CRITICAL_CONVERSATION_POLICY
from jarvis.file_editing import FileEditing
from jarvis.files import FileSearchService
from jarvis.local_file_actions import LocalFileActions
from jarvis.models import CommandResult
from jarvis.realtime import RealtimeVoiceConfig, RealtimeVoiceSession
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.vision.sharing import ScreenSharing
from jarvis.windows_actions import WindowsActions


@pytest.fixture
def sharing(monkeypatch):
    ai = Mock()
    ai.describe_image_bytes.return_value = CommandResult(True, "A missing semicolon is visible.")
    service = ScreenSharing(ai)
    service.indicator_available = True
    capture = Mock(return_value=b"example-image")
    monkeypatch.setattr(service, "_snapshot", capture)
    return service, ai, capture


def test_screen_sharing_off_by_default_and_needs_visible_indicator(sharing):
    service, ai, capture = sharing
    assert not service.ask("What is wrong?").ok
    assert service.start().ok
    assert not service.ask("What is wrong?").ok
    capture.assert_not_called()
    service.indicator_visible()
    assert service.ask("What is wrong?").ok
    capture.assert_called_once()
    ai.describe_image_bytes.assert_called_once_with(b"example-image", "What is wrong?")


def test_sharing_does_not_capture_until_question_and_never_persists_images(sharing, monkeypatch):
    service, _, capture = sharing
    monkeypatch.setattr(Path, "open", lambda *a, **kw: pytest.fail("No persistent screenshots"))
    service.start()
    service.indicator_visible()
    assert service.status().ok
    capture.assert_not_called()
    result = service.ask("Explain this")
    assert result.ok and result.metadata["snapshot_on_request"]
    assert not result.metadata["image_persisted"]
    assert result.metadata["scope"] == "primary_screen"


@pytest.mark.parametrize("end", ["stop", "heartbeat"])
def test_sharing_stops_on_revocation_expiry_or_missing_indicator(sharing, end):
    service, _, capture = sharing
    service.start()
    service.indicator_visible()
    if end == "stop":
        service.stop()
    else:
        service._visible_at -= 3
    assert not service.ask("Read screen").ok
    capture.assert_not_called()


def test_stop_after_capture_prevents_upload(sharing):
    service, ai, capture = sharing
    service.start()
    service.indicator_visible()
    capture.side_effect = lambda: (service.stop(), b"image")[1]
    assert not service.ask("Explain").ok
    ai.describe_image_bytes.assert_not_called()


def test_stop_while_api_runs_discards_stale_answer(sharing):
    service, ai, _ = sharing
    service.start()
    service.indicator_visible()
    ai.describe_image_bytes.side_effect = lambda *a: (service.stop(), CommandResult(True, "Old screen answer"))[1]
    result = service.ask("Explain")
    assert not result.ok and "Old screen answer" not in result.message


def test_dry_run_and_headless_sharing_do_not_start():
    assert not ScreenSharing(Mock()).start().ok
    service = ScreenSharing(Mock(), dry_run=True)
    service.indicator_available = True
    assert service.start().ok and not service.state()["sharing"]


def test_snapshot_requests_only_primary_screen(monkeypatch):
    from PIL import Image, ImageGrab

    grab = Mock(return_value=Image.new("RGB", (64, 32), "black"))
    monkeypatch.setattr(ImageGrab, "grab", grab)
    frame = ScreenSharing._snapshot()
    assert frame.startswith(b"\x89PNG")
    grab.assert_called_once_with(all_screens=False)


def test_realtime_stop_bypasses_an_unstarted_executor_queue(sharing):
    from jarvis.gui.command_executor import CommandExecutor

    service, _, _ = sharing
    service.start()
    service.indicator_visible()
    audit = Mock()
    executor = CommandExecutor(SimpleNamespace(screen_sharing=service), audit)
    result = executor.submit_tool_blocking("stop_screen_sharing", {})
    assert result["ok"] and not service.state()["sharing"]
    assert executor._jobs.empty()
    audit.log.assert_called_once()


def test_native_indicator_is_visible_and_stop_works(sharing, qapp, tmp_path):
    from jarvis.gui.screen_sharing import ScreenSharingIndicator
    from PySide6.QtGui import QFontDatabase

    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")

    service, _, _ = sharing
    indicator = ScreenSharingIndicator(service)
    service.start()
    indicator.refresh()
    assert indicator.isVisible() and service.state()["ready"]
    assert indicator.label.text().startswith("SCREEN SHARING")
    assert indicator.grab().save(str(tmp_path / "sharing-indicator.png"))
    indicator.stop_button.click()
    assert not indicator.isVisible() and not service.state()["sharing"]
    indicator.shutdown()
    indicator.close()


@pytest.fixture
def editing(tmp_path):
    root = tmp_path / "Documents"
    root.mkdir()
    (root / "notes.txt").write_bytes(b"Hello Berk.\r\n")
    ai = Mock()
    ai.propose_text_edit.return_value = CommandResult(True, json.dumps({"replacement": "Hello, Berk.\n", "explanation": "Add the comma for direct address."}))
    files = FileSearchService(folders={"documents": root})
    service = FileEditing(files, LocalFileActions(folders=files.folders), ai)
    return service, root, ai


def test_propose_diff_then_save_actual_copy_preserves_original_and_newlines(editing):
    service, root, ai = editing
    result = service.propose("Documents/notes.txt", "Improve punctuation")
    assert result.ok and not result.metadata["saved"]
    assert "+Hello, Berk." in result.metadata["diff"]
    assert (root / "notes.txt").read_bytes() == b"Hello Berk.\r\n"
    assert not (root / "revised.txt").exists()
    saved = service.save_copy(result.metadata["proposal_id"], "Documents/revised.txt")
    assert saved.ok and saved.metadata["original_preserved"]
    assert (root / "revised.txt").read_bytes() == b"Hello, Berk.\r\n"
    assert (root / "notes.txt").read_bytes() == b"Hello Berk.\r\n"
    assert not service.preview().ok
    assert not list(root.glob(".jarvis-*"))


@pytest.mark.parametrize("problem", ["changed", "expired", "wrong_id", "discarded", "overwrite", "extension"])
def test_edit_save_refuses_stale_or_invalid_selection(editing, problem):
    service, root, _ = editing
    proposal = service.propose("Documents/notes.txt", "Improve punctuation")
    identifier = proposal.metadata["proposal_id"]
    destination = "Documents/revised.txt"
    if problem == "changed":
        (root / "notes.txt").write_text("User edited this", encoding="utf-8")
    elif problem == "expired":
        service._pending["created"] -= 301
    elif problem == "wrong_id":
        identifier = "invented"
    elif problem == "discarded":
        service.discard()
    elif problem == "overwrite":
        destination = "Documents/notes.txt"
    else:
        destination = "Documents/revised.exe"
    assert not service.save_copy(identifier, destination).ok
    assert not (root / "revised.txt").exists()


@pytest.mark.parametrize("name,content", [(".env.txt", "private"), ("credentials.txt", "private"),
                                           ("notes.txt", "password=example-password"),
                                           ("notes.txt", "x" * 64001), ("paper.docx", "binary")],
                         ids=["private-dotfile", "credentials-file", "embedded-secret", "oversized", "word-binary"])
def test_private_oversized_and_unsupported_files_never_reach_ai(editing, name, content):
    service, root, ai = editing
    (root / name).write_text(content, encoding="utf-8")
    assert not service.propose(f"Documents/{name}", "Improve").ok
    ai.propose_text_edit.assert_not_called()


@pytest.mark.parametrize("response", ['not JSON', '{"replacement":"New"}',
    json.dumps({"replacement": "password=example-password", "explanation": "change"}),
    json.dumps({"replacement": ["wrong type"], "explanation": "change"})])
def test_invalid_model_output_never_becomes_proposal(editing, response):
    service, _, ai = editing
    ai.propose_text_edit.return_value = CommandResult(True, response)
    assert not service.propose("Documents/notes.txt", "Improve").ok
    assert not service.preview().ok


def test_python_syntax_validation_does_not_execute_code(editing):
    service, root, ai = editing
    (root / "script.py").write_text("print('old')\n", encoding="utf-8")
    ai.propose_text_edit.return_value = CommandResult(True, json.dumps({"replacement": "def (", "explanation": "Invalid"}))
    assert not service.propose("Documents/script.py", "Fix").ok
    ai.propose_text_edit.return_value = CommandResult(True, json.dumps({"replacement": "raise RuntimeError('never execute')\n", "explanation": "Edit"}))
    assert service.propose("Documents/script.py", "Change code").ok


def test_cancellation_during_edit_generation_discards_proposal(editing):
    service, _, ai = editing
    response = ai.propose_text_edit.return_value
    ai.propose_text_edit.side_effect = lambda *a: (setattr(service, "cancelled", lambda: True), response)[1]
    assert not service.propose("Documents/notes.txt", "Improve").ok
    assert not service.preview().ok


def test_local_edit_and_screen_commands_share_confirmations(editing):
    _, root, ai = editing
    safety = SafetyPolicy()
    safety.confirm = Mock(return_value=True)
    router = CommandRouter(WindowsActions(), safety, ai=ai)
    router.files.folders = {"documents": root}
    router.actions.local_files.folders = router.files.folders
    assert router.handle('local edit file "Documents/notes.txt" to improve punctuation').ok
    assert router.handle('local save edited copy to "Documents/revised.txt"').ok
    assert safety.confirm.call_count == 2
    safety.confirm.return_value = False
    router.screen_sharing.indicator_available = True
    execute = RealtimeVoiceSession.tool_executor_from_router(router)
    assert not execute("start_screen_sharing", {})["ok"]
    assert not router.screen_sharing.state()["sharing"]
    router.workflow_runner.cancelled.set()
    assert execute("stop_screen_sharing", {})["ok"]


def test_readonly_native_edit_preview(sharing, qapp, tmp_path):
    from jarvis.gui.main_window import MainWindow
    from PySide6.QtGui import QFontDatabase

    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/consola.ttf")

    window = MainWindow()
    window.show_edit_preview("Improve punctuation\n--- notes.txt\n+++ revised/notes.txt\n-Hello Berk.\n+Hello, Berk.")
    assert window._edit_preview_text.isReadOnly()
    assert "+Hello, Berk." in window._edit_preview_text.toPlainText()
    assert window._edit_preview_dialog.grab().save(str(tmp_path / "edit-preview.png"))
    window._edit_preview_dialog.close()
    window.close()


def test_critical_policy_reaches_custom_realtime_instructions_and_chat(monkeypatch):
    import openai

    config = RealtimeVoiceConfig(instructions="Custom tone")
    assert CRITICAL_CONVERSATION_POLICY in config.session_update_event()["session"]["instructions"]
    monkeypatch.setenv("OPENAI_API_KEY", "example-key")
    create = Mock(return_value=SimpleNamespace(output_text="A counterargument", status="completed"))
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=create)))
    assert JarvisAI().answer_conversation("Debate me").ok
    assert CRITICAL_CONVERSATION_POLICY in create.call_args.kwargs["instructions"]


def test_vision_prompt_is_tool_free_and_treats_screen_as_untrusted(monkeypatch):
    import openai

    monkeypatch.setenv("OPENAI_API_KEY", "example-key")
    create = Mock(return_value=SimpleNamespace(output_text="Visible code", status="completed"))
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=create)))
    result = JarvisAI().describe_image_bytes(b"example-image", "Explain visible code")
    assert result.ok
    kwargs = create.call_args.kwargs
    assert kwargs["store"] is False and "tools" not in kwargs
    assert "untrusted data" in kwargs["instructions"]
    assert any(item["type"] == "input_image" for item in kwargs["input"][0]["content"])
