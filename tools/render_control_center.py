"""Render the native command palette and history using synthetic, isolated records."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from jarvis.audit import AuditLogger
from jarvis.gui.activity_center import ActivityCenter
from jarvis.gui.overlay import OverlayWidget
from jarvis.models import CommandResult
from jarvis.rollback import RollbackManager


app = QApplication([])
for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "segmdl2.ttf"):
    QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / name))
target = Path(__file__).resolve().parents[1] / "data" / "diagnostics"
target.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="control-fixture-", dir=target) as fixture:
    audit = AuditLogger(Path(fixture) / "audit.jsonl")
    audit.log("звук на 30", CommandResult(True, "Volume set to 30%.", action="set_volume",
              metadata={"intent_reason": "User requested volume at 30 percent.", "verification": "read_back"}), True,
              source="gui_overlay_local")
    rollback = RollbackManager(Path(fixture) / "rollback.json")
    rollback.push("Restore previous volume", "volume", {"percent": 50})
    center = ActivityCenter(audit, rollback)
    for page in (False, True):
        center.open_page(undo=page)
        for width, height in ((800, 540), (640, 440)):
            center.resize(width, height)
            QTest.qWait(100)
            center.grab().save(str(target / f"{'undo' if page else 'activity'}-{width}.png"))
    center.hide()
    overlay = OverlayWidget()
    overlay.mode.setCurrentIndex(2)
    overlay.show_result("1. Отвори Settings > System > Sound.\n2. Избери изходното устройство.\n3. Промени Volume и провери звука.", True)
    overlay.toggle()
    QTest.qWait(100)
    overlay.grab().save(str(target / "command-overlay.png"))
    overlay.hide()
print(target)
