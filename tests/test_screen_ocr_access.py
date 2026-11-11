import io
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from jarvis.document_extract import extract_document
from jarvis.local_file_actions import LocalFileActions
from jarvis.models import CommandResult
from jarvis.safety import SafetyPolicy
from jarvis.trusted_actions import trusted_local_action
from jarvis.user_settings import JarvisSettings
from jarvis.vision.sharing import ScreenSharing


@pytest.mark.parametrize("value", [False, None, "true", "false", 1])
def test_full_access_requires_boolean_opt_in(value):
    settings = JarvisSettings(safety={"full_access_local": value})
    assert not trusted_local_action(settings, "end_process")


@pytest.mark.parametrize("prefix", ["", "Run Jarvis tool: ", "Run workflow step: ", "Run adaptive workflow step: "])
def test_trusted_local_actions_skip_terminal_prompt(prefix, monkeypatch):
    policy = SafetyPolicy()
    policy.settings = JarvisSettings(safety={"full_access_local": True})
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("Unexpected prompt"))
    assert policy.confirm(prefix + "end_process", "End the selected user app")
    assert policy.confirm(prefix + "recycle_local_path", "Recycle selected folder")


@pytest.mark.parametrize("action", ["start_screen_sharing", "analyze_document", "propose_file_edit",
    "shutdown", "disable_internet", "Run Jarvis tool: restart", "unknown_tool"])
def test_full_access_does_not_preauthorize_cloud_or_admin(action):
    assert not trusted_local_action(JarvisSettings(safety={"full_access_local": True}), action)


def test_gui_policy_uses_same_opt_in_and_stops_on_shutdown(monkeypatch):
    from jarvis.gui.gui_safety import GuiSafetyPolicy
    monkeypatch.setattr("jarvis.gui.gui_safety.QApplication.instance", lambda: None)
    policy = GuiSafetyPolicy(JarvisSettings(safety={"full_access_local": True}))
    assert policy.confirm("end_process", "test")
    policy.shutdown()
    assert not policy.confirm("end_process", "test")


@pytest.mark.parametrize("approve", [True, False])
def test_full_access_ui_requires_one_time_explicit_approval(qapp, tmp_path, monkeypatch, approve):
    from PySide6.QtWidgets import QMessageBox
    from jarvis.gui.settings_page import SettingsPage
    settings = JarvisSettings()
    path = tmp_path / "settings.json"
    page = SettingsPage(settings, settings_path=path)
    assert not page._full_access_checkbox.isChecked()
    prompt = Mock(return_value=QMessageBox.StandardButton.Yes if approve else QMessageBox.StandardButton.No)
    monkeypatch.setattr(QMessageBox, "warning", prompt)
    page._full_access_checkbox.setChecked(True)
    page._on_save()
    assert settings.safety["full_access_local"] is approve
    assert JarvisSettings.load(path).safety["full_access_local"] is approve
    prompt.assert_called_once()
    page._full_access_checkbox.setChecked(False)
    page._on_save()
    assert not settings.safety["full_access_local"]
    page.close()


def test_recycling_protects_roots_and_uses_no_permanent_fallback(tmp_path, monkeypatch):
    recycle = Mock()
    monkeypatch.setattr("jarvis.recycle.recycle_path", recycle)
    actions = LocalFileActions(folders={"documents": tmp_path})
    assert not actions.recycle_local_path(str(tmp_path)).ok
    assert not actions.recycle_local_path("ambiguous-name").ok
    recycle.assert_not_called()
    sample = tmp_path / "sample"
    sample.mkdir()
    actions.dry_run = True
    assert actions.recycle_local_path(str(sample)).ok
    recycle.assert_not_called()
    actions.dry_run = False
    recycle.side_effect = OSError("Cannot recycle")
    assert not actions.recycle_local_path(str(sample)).ok
    assert sample.is_dir()


def test_recycling_verifies_source_disappearance(tmp_path, monkeypatch):
    sample = tmp_path / "sample"
    sample.mkdir()
    recycled_fixture = tmp_path / "mock-trash"
    recycle = Mock(side_effect=lambda path: path.rename(recycled_fixture))
    monkeypatch.setattr("jarvis.recycle.recycle_path", recycle)
    result = LocalFileActions(folders={}).recycle_local_path(str(sample))
    assert result.ok and result.metadata["recycled"]
    assert not result.metadata["permanent_delete"]
    assert recycled_fixture.exists()


def test_screen_followups_compare_previous_frame_and_stop_forgets(monkeypatch):
    ai = Mock()
    ai.describe_image_bytes.return_value = CommandResult(True, "An error is visible")
    sharing = ScreenSharing(ai)
    sharing.indicator_available = True
    monkeypatch.setattr(sharing, "_snapshot", Mock(side_effect=[b"first", b"second", b"third"]))
    sharing.start()
    sharing.indicator_visible()
    assert sharing.ask("What is wrong?").ok
    result = sharing.ask("Did I fix it?")
    assert result.ok and result.metadata["compared_previous_snapshot"]
    assert ai.describe_image_bytes.call_args.kwargs["previous_image"] == b"first"
    assert ai.describe_image_bytes.call_args.kwargs["history"][0][0] == "What is wrong?"
    sharing.stop()
    assert sharing._previous_frame is None and not sharing._history
    sharing.start()
    sharing.indicator_visible()
    assert sharing.ask("New task").ok
    assert not ai.describe_image_bytes.call_args.kwargs


def test_screen_stop_clears_context(monkeypatch):
    sharing = ScreenSharing(Mock())
    sharing._previous_frame, sharing._history = b"private", [("question", "answer")]
    sharing.stop()
    assert sharing._previous_frame is None and not sharing._history


def scan_image():
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (1000, 180), "white")
    ImageDraw.Draw(image).text((30, 50), "Jarvis reads scanned documents", fill="black",
        font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 42))
    return image


@pytest.mark.skipif(os.name != "nt", reason="Local Windows OCR integration")
@pytest.mark.parametrize("extension", [".pdf", ".docx"])
def test_real_scanned_pdf_and_word_image_ocr(extension):
    pytest.importorskip("winrt.windows.media.ocr")
    output = io.BytesIO()
    with scan_image() as image:
        if extension == ".pdf":
            image.save(output, format="PDF")
        else:
            from docx import Document
            png = io.BytesIO()
            image.save(png, format="PNG")
            doc = Document()
            doc.add_picture(io.BytesIO(png.getvalue()))
            doc.save(output)
    result = extract_document(output.getvalue(), extension)
    assert result["ocr_images"] == 1
    assert "Jarvis reads scanned documents" in " ".join(b["text"] for b in result["blocks"])
    assert "OCR" in result["coverage"]


def test_ocr_fallback_is_bounded_and_partial(monkeypatch):
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(10):
        writer.add_blank_page(width=400, height=400)
    output = io.BytesIO()
    writer.write(output)
    read = Mock(return_value="Recognized sample")
    monkeypatch.setattr("jarvis.ocr.pdf_page_text", read)
    result = extract_document(output.getvalue(), ".pdf")
    assert result["partial"] and read.call_count == 8
    assert result["ocr_images"] == 8


def test_realtime_and_local_recycling_use_trusted_setting(tmp_path, monkeypatch):
    from jarvis.router import CommandRouter
    from jarvis.windows_actions import WindowsActions
    from jarvis.realtime import RealtimeVoiceSession
    settings = JarvisSettings(safety={"full_access_local": True})
    router = CommandRouter(WindowsActions(dry_run=True), SafetyPolicy(), settings=settings)
    folder = tmp_path / "sample"
    folder.mkdir()
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("Unexpected repeated approval"))
    result = router.local_commands.resource_command(f'delete folder "{folder}"')
    assert result.ok and result.metadata["approval_source"] == "trusted_local_setting"
    live = RealtimeVoiceSession.tool_executor_from_router(router)
    result = live("recycle_local_path", {"path": str(folder)})
    assert result["ok"] and folder.exists()


def test_vision_comparison_request_is_labeled_and_bounded(monkeypatch):
    import openai
    from jarvis.ai_client import JarvisAI
    monkeypatch.setenv("OPENAI_API_KEY", "example-key")
    create = Mock(return_value=SimpleNamespace(status="completed", output_text="Visible change"))
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: SimpleNamespace(responses=SimpleNamespace(create=create)))
    result = JarvisAI().describe_image_bytes(b"new", "Compare", previous_image=b"old", history=[("q", "a")])
    assert result.ok
    request = create.call_args.kwargs
    assert not request["store"] and "tools" not in request
    content = request["input"][0]["content"]
    assert len([i for i in content if i["type"] == "input_image"]) == 2
    assert any("PREVIOUS" in i.get("text", "") for i in content)
    assert any("CURRENT" in i.get("text", "") for i in content)


def test_recycle_com_aborts_nonrecyclable_items(monkeypatch):
    import pythoncom
    from win32com.shell import shell, shellcon
    from win32com.server.exception import COMException
    from jarvis.recycle import recycle_path
    operation = Mock()
    operation.PerformOperations.return_value = 0
    operation.GetAnyOperationsAborted.return_value = False
    monkeypatch.setattr(pythoncom, "CoInitialize", Mock())
    monkeypatch.setattr(pythoncom, "CoUninitialize", Mock())
    monkeypatch.setattr(pythoncom, "CoCreateInstance", lambda *a: operation)
    monkeypatch.setattr(pythoncom, "WrapObject", lambda obj, *a: obj)
    monkeypatch.setattr(shell, "SHCreateItemFromParsingName", lambda *a: Mock())
    recycle_path("C:/fixture")
    sink = operation.DeleteItem.call_args.args[1]
    with pytest.raises(COMException):
        sink.PreDeleteItem(0, Mock())
    assert sink.PreDeleteItem(shellcon.TSF_DELETE_RECYCLE_IF_POSSIBLE, Mock()) == 0
    assert operation.SetOperationFlags.call_args.args[0] & 0x00080000


def test_full_access_control_renders_without_clipping(qapp, tmp_path):
    from PySide6.QtGui import QFontDatabase, QFont
    from PySide6.QtWidgets import QGroupBox
    from jarvis.gui.settings_page import SettingsPage
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    page = SettingsPage(JarvisSettings(), settings_path=tmp_path / "settings.json")
    page.setFont(QFont("Segoe UI", 10))
    page.resize(760, page.sizeHint().height())
    page.show()
    qapp.processEvents()
    group = next(g for g in page.findChildren(QGroupBox) if g.title() == "Safety confirmations")
    control = page._full_access_checkbox
    assert control.width() >= control.sizeHint().width()
    assert group.grab().save(str(tmp_path / "trusted-access.png"))
    page.close()
