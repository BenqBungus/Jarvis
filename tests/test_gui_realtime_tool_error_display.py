"""Tool errors during a live Realtime call must be visibly distinct from
routine transcript text and must not silently auto-clear after 9 seconds
(see RealtimeVoiceWorker.tool_error_occurred and
MainWindow.show_tool_error). Routed here rather than into
tests/test_gui_main_window.py, which is not in Claude's test-file scope
per TASK_SPLIT.md.

The one-line app.py wiring needed to connect these two pieces in the real
app (which Claude cannot edit) is filed in
docs/claude/INTEGRATION_REQUESTS.md.
"""

from __future__ import annotations

from jarvis.gui.main_window import MainWindow
from jarvis.gui.realtime_worker import RealtimeVoiceWorker


def test_show_tool_error_is_styled_as_a_persistent_error():
    window = MainWindow()
    try:
        window.show_tool_error("Tool output could not be sent")

        assert window._feedback_text == "Tool output could not be sent"
        assert window._feedback_error is True
        assert not window._feedback_timer.isActive()
    finally:
        window.deleteLater()


def test_show_tool_error_does_not_get_overwritten_by_the_routine_9s_clear():
    window = MainWindow()
    try:
        window.show_feedback("Heard: open notepad")
        assert window._feedback_timer.isActive()  # routine feedback does auto-clear

        window.show_tool_error("Tool output could not be sent")

        assert window._feedback_text == "Tool output could not be sent"
        assert not window._feedback_timer.isActive()
    finally:
        window.deleteLater()


def test_tool_error_signal_reaches_main_window_as_non_expiring_error_feedback(qapp, pump_events):
    window = MainWindow()
    # The session argument is never touched by _on_realtime_state's
    # tool_error branch (it only reads the event dict passed directly to
    # it), so a bare object() is enough here -- this test is specifically
    # about the signal-to-window wiring, not the worker's session lifecycle.
    worker = RealtimeVoiceWorker(object(), lambda *args: {})
    worker.tool_error_occurred.connect(window.show_tool_error)

    try:
        worker._on_realtime_state("tool_error", {"message": "Tool output could not be sent"})

        assert pump_events(lambda: window._feedback_text == "Tool output could not be sent", timeout=3)
        assert window._feedback_error is True
        assert not window._feedback_timer.isActive()
    finally:
        window.deleteLater()
