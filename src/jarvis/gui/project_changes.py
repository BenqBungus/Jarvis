"""Desktop review boundary for AI proposals and project execution."""
import json
import threading

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QStyle, QTabWidget, QToolButton, QVBoxLayout)

from ..models import CommandResult
from ..project_checks import ProjectChecks
from ..project_repair import ProjectRepair
from .aurora import DialogHeader, set_glyph, set_role, style_dialog


class ProjectChangesDialog(QDialog):
    result_ready = Signal(object)
    verification_changed = Signal(str)

    def __init__(self, changes, parent=None, *, dry_run=False, ai=None):
        super().__init__(parent)
        self.changes = changes
        self.dry_run = dry_run
        self.running = False
        self.checks = None
        self.ai = ai
        self.repair = None
        self.worker = None
        self._last_id = None
        self._closed = False
        self.setWindowTitle("Jarvis | Project changes")
        self.resize(740, 620)
        self.setMinimumSize(480, 420)
        style_dialog(self, "projectChanges")  # the Aurora look (gui/aurora.py)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)
        layout.addWidget(DialogHeader("code", "Project changes",
                                      "Review AI patches before anything is written, then apply, undo or run checks."))
        self.allow = QCheckBox("Allow AI patch proposals")
        self.allow.setChecked(changes.enabled)
        self.allow.toggled.connect(self._allow_changed)
        layout.addWidget(self.allow)
        self.share_output = QCheckBox("Include check output in AI context")
        self.share_output.toggled.connect(self._share_output_changed)
        layout.addWidget(self.share_output)
        controls = QHBoxLayout()
        self.apply_button = QPushButton("Apply patch")
        set_role(self.apply_button, "", variant="primary")
        set_glyph(self.apply_button, "checkmark", QStyle.StandardPixmap.SP_DialogApplyButton, color="#04131A")
        self.apply_button.clicked.connect(self.apply_patch)
        controls.addWidget(self.apply_button)
        self.undo_button = QPushButton("Undo")
        set_glyph(self.undo_button, "undo", QStyle.StandardPixmap.SP_ArrowBack)
        self.undo_button.clicked.connect(self.undo_patch)
        controls.addWidget(self.undo_button)
        self.repair_button = QPushButton("Repair checks")
        set_glyph(self.repair_button, "sparkle", QStyle.StandardPixmap.SP_BrowserReload)
        self.repair_button.clicked.connect(self.start_repair)
        controls.addWidget(self.repair_button)
        controls.addStretch()
        layout.addLayout(controls)
        self.session_status = QLabel()
        set_role(self.session_status, "note")
        self.session_status.setWordWrap(True)
        layout.addWidget(self.session_status)
        self.tabs = QTabWidget()
        self.diff = QPlainTextEdit()
        self.diff.setReadOnly(True)
        set_role(self.diff, "code")
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        set_role(self.report, "code")
        self.tabs.addTab(self.diff, "Patch")
        self.tabs.addTab(self.report, "Checks")
        layout.addWidget(self.tabs, 1)
        test_row = QHBoxLayout()
        self.profile = QComboBox()
        self.profile.addItem("Python / JSON syntax", "syntax")
        self.profile.addItem("Python pytest", "pytest")
        test_row.addWidget(self.profile, 1)
        self.check_button = QPushButton("Run check")
        set_glyph(self.check_button, "play", QStyle.StandardPixmap.SP_MediaPlay)
        self.check_button.clicked.connect(self.run_check)
        test_row.addWidget(self.check_button)
        self.cancel_button = QToolButton()
        set_glyph(self.cancel_button, "cancel", QStyle.StandardPixmap.SP_MediaStop)
        set_role(self.cancel_button, "ghost")
        self.cancel_button.setFixedSize(34, 34)
        self.cancel_button.setToolTip("Cancel project check")
        self.cancel_button.setAccessibleName("Cancel project check")
        self.cancel_button.clicked.connect(self.cancel_check)
        test_row.addWidget(self.cancel_button)
        layout.addLayout(test_row)
        runtime_row = QHBoxLayout()
        self.runtime = QLineEdit()
        self.runtime.setReadOnly(True)
        self.runtime.setPlaceholderText("Python runtime")
        runtime_row.addWidget(self.runtime, 1)
        self.pick_runtime = QToolButton()
        set_glyph(self.pick_runtime, "folder", QStyle.StandardPixmap.SP_DirOpenIcon)
        set_role(self.pick_runtime, "ghost")
        self.pick_runtime.setFixedSize(34, 34)
        self.pick_runtime.setToolTip("Select Python executable for project tests")
        self.pick_runtime.setAccessibleName("Select Python executable for project tests")
        self.pick_runtime.clicked.connect(self._pick_runtime)
        runtime_row.addWidget(self.pick_runtime)
        layout.addLayout(runtime_row)
        self.result_ready.connect(self._on_result)
        self.timer = QTimer(self)
        self.timer.setInterval(400)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def _busy(self):
        return self.running or bool(getattr(self.parentWidget(), "_busy", False))

    @property
    def session_active(self):
        return self.running or (self.repair is not None and self.repair.active)

    def _allow_changed(self, enabled):
        self.changes.enabled = bool(enabled) and not self.changes.revoked
        if not enabled:
            self.cancel_check()
            self.changes.discard()
        self.refresh()

    def _share_output_changed(self, enabled):
        if not enabled:
            self.verification_changed.emit("Check output sharing disabled. Earlier output may refer to older file versions.")
            return
        answer = QMessageBox.question(self, "Share check output with AI",
            "Future project check output will be included in screen questions sent to OpenAI. "
            "Logs may contain private data even after recognized credentials are redacted. Enable only for non-sensitive output.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            self.share_output.setChecked(False)

    def refresh(self):
        if self.repair is not None:
            self.session_status.setText("Repair: " + self.repair.state.replace("_", " ")
                + f" | Checks {self.repair.check_count}/3 | Diagnoses {self.repair.diagnoses}/2")
        else:
            self.session_status.setText("Checking..." if self.running else "")
        self.session_status.setVisible(bool(self.session_status.text()))
        proposal = self.changes.preview()
        current = proposal["proposal_id"] if proposal else None
        if current != self._last_id:
            self._last_id = current
            self.diff.setPlainText(proposal["explanation"] + "\n\n" + proposal["diff"] if proposal else "")
        busy = self._busy() or self.changes.revoked
        reserved = busy or self.session_active
        self.allow.setEnabled(not reserved)
        self.share_output.setEnabled(not reserved)
        self.apply_button.setEnabled(bool(proposal) and not busy and not self.dry_run)
        self.undo_button.setEnabled(not reserved and not self.dry_run and self.changes.undo_available())
        self.check_button.setEnabled(not reserved and not self.dry_run)
        self.repair_button.setEnabled(not reserved and not self.dry_run and self.ai is not None
                                      and self.changes.enabled and not proposal)
        self.cancel_button.setEnabled(self.session_active)
        self.cancel_button.setToolTip("Cancel check or repair session")
        self.profile.setEnabled(not reserved)
        self.pick_runtime.setEnabled(not reserved)

    def apply_patch(self):
        proposal = self.changes.preview()
        if not proposal or self._busy() or self.dry_run or self.changes.revoked:
            return
        answer = QMessageBox.question(self, "Apply reviewed patch",
            "Apply the displayed edits and new files? Existing destinations will not be overwritten by new-file proposals. "
            "The previous state is recorded in .jarvis-undo.json, replacing the previous one-step undo record. "
            "Undo restores edited contents and removes only unchanged files created by this patch.\n\n"
            + "\n".join(("CREATE " if path in proposal.get("created_files", []) else "EDIT ") + path for path in proposal["files"]),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.repair is not None and self.repair.active:
            repair, proposal_id = self.repair, proposal["proposal_id"]
            self._run_repair(lambda: repair.approve(proposal_id, confirmed=True))
            return
        result = self.changes.apply(proposal["proposal_id"], confirmed=True)
        self._show_result(result)
        self.refresh()
        if result.ok:
            self._start_check("syntax", paths=result.metadata["files"])

    def undo_patch(self):
        if self._busy() or self.session_active or self.dry_run or self.changes.revoked:
            return
        answer = QMessageBox.question(self, "Undo project patch", "Restore previous contents and remove unchanged files created by the latest patch? "
            "Files changed or replaced since that patch will be preserved.", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            self._show_result(self.changes.undo(confirmed=True))
            self.refresh()

    def _pick_runtime(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select project Python runtime", "", "Python executable (python.exe python3.exe)")
        if path:
            self.runtime.setText(path)
            self.runtime.setToolTip(path)

    def run_check(self):
        if self._busy() or self.session_active or self.dry_run or self.changes.revoked:
            return
        profile = self.profile.currentData()
        if profile == "pytest":
            if not self.runtime.text():
                self._pick_runtime()
            if not self.runtime.text():
                return
            answer = QMessageBox.question(self, "Run project code",
                "pytest runs arbitrary code from this project and its dependencies with your Windows permissions. "
                "It is not sandboxed and may change files or access the network. Run only a project/runtime you trust. "
                "Timeout: 120 seconds. This is not permission to install packages.\n\nProject: " + str(self.changes.workspace.root)
                + "\nPython: " + self.runtime.text() + "\nCheck: pytest -q -p no:cacheprovider",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
        self._start_check(profile)

    def start_repair(self):
        if (self._busy() or self.session_active or self.dry_run or self.changes.revoked
                or not self.changes.enabled or self.changes.preview() or self.ai is None):
            return
        profile = self.profile.currentData()
        if profile == "pytest" and not self.runtime.text():
            self._pick_runtime()
            if not self.runtime.text():
                return
        warning = ("Run a bounded repair session in this selected project? Source excerpts and check output will be sent "
            "to OpenAI even if ordinary output sharing is off. Logs may contain private data despite credential redaction. "
            "Maximum: 2 AI diagnoses (up to 12 paid API requests), 3 checks, 15 minutes including review time. "
            "Each patch requires a separate review and approval. No package installation.\n\nProject: "
            + str(self.changes.workspace.root) + "\nCheck: " + profile)
        if profile == "pytest":
            warning += ("\nPython: " + self.runtime.text() + "\npytest runs arbitrary project/dependency code with your "
                "Windows permissions, including after each approved patch. It is NOT sandboxed. It can change files or "
                "access the network. Only approve trusted code. Each run stops after 120 seconds.")
        answer = QMessageBox.question(self, "Approve bounded project repair", warning,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.repair = ProjectRepair(self.changes, self.ai.diagnose_project_check,
                                    profile=profile, runtime=self.runtime.text())
        repair = self.repair
        self._run_repair(lambda: repair.start(confirmed=True))

    def _run_repair(self, operation):
        self.running = True
        self.report.setPlainText("Repair session running...")
        self.tabs.setCurrentWidget(self.report)
        self.refresh()
        def work():
            try:
                result = operation()
            except Exception:
                self.repair.cancel()
                result = CommandResult(False, "Repair stopped. No successful verification is recorded.")
            self.result_ready.emit(result)
        self.worker = threading.Thread(target=work, daemon=True, name="jarvis-project-repair")
        self.worker.start()

    def _start_check(self, profile, paths=None):
        self.running = True
        self.checks = ProjectChecks(self.changes.workspace)
        checks, runtime = self.checks, self.runtime.text()
        self.report.setPlainText("Running " + profile + "...")
        self.tabs.setCurrentWidget(self.report)
        self.refresh()
        def work():
            try:
                result = checks.syntax(paths) if profile == "syntax" else checks.pytest(runtime, confirmed=True)
            except Exception:
                result = CommandResult(False, "Project check failed; no successful verification is recorded.")
            self.result_ready.emit(result)
        self.worker = threading.Thread(target=work, daemon=True, name="jarvis-project-check")
        self.worker.start()

    def _on_result(self, result):
        self.running = False
        if self.repair is not None and self.repair.state == "cancelled" and result.metadata.get("repair_state"):
            result = CommandResult(False, "Repair cancelled. Already applied edits remain; use Undo for the latest patch.")
        if not self._closed and not self.changes.revoked:
            self._show_result(result)
            if self.repair is not None and self.repair.state == "awaiting_review":
                self.tabs.setCurrentWidget(self.diff)
        self.refresh()

    def _show_result(self, result):
        text = result.message + "\n\n" + json.dumps(result.metadata, ensure_ascii=True, indent=2)
        self.report.setPlainText(text)
        self.tabs.setCurrentWidget(self.report)
        context = text if self.share_output.isChecked() else result.message.splitlines()[0] + "\n" + json.dumps(result.metadata, ensure_ascii=True)
        self.verification_changed.emit(context[:8000])

    def cancel_check(self):
        if self.repair is not None:
            self.repair.cancel()
        if self.checks is not None:
            self.checks.cancel()
        if not self.running and self.repair is not None and self.repair.state == "cancelled":
            self.report.setPlainText("Repair cancelled. Already applied edits remain; use Undo for the latest patch.")
            self.tabs.setCurrentWidget(self.report)

    def closeEvent(self, event):
        self.cancel_check()
        super().closeEvent(event)

    def reject(self):
        self.cancel_check()
        super().reject()

    def shutdown(self):
        self._closed = True
        self.cancel_check()
        self.timer.stop()
        self.hide()
