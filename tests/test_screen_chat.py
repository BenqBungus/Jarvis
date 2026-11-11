import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtWidgets import QMessageBox

from jarvis.gui.screen_chat import ScreenChatDialog, SCREEN_CHAT_MODEL
from jarvis.models import CommandResult
from jarvis.vision.sharing import ScreenSharing
from jarvis.project_workspace import ProjectWorkspace


def pump(qapp, predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def start(dialog, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr("jarvis.gui.screen_chat.ensure_openai_api_key_visible", lambda: None)
    dialog.open_chat()
    dialog._toggle_share()
    assert dialog.sharing.state()["ready"]


def test_screen_model_follows_configured_model(qapp, monkeypatch):
    monkeypatch.setenv("JARVIS_OPENAI_MODEL", "different-model")
    dialog = ScreenChatDialog(dry_run=True)
    try:
        assert dialog.sharing.ai.model == "different-model"
        assert dialog.model_label.text() == "different-model"
        assert dialog.sharing.chat_only
        assert dialog.sharing.dry_run
    finally:
        dialog.shutdown()


def test_selected_project_reaches_ai_and_clear_revokes_access(qapp, monkeypatch, tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    (root / "main.py").write_text("print('fixture')")
    def answer(*args, **kwargs):
        reader = kwargs["project_reader"]
        result = reader.execute("read_project_file", {"path": "main.py", "start_line": 1})
        assert "fixture" in result["text"]
        return CommandResult(True, "main.py:1 prints fixture. No files changed.")
    ai = Mock()
    ai.describe_image_bytes.side_effect = answer
    dialog = ScreenChatDialog(ai=ai)
    monkeypatch.setattr("jarvis.gui.screen_chat.QFileDialog.getExistingDirectory", lambda *args: str(root))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(dialog.sharing, "_snapshot", lambda: b"fixture-screen")
    try:
        dialog._select_project()
        assert dialog._project.root == root
        start(dialog, monkeypatch)
        dialog.question.setText("Inspect the source behind this error")
        dialog.send_question()
        pump(qapp, lambda: not dialog._busy)
        assert dialog._actions[0]["tool"] == "read_project_file"
        assert "No files changed" in dialog.messages.toPlainText()
        dialog.clear_chat()
        assert dialog._project is None
        assert not dialog._actions
        assert not dialog.sharing.state()["sharing"]
    finally:
        dialog.shutdown()


def test_declining_project_consent_never_grants_access(qapp, monkeypatch, tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    dialog = ScreenChatDialog(ai=Mock())
    monkeypatch.setattr("jarvis.gui.screen_chat.QFileDialog.getExistingDirectory", lambda *args: str(root))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    try:
        dialog._select_project()
        assert dialog._project is None
        dialog.sharing.ai.describe_image_bytes.assert_not_called()
    finally:
        dialog.shutdown()


def test_removing_project_during_analysis_prevents_next_read(qapp, monkeypatch, tmp_path):
    root = tmp_path / "demo"
    root.mkdir()
    entered, release = threading.Event(), threading.Event()
    readers = []
    def answer(*args, **kwargs):
        readers.append(kwargs["project_reader"])
        entered.set()
        release.wait(3)
        with pytest.raises(ValueError, match="cancelled"):
            readers[0].execute("list_project_files", {"path": "."})
        return CommandResult(True, "STALE PROJECT ANSWER")
    ai = Mock()
    ai.describe_image_bytes.side_effect = answer
    dialog = ScreenChatDialog(ai=ai)
    monkeypatch.setattr(dialog.sharing, "_snapshot", lambda: b"fixture-screen")
    try:
        dialog._project = ProjectWorkspace(root)
        start(dialog, monkeypatch)
        dialog.question.setText("Inspect project")
        dialog.send_question()
        pump(qapp, entered.is_set)
        dialog._remove_project()
        release.set()
        pump(qapp, lambda: not dialog._busy)
        assert dialog._project is None
        assert not dialog._actions
        assert "STALE" not in dialog.messages.toPlainText()
    finally:
        release.set()
        dialog.shutdown()


def test_missing_icon_font_uses_native_icon_fallback(qapp, monkeypatch):
    from jarvis.gui.icons import control_icon, QFontDatabase
    from PySide6.QtWidgets import QStyle
    monkeypatch.setattr(QFontDatabase, "families", lambda: [])
    style = qapp.style()
    from PySide6.QtGui import QPixmap, QIcon
    from PySide6.QtCore import Qt
    pixmap = QPixmap(24, 24)
    pixmap.fill(Qt.GlobalColor.white)
    fallback = Mock(return_value=QIcon(pixmap))
    fake_style = SimpleNamespace(standardIcon=fallback)
    icon = control_icon(fake_style, QStyle.StandardPixmap.SP_ArrowForward)
    assert not icon.isNull()
    fallback.assert_called_once_with(QStyle.StandardPixmap.SP_ArrowForward)


def test_sharing_consent_no_capture_before_question_and_no_realtime_feed(qapp, monkeypatch):
    ai = Mock()
    dialog = ScreenChatDialog(ai=ai)
    capture = Mock(return_value=b"frame")
    monkeypatch.setattr(dialog.sharing, "_snapshot", capture)
    try:
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
        monkeypatch.setattr("jarvis.gui.screen_chat.ensure_openai_api_key_visible", lambda: None)
        dialog._toggle_share()
        assert not dialog.sharing.state()["sharing"]
        start(dialog, monkeypatch)
        assert "SCREEN CHAT" in dialog.indicator.label.text()
        assert dialog.sharing.state()["capture_mode"] == "chat_on_question"
        with pytest.raises(ValueError):
            dialog.sharing.frame_for_live()
        capture.assert_not_called()
        ai.describe_image_bytes.assert_not_called()
    finally:
        dialog.shutdown()


def test_chat_uses_fresh_images_and_history_without_dispatching_commands(qapp, monkeypatch):
    ai = Mock()
    ai.describe_image_bytes.return_value = CommandResult(True, "I can explain this, but cannot close apps.")
    dialog = ScreenChatDialog(ai=ai)
    capture = Mock(side_effect=[b"first", b"second"])
    monkeypatch.setattr(dialog.sharing, "_snapshot", capture)
    try:
        start(dialog, monkeypatch)
        dialog.question.setText("Close the app and delete this folder")
        dialog.send_question()
        pump(qapp, lambda: not dialog._busy)
        assert ai.describe_image_bytes.call_args.args == (b"first", "Close the app and delete this folder")
        assert dialog.isVisible()
        assert "cannot close apps" in dialog.messages.toPlainText()
        dialog.question.setText("What changed?")
        dialog.send_question()
        pump(qapp, lambda: not dialog._busy)
        assert ai.describe_image_bytes.call_args.args[0] == b"second"
        assert ai.describe_image_bytes.call_args.kwargs["previous_image"] == b"first"
        assert ai.describe_image_bytes.call_args.kwargs["history"]
        assert not hasattr(dialog, "executor")
    finally:
        dialog.shutdown()


def test_stop_discards_late_reply_and_clears_screen_context(qapp, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    def answer(*args, **kwargs):
        entered.set()
        release.wait(3)
        return CommandResult(True, "STALE ANSWER")
    dialog = ScreenChatDialog(ai=SimpleNamespace(describe_image_bytes=answer))
    monkeypatch.setattr(dialog.sharing, "_snapshot", lambda: b"frame")
    try:
        start(dialog, monkeypatch)
        dialog.question.setText("Explain")
        dialog.send_question()
        pump(qapp, entered.is_set)
        dialog.stop_sharing()
        release.set()
        pump(qapp, lambda: not dialog._busy)
        assert "STALE ANSWER" not in dialog.messages.toPlainText()
        assert dialog.sharing._history == [] and dialog.sharing._previous_frame is None
        assert not dialog.send.isEnabled()
    finally:
        release.set()
        if dialog._thread:
            dialog._thread.join(3)
        dialog.shutdown()


def test_clear_before_delayed_capture_never_sends(qapp, monkeypatch):
    ai = Mock()
    dialog = ScreenChatDialog(ai=ai)
    capture = Mock(return_value=b"frame")
    monkeypatch.setattr(dialog.sharing, "_snapshot", capture)
    try:
        start(dialog, monkeypatch)
        dialog.question.setText("Explain")
        dialog.send_question()
        dialog.clear_chat()
        pump(qapp, lambda: not dialog._busy)
        capture.assert_not_called()
        ai.describe_image_bytes.assert_not_called()
        assert dialog.messages.toPlainText() == ""
    finally:
        dialog.shutdown()


def test_escape_stops_and_reopening_does_not_restart_sharing(qapp, monkeypatch):
    dialog = ScreenChatDialog(ai=Mock())
    try:
        start(dialog, monkeypatch)
        dialog.reject()
        assert not dialog.sharing.state()["sharing"]
        assert not dialog.isVisible()
        dialog.open_chat()
        assert not dialog.sharing.state()["sharing"]
        assert not dialog.send.isEnabled()
    finally:
        dialog.shutdown()


def test_capture_failure_restores_chat_and_is_not_saved_in_history(qapp, monkeypatch):
    dialog = ScreenChatDialog(ai=Mock())
    monkeypatch.setattr(dialog.sharing, "_snapshot", Mock(side_effect=OSError("capture failed")))
    try:
        start(dialog, monkeypatch)
        dialog.question.setText("Explain")
        dialog.send_question()
        pump(qapp, lambda: not dialog._busy)
        assert dialog.isVisible()
        assert "failed" in dialog.messages.toPlainText().lower()
        assert not dialog.sharing._history
    finally:
        dialog.shutdown()


def test_screen_ai_request_has_no_tools_and_correct_model(monkeypatch):
    from jarvis.ai_client import JarvisAI
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    request = Mock(return_value=SimpleNamespace(status="completed", output_text="Visible code", model=SCREEN_CHAT_MODEL))
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: SimpleNamespace(responses=SimpleNamespace(create=request)))
    ai = JarvisAI()
    ai.model = SCREEN_CHAT_MODEL
    assert ai.describe_image_bytes(b"sample-image", "Explain").ok
    payload = request.call_args.kwargs
    assert payload["model"] == SCREEN_CHAT_MODEL
    assert not payload.get("tools") and payload["store"] is False
    assert "no tools" in payload["instructions"]


@pytest.mark.parametrize("status, expected", [(401, "key was rejected"), (403, "permission"),
                                             (404, "unavailable"), (429, "quota or rate limit")])
def test_screen_errors_are_actionable_and_do_not_leak_provider_body(monkeypatch, status, expected):
    from jarvis.ai_client import JarvisAI
    import openai
    monkeypatch.setenv("OPENAI_API_KEY", "test-placeholder")
    error = RuntimeError("PRIVATE SCREEN TEXT AND KEY MUST NOT APPEAR")
    error.status_code = status
    close = Mock()
    request = Mock(side_effect=error)
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=request), close=close))
    result = JarvisAI().describe_image_bytes(b"image", "Explain")
    assert not result.ok and expected in result.message
    assert "PRIVATE SCREEN" not in str(result)
    close.assert_called_once()


def test_retry_is_explicit_and_uses_new_image(qapp, monkeypatch):
    ai = Mock()
    ai.describe_image_bytes.side_effect = [CommandResult(False, "Temporary error"), CommandResult(True, "Recovered")]
    dialog = ScreenChatDialog(ai=ai)
    capture = Mock(side_effect=[b"first", b"second"])
    monkeypatch.setattr(dialog.sharing, "_snapshot", capture)
    try:
        start(dialog, monkeypatch)
        dialog.question.setText("Explain")
        dialog.send_question()
        pump(qapp, lambda: not dialog._busy)
        assert dialog.retry.isEnabled() and capture.call_count == 1
        dialog.retry.click()
        pump(qapp, lambda: not dialog._busy)
        assert ai.describe_image_bytes.call_args.args == (b"second", "Explain")
        assert not dialog.retry.isEnabled()
    finally:
        dialog.shutdown()


def test_pending_repair_blocks_screen_questions_and_stop_discards(qapp, monkeypatch, tmp_path):
    from jarvis.project_repair import ProjectRepair
    root = tmp_path / "demo"
    root.mkdir()
    (root / "main.py").write_text("value =\n")
    dialog = ScreenChatDialog(ai=Mock())
    monkeypatch.setattr("jarvis.gui.screen_chat.QFileDialog.getExistingDirectory", lambda *args: str(root))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    capture = Mock(return_value=b"fixture")
    monkeypatch.setattr(dialog.sharing, "_snapshot", capture)
    try:
        dialog._select_project()
        start(dialog, monkeypatch)
        changes = dialog._changes
        changes.enabled = True
        def diagnose(evidence, reader):
            reader.read_file("main.py")
            changes.propose(reader, [{"path": "main.py", "old_text": "value =", "new_text": "value = 2"}], "Fixture.")
            return CommandResult(True, "Fixture.")
        panel = dialog._project_panel
        panel.repair = ProjectRepair(changes, diagnose)
        assert panel.repair.start(confirmed=True).ok
        dialog._sync()
        dialog.question.setText("New question")
        dialog.send_question()
        assert not dialog._busy and not dialog.send.isEnabled()
        capture.assert_not_called()
        dialog.stop_sharing()
        assert changes.preview() is None and not panel.session_active
    finally:
        dialog.shutdown()
