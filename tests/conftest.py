from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_LOAD_USER_OPENAI_API_KEY", "0")

import pytest


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    # Defaults such as data/conversation_history.jsonl must never reach the
    # running assistant's memory, settings, audit trail, or undo stack.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


@pytest.fixture(scope="session")
def qapp():
    """Shared QApplication for GUI tests. Only one may exist per process,
    so this is session-scoped and reused across every test that needs it."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def pump_events(qapp):
    """Returns a helper that processes the Qt event loop until `condition()`
    is true or `timeout` elapses -- needed to observe cross-thread queued
    signal delivery, which only happens while events are being processed."""

    def _pump(condition, timeout: float = 2.0) -> bool:
        deadline = time.time() + timeout
        while not condition() and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.005)
        return condition()

    return _pump
