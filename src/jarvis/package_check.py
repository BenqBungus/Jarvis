"""Explicit offline packaging smoke check; no microphone, credentials or cloud calls."""
import io
import json
import os
import tempfile
from pathlib import Path


def main():
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["JARVIS_LOAD_USER_OPENAI_API_KEY"] = "0"
    os.environ.pop("OPENAI_API_KEY", None)
    report = {}
    try:
        from .gui import app as gui_app
        import openai
        import sounddevice
        import pyaudio
        import websockets
        import pocketsphinx
        import win32cred
        import win32job
        import pyttsx3.drivers.sapi5
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFontDatabase, QFont
        from PySide6.QtCore import QTimer
        from .gui.main_window import MainWindow
        from .gui.first_run_wizard import _ApiKeyPage
        from .gui.screen_chat import ScreenChatDialog
        from .documents import DocumentService
        from .files import FileSearchService
        from .local_file_actions import LocalFileActions
        from .project_workspace import ProjectWorkspace, ProjectReader
        from .project_changes import ProjectChanges
        from .project_checks import ProjectChecks
        from .project_repair import ProjectRepair
        from .models import CommandResult
        from .gui.project_changes import ProjectChangesDialog
        from .vision.project_analysis import PROJECT_TOOLS
        from PIL import Image, ImageDraw, ImageFont
        from docx import Document

        app = QApplication([])
        QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / "segoeui.ttf"))
        app.setFont(QFont("Segoe UI", 10))
        window = MainWindow()
        window.show()
        page = _ApiKeyPage()
        page.show()
        app.processEvents()
        window.grab().save("package-ui.png")
        page.grab().save("package-key-page.png")
        report["gui"] = window.isVisible() and page.isVisible()
        page.close()
        window.hide()
        screen_chat = ScreenChatDialog(dry_run=True)
        screen_chat.messages.setPlainText("You\nWhat does this error mean?\n\nJarvis\nThe function received an empty value. Check the input before using it.\n\nExample:\n    if value is None:\n        return\n\nThis is a rendering fixture, not a live screen analysis.")
        screen_chat.show()
        app.processEvents()
        screen_chat.grab().save("package-screen-chat.png")
        screen_chat.resize(440, 400)
        app.processEvents()
        screen_chat.grab().save("package-screen-chat-compact.png")
        report["screen_chat"] = screen_chat.isVisible() and screen_chat.sharing.ai.model == "gpt-5.6-sol"
        screen_chat.shutdown()
        document = Document()
        document.add_paragraph("Jarvis standalone Word extraction works.")
        data = io.BytesIO()
        document.save(data)
        service = DocumentService(FileSearchService(), LocalFileActions())
        result = service._extract(data.getvalue(), ".docx")
        report["word"] = "standalone" in result["blocks"][0]["text"]
        with Image.new("RGB", (1000, 180), "white") as image:
            ImageDraw.Draw(image).text((30, 50), "Jarvis standalone OCR works", fill="black",
                font=ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / "arial.ttf"), 42))
            data = io.BytesIO()
            image.save(data, format="PDF")
        result = service._extract(data.getvalue(), ".pdf")
        report["scanned_pdf"] = result["ocr_images"] == 1 and "standalone" in result["blocks"][0]["text"]
        report["voice_imports"] = True
        report["project_process_imports"] = hasattr(win32job, "AssignProcessToJobObject")
        from .tool_registry import ToolRegistry, ToolSpec, ToolParameter, ToolCall
        from .workflows import WorkflowRunner, WorkflowStep

        with tempfile.TemporaryDirectory(prefix="package-task-", dir=Path.cwd()) as root:
            source = Path(root) / "main.py"
            source.write_text("print('standalone project reader')\n", encoding="utf-8")
            reader = ProjectReader(ProjectWorkspace(root))
            read = reader.execute("read_project_file", {"path": "main.py", "start_line": 1})
            report["project_reader"] = ("standalone project reader" in read.get("text", "")
                and len(PROJECT_TOOLS) == 3
                and "error" in reader.execute("read_project_file", {"path": "../outside.py"}))
            changes = ProjectChanges(reader.workspace)
            changes.enabled = True
            proposal = changes.propose(reader, [{"path": "main.py", "old_text": "standalone project reader",
                "new_text": "standalone patch reader"}], "Synthetic package fixture: update the printed label.")
            review = ProjectChangesDialog(changes, dry_run=True)
            review.show()
            app.processEvents()
            review.grab().save("package-project-changes.png")
            review.resize(480, 420)
            app.processEvents()
            review.grab().save("package-project-changes-compact.png")
            review.shutdown()
            applied = changes.apply(proposal["proposal_id"], confirmed=True)
            syntax = ProjectChecks(reader.workspace).syntax(["main.py"])
            restored = changes.undo(confirmed=True)
            report["project_patch_undo"] = applied.ok and syntax.ok and restored.ok and "standalone project reader" in source.read_text()
            source.write_text("value =\n", encoding="utf-8")
            def diagnose_fixture(evidence, repair_reader):
                repair_reader.read_file("main.py")
                changes.propose(repair_reader, [{"path": "main.py", "old_text": "value =", "new_text": "value = 2"}],
                                "Synthetic package fixture: fix incomplete assignment.")
                return CommandResult(True, "Offline fixture proposal, not a live AI response.")
            repair = ProjectRepair(changes, diagnose_fixture)
            pending = repair.start(confirmed=True)
            repair_view = ProjectChangesDialog(changes, dry_run=True)
            repair_view.repair = repair
            repair_view.refresh()
            repair_view.show()
            app.processEvents()
            repair_view.grab().save("package-project-repair.png")
            repair_view.resize(480, 420)
            app.processEvents()
            repair_view.grab().save("package-project-repair-compact.png")
            repaired = repair.approve(repair.proposal_id, confirmed=True)
            report["project_repair_loop"] = pending.ok and repaired.ok and repair.state == "passed" and repair.check_count == 2
            repair_view.shutdown()
            new_reader = ProjectReader(changes.workspace, changes=changes)
            new_reader.list_files(".")
            new_reader.read_file("main.py")
            new_proposal = changes.propose(new_reader,
                [{"path": "main.py", "old_text": "value = 2", "new_text": "value = 3"}],
                "Synthetic fixture: edit an existing module and create a helper.",
                [{"path": "helper.py", "content": "answer = 42\n"}])
            new_view = ProjectChangesDialog(changes, dry_run=True)
            new_view.show()
            app.processEvents()
            new_view.grab().save("package-project-new-files.png")
            new_view.resize(480, 420)
            app.processEvents()
            new_view.grab().save("package-project-new-files-compact.png")
            new_view.shutdown()
            applied_new = changes.apply(new_proposal["proposal_id"], confirmed=True)
            checked_new = ProjectChecks(changes.workspace).syntax()
            restored_new = ProjectChanges(ProjectWorkspace(root)).undo(confirmed=True)
            report["project_new_file_undo"] = (applied_new.ok and checked_new.ok and restored_new.ok
                and not (Path(root) / "helper.py").exists() and source.read_text() == "value = 2\n")
            local_files = LocalFileActions(folders={"documents": Path(root)})
            registry = ToolRegistry()
            for name in ("create_local_folder", "create_local_file"):
                registry.register(ToolSpec(name, "Package check", permission="confirm",
                    parameters=(ToolParameter("path", "string", "Test path"),)), getattr(local_files, name))
            checked = WorkflowRunner(registry).run("package check", [
                WorkflowStep("Create test folder", ToolCall("create_local_folder", {"path": "Documents/Work"})),
                WorkflowStep("Create test file", ToolCall("create_local_file", {"path": "Documents/Work/Notes.txt"}))
            ], confirm=lambda *args: True)
            inspected = local_files.inspect_local_path("Documents/Work/Notes.txt")
            report["verified_local_task"] = (checked.ok and inspected.ok and inspected.metadata["exists"]
                and inspected.metadata["size_bytes"] == 0
                and all(item["status"] == "verified" for item in checked.metadata["completion_evidence"]))
        # Exercise the real object graph and shutdown, but do not run live
        # monitoring, audio capture or network checks during package QA.
        original_start = gui_app.BackgroundMonitor.start
        gui_app.BackgroundMonitor.start = lambda self: None
        try:
            _, components = gui_app.build_app(dry_run=True)
        finally:
            gui_app.BackgroundMonitor.start = original_start
        QTimer.singleShot(300, app.quit)
        app.exec()
        report["app_start_stop"] = not components["realtime_worker"].running
        report["ok"] = all(report.values())
    except Exception as exc:
        import traceback
        report.update(ok=False, error_type=type(exc).__name__, traceback=traceback.format_exc())
    Path("package-check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
