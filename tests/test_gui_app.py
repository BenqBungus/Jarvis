from __future__ import annotations

import pytest

from jarvis.gui import app as gui_app
from jarvis.monitoring import checks


@pytest.fixture(autouse=True)
def isolated_gui_data(tmp_path, monkeypatch):
    # Settings toggles and command audits must never write the user's live data.
    monkeypatch.chdir(tmp_path)


class _FakeTts:
    """Deterministic stand-in so this test never depends on whether pyttsx3
    happens to be installed (and never actually speaks out loud during a
    test run)."""

    enabled = False

    def speak(self, *args, **kwargs):
        return False


class _EnabledFakeTts:
    enabled = True

    def status_summary(self):
        return {
            "enabled": True,
            "provider": "openai",
            "openai_key_present": True,
            "openai_model": "gpt-4o-mini-tts",
            "openai_voice": "cedar",
            "windows_fallback_available": False,
            "available_languages": [],
        }

    def speak(self, text, lang=None):
        return True


def test_build_app_keeps_command_execution_and_dashboard_without_history_panel(qapp, pump_events, monkeypatch):
    # Keep BackgroundMonitor's real threads fast and side-effect-free --
    # build_app() always starts real monitoring threads.
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(80, True, True))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(
        checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading("NVIDIA GeForce RTX", "1.2.3", True)
    )
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(0, True))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    window = components["window"]
    executor = components["executor"]

    try:
        window.command_submitted.emit("jarvis отвори facebook", "text")

        assert pump_events(lambda: "facebook" in window._feedback_text.lower(), timeout=3)
        assert not hasattr(window, "_history")

        # Dashboard should populate from the (monkeypatched, fast) monitor readings
        # -- BackgroundMonitor runs every check once immediately on start().
        assert pump_events(lambda: "80%" in window._dashboard_labels["battery"].text(), timeout=3)
        assert pump_events(lambda: "connected" in window._dashboard_labels["internet"].text(), timeout=3)
    finally:
        components["monitor"].stop()
        executor.stop()
        components["speech"].stop()


def test_build_app_shows_main_window_on_startup(qapp, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        assert components["window"].isVisible() is True
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_queues_english_startup_greeting_when_not_dry_run(qapp, pump_events, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _EnabledFakeTts())
    spoken: list[tuple[str, str | None]] = []
    original_request_speak = gui_app.SpeechService.request_speak

    def record_request_speak(self, text, lang=None):
        spoken.append((text, lang))
        return original_request_speak(self, text, lang)

    monkeypatch.setattr(gui_app.SpeechService, "request_speak", record_request_speak)

    app, components = gui_app.build_app(dry_run=False)
    try:
        assert pump_events(lambda: ("Hello Berk, how can I help you?", "en") in spoken, timeout=3)
        assert "Jarvis: Hello Berk" in components["window"]._voice_transcript_label.text()
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_realtime_states_map_to_tray_voice_states():
    assert gui_app._tray_state_for_realtime("connecting") == "processing"
    assert gui_app._tray_state_for_realtime("thinking") == "processing"
    assert gui_app._tray_state_for_realtime("speaking") == "processing"
    assert gui_app._tray_state_for_realtime("listening") == "listening"
    assert gui_app._tray_state_for_realtime("interrupted") == "unclear"
    assert gui_app._tray_state_for_realtime("error") == "unclear"
    assert gui_app._tray_state_for_realtime("idle") == "idle"


@pytest.mark.parametrize("websocket,audio", [(True, True), (True, False), (False, True), (False, False)])
def test_realtime_dependency_details_do_not_mistake_missing_devices_for_missing_packages(websocket, audio):
    ready, detail = gui_app._realtime_dependency_check({
        "websocket_available": websocket, "audio_stream_available": audio,
    })
    assert ready == (websocket and audio)
    assert ("microphone/speaker unavailable" in detail) == (not audio)
    assert ("websockets unavailable" in detail) == (not websocket)
    assert "install websockets and sounddevice" not in detail
    if ready:
        assert "devices detected" in detail
    else:
        assert "Voice Doctor" in detail


def test_built_app_displays_redacted_persistent_tool_error_and_honest_audio_readiness(qapp, monkeypatch):
    monkeypatch.setattr(gui_app.BackgroundMonitor, "start", lambda self: None)
    monkeypatch.setattr(gui_app, "TextToSpeech", lambda *args, **kwargs: _FakeTts())
    monkeypatch.setattr(gui_app.RealtimeVoiceSession, "readiness", lambda self: {
        "api_key_present": False, "websocket_available": True, "audio_stream_available": False,
        "ready": False, "missing": ["OPENAI_API_KEY", "sounddevice"],
        "model": "fixture-model", "voice": "fixture-voice", "sample_rate": 24000,
    })
    _, components = gui_app.build_app(dry_run=True)
    window, worker = components["window"], components["realtime_worker"]
    try:
        assert "microphone/speaker unavailable" in window._setup_rows["realtime_deps"][2].text()
        worker._on_realtime_state("tool_error", {"message": "Tool failed: sk-" + "x" * 40})
        assert "Tool failed" in window._feedback_text
        assert "x" * 40 not in window._feedback_text
        assert window._feedback_error is True
        assert not window._feedback_timer.isActive()
        worker.state_changed.emit("listening")
        components["session_poll_timer"].timeout.emit()
        assert window._feedback_error is True
        assert not window._feedback_timer.isActive()
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()
        components["session_poll_timer"].stop()
        components["screen_chat"].shutdown()
        components["sharing_indicator"].shutdown()
        components["safety"].shutdown()
        components["tray"]._icon.hide()
        window.hide()


def test_live_call_does_not_repeat_completed_startup_greeting(qapp, pump_events, monkeypatch):
    callbacks = []
    monkeypatch.setattr(gui_app.QTimer, "singleShot", lambda _delay, fn: callbacks.append(fn))
    monkeypatch.setattr(gui_app.BackgroundMonitor, "start", lambda self: None)
    monkeypatch.setattr(gui_app, "TextToSpeech", lambda *args, **kwargs: _EnabledFakeTts())
    _, components = gui_app.build_app(dry_run=False)
    try:
        for callback in callbacks:
            callback()
        assert pump_events(lambda: components["speech"]._idle.is_set())
        worker = components["realtime_worker"]
        monkeypatch.setattr(worker, "start", lambda: True)
        components["window"].realtime_start_requested.emit()
        assert worker._session.config.greeting == ""
        assert components["speech"].request_speak("No parallel classic voice") is None
        worker._on_stopped()
        assert components["speech"].request_speak("Classic voice is available again") is not None
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()
        components["session_poll_timer"].stop()


def test_interrupt_button_targets_speech_without_ending_call_or_cancelling_tasks(qapp, monkeypatch):
    monkeypatch.setattr(gui_app.BackgroundMonitor, "start", lambda self: None)
    monkeypatch.setattr(gui_app, "TextToSpeech", lambda *args, **kwargs: _FakeTts())
    _, components = gui_app.build_app(dry_run=True)
    worker, window = components["realtime_worker"], components["window"]
    try:
        with worker._lock:
            worker._running = True
        window.set_realtime_active(True, "speaking")
        assert window._privacy_label.text() == "MIC PAUSED"
        window._interrupt_button.click()
        assert worker._session._interrupt_requested.is_set()
        assert worker.running
        assert not worker._stop_requested.is_set()
        window.set_speaker_guard(False)
        window.set_realtime_active(True, "speaking")
        assert window._privacy_label.text() == "MIC LIVE / OPENAI"
    finally:
        with worker._lock:
            worker._running = False
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()
        components["session_poll_timer"].stop()


def test_build_app_sets_window_on_safety_policy_for_confirmation_dialogs(qapp, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        # If set_window() were never called, GuiSafetyPolicy._show_dialog would
        # try to show/raise/activate None -- confirm it's wired to the real window.
        assert components["safety"]._window is components["window"]
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_wires_mic_state_to_tray_and_window(qapp, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        # Real hardware/mic threads aren't running in this test environment
        # (no SpeechRecognition installed) -- exercise the wiring directly by
        # emitting the same signal a real listen cycle would emit.
        components["voice_worker"].state_changed.emit("listening")
        assert components["tray"].current_state() == "listening"
        assert components["window"]._core_status_label.text() == "LISTENING"

        components["push_to_talk"].state_changed.emit("processing")
        assert components["tray"].current_state() == "processing"
        assert components["window"]._core_status_label.text() == "WORKING"

        components["realtime_worker"].state_changed.emit("speaking")
        assert components["tray"].current_state() == "processing"
        assert components["window"]._core_status_label.text() == "SPEAKING"
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_wires_push_to_talk_button_to_push_to_talk_worker(qapp, pump_events, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        # PushToTalk._run() looks up stt.listen_once dynamically at call
        # time (unlike a Qt signal connection, which snapshots a bound
        # method at .connect() time), so patching the shared stt instance
        # here -- after build_app() already connected the button's signal
        # to push_to_talk.trigger -- still lets us observe the real chain:
        # button click -> trigger() -> _run() -> stt.listen_once().
        stt = components["stt"]
        stt.available = True
        listen_calls = []

        def fake_listen_once(timeout=None, phrase_time_limit=None):
            listen_calls.append(True)
            return None

        stt.listen_once = fake_listen_once

        components["window"].push_to_talk_pressed.emit()

        assert pump_events(lambda: listen_calls == [True], timeout=3)
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_wires_speaker_test_button_to_speech_queue(qapp, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())
    spoken: list[tuple[str, str | None]] = []

    def record_request_speak(self, text, lang=None):
        spoken.append((text, lang))

    monkeypatch.setattr(gui_app.SpeechService, "request_speak", record_request_speak)

    app, components = gui_app.build_app(dry_run=True)
    try:
        components["window"].speaker_test_requested.emit()

        assert (gui_app.SPEAKER_TEST, "en") in spoken
        assert "voice test" in components["window"]._voice_transcript_label.text()
        assert "Testing voice" in components["window"]._setup_rows["tts"][2].text()
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_wires_voice_doctor_button_to_diagnostics(qapp, monkeypatch):
    from jarvis.models import CommandResult

    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())
    monkeypatch.setattr(
        gui_app,
        "build_voice_diagnostics",
        lambda settings: CommandResult(True, "Voice Doctor\n- Output: system default"),
    )

    app, components = gui_app.build_app(dry_run=True)
    try:
        components["window"].voice_diagnostics_requested.emit()

        assert "Voice Doctor" in components["window"]._voice_transcript_label.toolTip()
        assert "system default" in components["window"]._feedback_text
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_wires_voice_conversation_button_to_conversation_worker(qapp, monkeypatch):
    from jarvis.gui.voice_worker import VoiceConversation

    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())
    triggered = []
    monkeypatch.setattr(VoiceConversation, "trigger", lambda self: triggered.append(True))

    app, components = gui_app.build_app(dry_run=True)
    try:
        components["window"].voice_conversation_requested.emit()

        assert triggered == [True]
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_stops_realtime_before_starting_voice_conversation(qapp, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        realtime_worker = components["realtime_worker"]
        with realtime_worker._lock:
            realtime_worker._running = True
        stopped: list[bool] = []

        def fake_stop():
            stopped.append(True)
            with realtime_worker._lock:
                realtime_worker._running = False

        realtime_worker.stop = fake_stop

        components["window"].voice_conversation_requested.emit()

        assert stopped == [True]
        assert "Stopping realtime voice" in components["window"]._feedback_text
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_does_not_quit_when_the_window_closes(qapp, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        assert app.quitOnLastWindowClosed() is False
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_does_not_create_removed_panels_or_start_hidden_listener(qapp, pump_events, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())
    started = []
    monkeypatch.setattr(gui_app.VoiceWorker, "start", lambda self: started.append(True))

    app, components = gui_app.build_app(dry_run=True)
    try:
        assert not {"memory_panel", "tasks_panel", "developer_panel"} & components.keys()
        assert started == []
        assert components["window"]._privacy_label.text() == "MIC OFF"
        assert not components["realtime_worker"].running
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_routes_live_mute_audio_and_cancel_to_core_controls(qapp, pump_events, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        window = components["window"]
        worker = components["realtime_worker"]
        worker.state_changed.emit("listening")
        window._mute_button.click()
        assert worker._session._input_muted
        assert window._input_muted
        worker.audio_level_changed.emit(.75)
        assert window._core._target_level == .75
        components["executor"].task_state_changed.emit(True, "Reading shop")
        assert window._cancel_task_button.isEnabled()
        window._cancel_task_button.click()
        assert "Stop requested" in window._feedback_text
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_wires_settings_hotkey_checkbox_to_the_shared_hotkey_manager(qapp, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        # SettingsPage was constructed with this exact HotkeyManager instance
        # -- not a second, separate one -- so toggling the checkbox controls
        # the same object build_app() itself registered/wired above.
        assert components["settings_page"]._hotkey_manager is components["hotkey_manager"]
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_settings_hotkey_toggle_off_removes_the_native_event_filter(qapp, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        # Offscreen never really registers, so simulate "was on" directly on
        # the shared manager, then exercise the real toggle-off path through
        # SettingsPage exactly as a user click would.
        hotkey_manager = components["hotkey_manager"]
        hotkey_manager._registered = True
        settings_page = components["settings_page"]
        settings_page._hotkey_checkbox.blockSignals(True)
        settings_page._hotkey_checkbox.setChecked(True)
        settings_page._hotkey_checkbox.blockSignals(False)

        settings_page._hotkey_checkbox.setChecked(False)

        assert hotkey_manager.registered is False
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_skips_real_hotkey_registration_under_offscreen_tests(qapp, monkeypatch):
    # QT_QPA_PLATFORM=offscreen is set globally for the test session (see
    # conftest.py) -- build_app() must not leave a real system-wide Ctrl+
    # Space registration dangling across test runs.
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        assert components["hotkey_manager"].registered is False
        assert components["overlay"].isVisible() is False
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_session_poll_timer_updates_session_label(qapp, pump_events, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        components["assistant"].handle_utterance("jarvis отвори facebook")
        assert pump_events(lambda: components["window"]._session_active, timeout=3)
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_wires_stop_session_button_to_assistant_end_session(qapp, monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())

    app, components = gui_app.build_app(dry_run=True)
    try:
        components["assistant"].handle_utterance("jarvis отвори facebook")
        assert components["assistant"].session_active() is True

        components["window"].stop_session_requested.emit()

        assert components["assistant"].session_active() is False
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_build_app_wires_hotkey_press_to_overlay_toggle_and_push_to_talk(qapp, monkeypatch):
    from jarvis.gui.voice_worker import PushToTalk

    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())
    # Patched at the class level, before build_app() constructs PushToTalk
    # and connects hotkey_pressed to its bound .trigger -- connecting
    # captures a bound method at connect-time, so patching the instance
    # attribute afterwards would not affect the already-made connection.
    triggered = []
    monkeypatch.setattr(PushToTalk, "trigger", lambda self: triggered.append(True))

    app, components = gui_app.build_app(dry_run=True)
    try:
        # hotkey_pressed is connected to overlay.toggle/push_to_talk.trigger
        # unconditionally inside build_app() -- even offscreen, where only
        # the real RegisterHotKey call itself is skipped -- so no manual
        # reconnection is needed to exercise this wiring.
        components["stt"].available = True
        components["hotkey_manager"].hotkey_pressed.emit()

        assert components["overlay"].isVisible() is True
        assert triggered == [True]
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_alt_space_opens_text_overlay_without_starting_voice(qapp, monkeypatch):
    from jarvis.gui.voice_worker import PushToTalk

    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())
    triggered = []
    monkeypatch.setattr(PushToTalk, "trigger", lambda self: triggered.append(True))
    app, components = gui_app.build_app(dry_run=True)
    try:
        components["stt"].available = True
        components["overlay_hotkey_manager"].hotkey_pressed.emit()
        assert components["overlay"].isVisible()
        assert not triggered
        assert not components["realtime_worker"].running
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()


def test_monitor_alerts_do_not_speak_an_unsolicited_system_report(qapp, monkeypatch):
    monkeypatch.setattr("jarvis.gui.app.TextToSpeech", lambda *a, **k: _FakeTts())
    app, components = gui_app.build_app(dry_run=False)
    spoken = []
    monkeypatch.setattr(components["speech"], "request_speak", lambda text, *args: spoken.append(text))
    monkeypatch.setattr(components["tray"], "notify", lambda *args, **kwargs: None)
    try:
        components["bridge"].alert_received.emit("Disk space is low")
        assert not spoken
    finally:
        components["monitor"].stop()
        components["executor"].stop()
        components["speech"].stop()
