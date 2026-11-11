from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QLabel, QLineEdit, QListWidget, QTabWidget, QWidget

from jarvis.gui.main_window import MainWindow, _DASHBOARD_LABELS


@pytest.fixture
def window(qapp):
    widget = MainWindow()
    widget.show()
    qapp.processEvents()
    yield widget
    widget.hide()
    widget.deleteLater()
    qapp.processEvents()


def test_main_surface_has_only_status_readiness_core_and_voice_controls(window):
    labels = {label.text() for label in window.findChildren(QLabel)}
    assert {"SYSTEM STATUS", "READINESS", "J.A.R.V.I.S"} <= labels
    assert not {"Conversation", "Quick actions", "Modes", "Tasks", "Tools", "Memory"} & labels
    assert not window.findChildren(QLineEdit)
    assert not window.findChildren(QListWidget)
    assert not window.findChildren(QTabWidget)
    assert set(window._dashboard_labels) == set(_DASHBOARD_LABELS)


def test_voice_profile_shows_english_instead_of_auto_detection(window):
    window.set_voice_mode_profile("cedar", "gpt-realtime-2.1")
    assert "English" in window._profile_label.text()
    assert "BG + EN" not in window._profile_label.text()
    assert "Language: English" in window._profile_label.toolTip()


@pytest.mark.parametrize("key", _DASHBOARD_LABELS)
def test_readings_are_updated_without_fake_values(window, key):
    assert window._dashboard_labels[key].text() == "Awaiting reading"
    window.update_dashboard(key, "42%")
    assert window._dashboard_labels[key].text() == "42%"
    window.update_dashboard("new_future_sensor", "ignored")


def test_voice_button_starts_and_ends_primary_live_call(window):
    calls = []
    window.realtime_start_requested.connect(lambda: calls.append("start"))
    window.realtime_stop_requested.connect(lambda: calls.append("stop"))
    assert not window._voice_button.isEnabled()
    window.set_realtime_status(True, "Ready to connect")
    window._voice_button.click()
    assert calls == ["start"]
    assert not window._voice_button.isChecked()
    window.set_realtime_active(True, "listening")
    window._voice_button.click()
    assert calls == ["start", "stop"]
    assert window._voice_button.isChecked()
    window.set_realtime_active(False, "idle")
    assert not window._voice_button.isChecked()


# --- Screen-sharing toggle (moved out of the buried Settings > Audio menu) ---


def test_screen_share_button_click_does_not_move_checked_state_before_confirmation(window):
    calls = []
    window.screen_sharing_requested.connect(lambda: calls.append(True))

    window._screen_share_button.click()

    assert calls == [True]
    # Same reasoning as the voice button: the click requests a start, but the
    # checked state must not move until set_screen_sharing_active confirms it
    # actually started (a failed start, e.g. AI vision unconfigured, must
    # never show "on").
    assert not window._screen_share_button.isChecked()


def test_set_screen_sharing_active_true_updates_button_and_dot(window):
    window.set_screen_sharing_active(True)

    assert window._screen_share_button.isChecked()
    assert window._screen_share_button.toolTip() == "Stop screen sharing"
    assert "#5ccb9a" in window._screen_share_dot.styleSheet()


def test_set_screen_sharing_active_false_updates_button_and_dot(window):
    window.set_screen_sharing_active(True)

    window.set_screen_sharing_active(False)

    assert not window._screen_share_button.isChecked()
    assert window._screen_share_button.toolTip() == "Start screen sharing"
    assert "#5c7277" in window._screen_share_dot.styleSheet()


def test_screen_share_button_starts_unchecked_with_the_neutral_dot_color():
    # Constructed fresh (not the shared `window` fixture) to confirm the
    # true initial state before any interaction, matching the pattern already
    # used for the voice button's initial-disabled assertion.
    from jarvis.gui.main_window import MainWindow

    widget = MainWindow()
    try:
        assert not widget._screen_share_button.isChecked()
        assert widget._screen_share_button.toolTip() == "Start screen sharing"
        assert "#5c7277" in widget._screen_share_dot.styleSheet()
    finally:
        widget.deleteLater()


@pytest.mark.parametrize(("state", "caption"), [
    ("connecting", "CONNECTING"), ("listening", "LISTENING"),
    ("thinking", "THINKING"), ("speaking", "SPEAKING"),
    ("interrupted", "LISTENING"), ("error", "VOICE ERROR"),
])
def test_transport_state_is_visible_and_not_overwritten_by_classic_poll(window, state, caption):
    window.set_realtime_active(state != "error", state)
    window.set_session_active(False)
    assert window._core_status_label.text() == caption
    if state != "error":
        window.set_mic_status("idle")
        assert window._core_status_label.text() == caption


def test_mute_control_and_privacy_status(window):
    requested = []
    window.input_mute_requested.connect(requested.append)
    window.set_realtime_active(True, "listening")
    assert window._privacy_label.text() == "MIC LIVE / OPENAI"
    window._mute_button.click()
    assert requested == [True]
    window.set_input_muted(True)
    assert window._core_status_label.text() == "MICROPHONE PAUSED"
    assert window._privacy_label.text() == "MIC PAUSED"
    window.set_realtime_active(False, "idle")
    assert not window._mute_button.isEnabled()
    assert window._privacy_label.text() == "MIC OFF"


def test_keyword_privacy_indicator_distinguishes_local_detection_from_cloud_streaming(window):
    window.set_realtime_active(True, "speaking")
    window.set_keyword_interrupt_status(True)
    assert window._privacy_label.text() == "LOCAL WAKE / JARVIS"
    window.set_input_muted(True)
    assert window._privacy_label.text() == "MIC PAUSED"
    window.set_input_muted(False)
    window.set_realtime_active(True, "interrupted")
    assert window._privacy_label.text() == "MIC LIVE / OPENAI"
    window.set_realtime_active(False, "idle")
    assert not window._keyword_interrupt_available
    assert window._privacy_label.text() == "MIC OFF"


def test_end_state_does_not_hide_failure_details(window):
    window.set_realtime_status(True, "Ready")
    window.set_realtime_detail("Audio output device unavailable")
    window.set_realtime_active(False, "error")
    assert window._feedback_error
    assert not window._feedback_timer.isActive()
    assert "device unavailable" in window._voice_transcript_label.toolTip()
    assert window._voice_button.isEnabled()


def test_feedback_is_transient_not_a_conversation_list(window):
    window.set_voice_transcript("Hello", "You")
    window.set_voice_transcript("Hello Berk", "Jarvis")
    assert window._voice_transcript_label.text() == "Jarvis: Hello Berk"
    assert window._feedback_timer.isActive()
    window._clear_feedback()
    assert not window._voice_transcript_label.text()
    window.append_history("tool", "request", "Failed to open browser", False)
    assert window._feedback_error
    assert not window._feedback_timer.isActive()


def test_readiness_distinguishes_setup_from_live_connection(window):
    window.set_setup_check("openai_key", True, "Key present; verified on connect")
    window.set_realtime_status(True, "Prerequisites installed")
    assert window._core_status_label.text() == "READY"
    assert window._privacy_label.text() == "MIC OFF"
    assert window._setup_rows["realtime_deps"][2].text() == "Ready to connect"
    window.set_setup_check("future", False, "ignored")


def test_settings_are_a_separate_hidden_dialog(window, qapp):
    settings = QWidget()
    window.set_settings_widget(settings)
    assert not window._settings_dialog.isVisible()
    window._settings_button.click()
    qapp.processEvents()
    assert window._settings_dialog.isVisible()
    assert settings.window() is window._settings_dialog
    window.close()
    assert not window.isVisible()
    assert not window._settings_dialog.isVisible()


def test_task_cancellation_remains_available_without_tasks_panel(window):
    calls = []
    window.cancel_task_requested.connect(lambda: calls.append(True))
    assert not window._cancel_task_button.isEnabled()
    window.set_task_state(True, "Opening shop")
    window._cancel_task_button.click()
    assert calls == [True]
    window.set_task_state(False, "Cancelled")
    assert not window._cancel_task_button.isEnabled()


def test_task_completion_preserves_actual_error_feedback(window):
    window.set_task_state(True, "Open browser")
    window.append_history("realtime", "open_url", "Opera executable unavailable", False)
    window.set_task_state(False, "Stopped / failed")
    assert window._feedback_text == "Opera executable unavailable"
    assert window._feedback_error


@pytest.mark.parametrize(("width", "height"), [(900, 660), (960, 720), (1360, 850), (1920, 1080)])
def test_layout_and_long_feedback_stay_inside_window(window, qapp, width, height):
    window.resize(width, height)
    window.show_feedback("W" * 3000)
    qapp.processEvents()
    window._elide_feedback()
    assert window.size().width() == width and window.size().height() == height
    for widget in (window._core, window._voice_button, window._mute_button,
                   window._cancel_task_button, window._voice_transcript_label):
        origin = widget.mapTo(window, QPoint(0, 0))
        assert window.rect().contains(origin)
        assert window.rect().contains(origin + QPoint(widget.width()-1, widget.height()-1))
    label = window._voice_transcript_label
    assert label.fontMetrics().horizontalAdvance(label.text()) <= label.width()


def test_native_core_is_nonblank_animated_and_stops_when_hidden(window, qapp):
    core = window._core
    assert core._timer.isActive()
    silent = core.grab().toImage()
    assert silent.pixelColor(silent.width()//2, silent.height()//2).green() > 30
    assert core._level == 0
    core.set_level(.8)
    for _ in range(8):
        core._animate()
    assert core._level > 0
    assert core.grab().toImage() != silent
    window.hide()
    qapp.processEvents()
    assert not core._timer.isActive()
