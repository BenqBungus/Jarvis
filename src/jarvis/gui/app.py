from __future__ import annotations

import os
import sys
import threading
from dataclasses import replace

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QCheckBox, QPushButton, QStyle

try:
    # comtypes (pycaw's volume control, pyttsx3's SAPI5 driver) disk-caches
    # generated wrapper modules on first use. Inside a PyInstaller --onedir
    # bundle that cache directory is not reliably writable, so force
    # in-memory generation instead. Must run before anything constructs a
    # TextToSpeech/WindowsActions instance that might touch comtypes; module
    # import time, ahead of build_app()'s object graph, is early enough.
    # try/except ImportError, not a hard import, since comtypes is only
    # needed when TTS/volume features are actually used.
    import comtypes.client

    comtypes.client.gen_dir = None
except ImportError:
    pass

from ..ai_client import JarvisAI
from ..audio.diagnostics import build_voice_diagnostics
from ..audio.speech_to_text import SpeechToText
from ..audio.text_to_speech import TextToSpeech
from ..audio.language import STARTUP_GREETING, SPEAKER_TEST, greeting_for, speaker_test_for, resolved_spoken_language, display_name_for
from ..audit import AuditLogger
from ..gmail import gmail_spoken_result
from ..config import ensure_openai_api_key_visible
from ..monitoring.loop import BackgroundMonitor
from ..realtime import RealtimeVoiceConfig, RealtimeVoiceSession, realtime_tool_schemas
from ..router import CommandRouter
from ..user_settings import JarvisSettings
from ..voice_assistant import VoiceAssistant
from ..windows_actions import WindowsActions
from .command_executor import CommandExecutor
from .activity_center import ActivityCenter
from .dashboard_model import DashboardModel
from .first_run_wizard import FirstRunWizard, needs_first_run_wizard
from .gui_safety import GuiSafetyPolicy
from .hotkey import HotkeyManager, MOD_ALT, MOD_CONTROL
from .main_window import MainWindow
from .monitor_bridge import MonitorBridge
from .notifications import classify_alert
from .overlay import OverlayWidget
from .profile_wiring import wire_profiles
from .realtime_worker import RealtimeVoiceWorker
from .settings_page import SettingsPage
from .speech_service import SpeechService
from .splash import StartupSplash
from .tray import TrayIcon
from .voice_worker import PushToTalk, VoiceConversation, VoiceWorker
from .panel_voice import PanelVoiceController, natural_config, NATURAL_DELIVERY

# Overrides VoiceAssistant's default "check the terminal" wording -- a --gui
# process may have no terminal at all, and the real confirmation now shows
# as an on-screen dialog (see GuiSafetyPolicy).
_GUI_CONFIRM_PROMPTS = {
    "bg": "Това изисква потвърждение. Виж екрана.",
    "en": "This needs confirmation. Please confirm on screen.",
}


def _is_offscreen(app: QApplication) -> bool:
    """True under headless test runs (QT_QPA_PLATFORM=offscreen) -- gates
    real microphone access and real global hotkey registration, neither of
    which make sense (and the latter would leave a real system-wide
    Ctrl+Space registration dangling across test runs) outside a real
    desktop session."""
    return os.getenv("QT_QPA_PLATFORM") == "offscreen" or app.platformName().lower() == "offscreen"


def _announce_startup_greeting(window: MainWindow, speech: SpeechService, language: str = "en"):
    text = greeting_for(language)
    window.set_assistant_message(text)
    return speech.request_speak(text, resolved_spoken_language(language))


def _run_speaker_test(window: MainWindow, speech: SpeechService, language: str = "en") -> None:
    text = speaker_test_for(language)
    window.set_assistant_message(text)
    window.set_setup_check("tts", False, "Testing voice...")
    speech.request_speak(text, resolved_spoken_language(language))


def _run_voice_doctor(window: MainWindow, settings: JarvisSettings) -> None:
    result = build_voice_diagnostics(settings)
    window.set_realtime_detail(result.message)
    window.append_history("diagnostic", "voice doctor", result.message, result.ok)


def _tray_state_for_realtime(state: str) -> str:
    if state == "idle":
        return "idle"
    if state == "listening":
        return "listening"
    if state in {"interrupted", "error"}:
        return "unclear"
    return "processing"


def _realtime_dependency_check(status: dict) -> tuple[bool, str]:
    problems = []
    if not status.get("websocket_available"):
        problems.append("websockets unavailable")
    if not status.get("audio_stream_available"):
        # This flag includes device discovery, not just package availability.
        problems.append("audio library or microphone/speaker unavailable")
    if problems:
        return False, "; ".join(problems) + ". Run Voice Doctor."
    return True, "websockets available; audio devices detected"


class _UnavailableSpeechToText:
    available = False

    def calibrate(self, duration: float = 0.5) -> None:
        return None

    def listen_once(self, **kwargs):
        return None


class _VoiceFeedback(QObject):
    state_changed = Signal(str)


def _format_reading(kind: str, reading: object) -> str:
    """One-line human-readable summary of a monitoring reading, for the
    dashboard panel. Falls back to str(reading) for a kind added later that
    this function doesn't know about yet, rather than raising."""
    if kind == "battery":
        if not getattr(reading, "available", False):
            return "not detected"
        state = "charging" if reading.charging else "on battery"
        return f"{reading.percent}% ({state})"
    if kind == "internet":
        return "connected" if reading.connected else "disconnected"
    if kind == "nvidia_driver":
        if not getattr(reading, "available", False):
            return "not detected"
        return f"{reading.name} {reading.driver_version}"
    if kind == "windows_update":
        if not getattr(reading, "available", False):
            return "unknown"
        return "up to date" if reading.pending_count == 0 else f"{reading.pending_count} pending"
    if kind == "cpu":
        if not getattr(reading, "available", False):
            return "unavailable"
        return f"{reading.percent:.0f}%"
    if kind == "cpu_temperature":
        if not getattr(reading, "available", False):
            return "sensor unavailable"
        return f"{reading.temperature_c:.0f}C"
    if kind == "memory":
        if not getattr(reading, "available", False):
            return "unavailable"
        return f"{reading.percent_used:.0f}% ({reading.used_gb:.1f}/{reading.total_gb:.1f} GB)"
    if kind == "gpu":
        if not getattr(reading, "available", False):
            return "not detected"
        usage = f"{reading.utilization_percent:.0f}%" if reading.utilization_percent is not None else "N/A"
        temperature = f"{reading.temperature_c:.0f}C" if reading.temperature_c is not None else "N/A"
        return f"{usage} ({temperature})"
    if kind == "disk":
        if not getattr(reading, "available", False):
            return "unavailable"
        return f"{reading.percent_free:.0f}% free ({reading.free_gb:.0f}/{reading.total_gb:.0f} GB)"
    return str(reading)


def build_app(dry_run: bool = False) -> tuple[QApplication, dict]:
    """Constructs the full GUI application graph and returns (app,
    components). Nothing here is a hidden module-level global -- tests and
    cli.py's --gui branch both get the constructed pieces back directly.
    """
    app = QApplication.instance() or QApplication(sys.argv)
    ensure_openai_api_key_visible()
    app.setQuitOnLastWindowClosed(False)  # tray app: closing the window must not quit
    # Dark native title bars and controls on every window, even when Windows
    # itself is in light mode (docs/claude/INTEGRATION_REQUESTS.md #5).
    app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
    offscreen = _is_offscreen(app)
    closing = threading.Event()
    panel_voice = None

    def panel_voice_active():
        return panel_voice is not None and panel_voice.active
    splash = StartupSplash()
    if offscreen:
        splash.set_progress(100, "READY")
    else:
        splash.run_startup_animation()

    settings = JarvisSettings.load()

    actions = WindowsActions(dry_run=dry_run)
    ai = JarvisAI(dry_run=dry_run, settings=settings)
    safety = GuiSafetyPolicy(settings)
    router = CommandRouter(actions=actions, safety=safety, ai=ai, settings=settings)
    audit = AuditLogger()
    executor = CommandExecutor(router=router, audit=audit, dry_run=dry_run)
    executor.cancellation_requested.connect(safety.cancel_pending)

    mic_lock = threading.Lock()
    tts = TextToSpeech()
    from ..audio.text_to_speech import DEFAULT_OPENAI_TTS_INSTRUCTIONS
    if getattr(tts, "openai_instructions", DEFAULT_OPENAI_TTS_INSTRUCTIONS) == DEFAULT_OPENAI_TTS_INSTRUCTIONS:
        tts.openai_instructions = NATURAL_DELIVERY
    speech = SpeechService(tts, mic_lock=mic_lock)
    startup_greeting_job = None
    live_has_spoken = False

    # energy_threshold/pause_threshold_ms come from the Settings page's noise
    # threshold controls; 0/absent means "let SpeechToText/SpeechRecognition
    # use their own defaults" (None), not literally 0.
    energy_threshold = settings.openai.get("energy_threshold") or None
    pause_threshold_ms = settings.openai.get("pause_threshold_ms") or None
    pause_threshold = (pause_threshold_ms / 1000) if pause_threshold_ms else None

    if offscreen:
        stt = _UnavailableSpeechToText()
    else:
        stt = SpeechToText(energy_threshold=energy_threshold, pause_threshold=pause_threshold,
                          conversation_language=settings.conversation_language)

    # Constructed here (not near the registration block below, where it used
    # to live) so the same instance can be handed to SettingsPage, which
    # calls register()/unregister() on it directly when its "Enable global
    # Ctrl+Space hotkey" checkbox is toggled -- a second, separate
    # HotkeyManager() would mean the checkbox silently controls a manager
    # that isn't the one actually intercepting Ctrl+Space. Actual
    # registration and hotkey_pressed wiring still happen further down, once
    # overlay/push_to_talk exist.
    hotkey_manager = HotkeyManager()
    overlay_hotkey_manager = HotkeyManager(modifiers=MOD_ALT, hotkey_id=2, label="Alt+Space")
    game_hotkey_manager = HotkeyManager(modifiers=MOD_ALT | MOD_CONTROL, hotkey_id=3, label="Ctrl+Alt+Space")

    window = MainWindow()
    from .screen_sharing import ScreenSharingIndicator
    sharing_indicator = ScreenSharingIndicator(router.screen_sharing)
    from .screen_chat import ScreenChatDialog
    screen_chat = ScreenChatDialog(window, dry_run=dry_run, settings=settings)
    window.screen_chat_requested.connect(screen_chat.open_chat)
    screen_chat.command_submitted.connect(executor.submit)
    screen_chat.command_cancel_requested.connect(executor.cancel_pending)
    screen_chat.sharing_started.connect(sharing_indicator.stop)
    from .game_chat import GameChatDialog
    game_chat = GameChatDialog(ai)

    def toggle_screen_sharing():
        if router.screen_sharing.state()["sharing"]:
            sharing_indicator.stop()
        else:
            executor.submit("start screen sharing", "gui")

    window.screen_sharing_requested.connect(toggle_screen_sharing)
    # The HUD share button mirrors the real sharing state (INTEGRATION_REQUESTS #3).
    share_state_timer = QTimer(window)
    share_state_timer.setInterval(500)
    share_state_timer.timeout.connect(
        lambda: window.set_screen_sharing_active(bool(router.screen_sharing.state().get("sharing"))))
    share_state_timer.start()
    safety.set_window(window)
    realtime_config = natural_config(RealtimeVoiceConfig.from_settings(settings))
    realtime_config = replace(realtime_config, tools=realtime_tool_schemas(router.tools))
    realtime_status = RealtimeVoiceSession(realtime_config).readiness()
    dependency_check = _realtime_dependency_check(realtime_status)
    window.set_voice_mode_profile(
        voice=realtime_status["voice"],
        model=realtime_status["model"],
        intelligence="Instant",
        language=display_name_for(settings.conversation_language),
    )
    if realtime_status["ready"]:
        window.set_realtime_status(
            True,
            f"{realtime_status['model']} | voice {realtime_status['voice']} | "
            f"{realtime_status['sample_rate']} Hz | {len(realtime_config.tools)} tools",
        )
    else:
        readiness_problems = []
        if not realtime_status["api_key_present"]:
            readiness_problems.append("OPENAI_API_KEY missing")
        if not dependency_check[0]:
            readiness_problems.append(dependency_check[1])
        window.set_realtime_status(
            False,
            "; ".join(readiness_problems)
            + f" | {realtime_status['model']} | voice {realtime_status['voice']}",
        )
    tts_status = tts.status_summary() if hasattr(tts, "status_summary") else {}
    window.set_setup_checks(
        {
            "openai_key": (
                bool(realtime_status["api_key_present"]),
                "visible to this process" if realtime_status["api_key_present"] else "missing environment variable",
            ),
            "realtime_deps": dependency_check,
            "classic_mic": (
                bool(stt.available),
                "microphone available" if stt.available else "classic voice unavailable",
            ),
            "tts": (
                bool(tts_status.get("enabled", False)),
                f"{tts_status.get('provider', 'voice')} voice ready"
                if tts_status.get("enabled", False)
                else "speaker voice unavailable",
            ),
        }
    )
    settings_page = SettingsPage(settings, ai=ai, hotkey_manager=hotkey_manager)
    from .gmail_settings import GmailSettingsDialog
    gmail_settings = GmailSettingsDialog(router.gmail, window)
    gmail_button = QPushButton("Gmail", settings_page)
    gmail_button.setIcon(settings_page.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView))
    gmail_button.setToolTip("Gmail account connection")
    gmail_button.clicked.connect(gmail_settings.open_settings)
    settings_page.layout().insertWidget(0, gmail_button)
    game_button = QPushButton("Game Chat", settings_page)
    game_button.setIcon(settings_page.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxQuestion))
    game_button.setToolTip("Gaming advice | Ctrl+Alt+Space")
    game_button.clicked.connect(game_chat.open_chat)
    settings_page.layout().insertWidget(0, game_button)
    game_hotkey_toggle = QCheckBox("Ctrl+Alt+Space | Game Chat", settings_page)
    game_hotkey_toggle.setChecked(bool(settings.mode_preferences.get("game_chat_hotkey_enabled", True)))
    settings_page.layout().insertWidget(1, game_hotkey_toggle)
    executor.task_state_changed.connect(window.set_task_state)
    executor.task_progress.connect(window.show_feedback)
    window.cancel_task_requested.connect(lambda: executor.submit("cancel task", "button"))
    window.set_settings_widget(settings_page)
    tray = TrayIcon(window)
    overlay = OverlayWidget()
    activity_center = ActivityCenter(audit, parent=window)
    window.overlay_requested.connect(overlay.toggle)
    window.activity_requested.connect(lambda: activity_center.open_page())
    window.undo_center_requested.connect(lambda: activity_center.open_page(undo=True))
    overlay.activity_requested.connect(lambda: activity_center.open_page())
    overlay.undo_requested.connect(lambda: activity_center.open_page(undo=True))
    overlay.command_submitted.connect(executor.submit)
    overlay.cancel_requested.connect(lambda: executor.submit("cancel task", "overlay"))
    activity_center.undo_requested.connect(lambda stamp: executor.submit_tool(
        "undo_last_action", {"expected_timestamp": stamp}, source="undo_center"))
    executor.task_state_changed.connect(lambda busy, _detail: activity_center.set_busy(busy))

    # Defined before VoiceAssistant so on_unclear can be wired straight into
    # its constructor rather than connected after the fact.
    def on_mic_state_changed(state: str) -> None:
        if closing.is_set():
            return
        tray.set_voice_state(state)
        window.set_mic_status(state)
        overlay.set_state(state)

    def locked_listen_once(*args, **kwargs):
        with mic_lock:
            return stt.listen_once(*args, **kwargs)

    voice_feedback = _VoiceFeedback(window)
    voice_feedback.state_changed.connect(on_mic_state_changed)

    def dispatch_classic_voice(text: str):
        return gmail_spoken_result(executor.submit_blocking(text))

    assistant = VoiceAssistant(
        router=router,
        stt=stt,
        tts=speech.as_tts(),  # routes voice prompts through SpeechService's queue, not the raw engine
        dispatch=dispatch_classic_voice,  # preserves serialization/audit before TTS presentation
        confirm_prompts=_GUI_CONFIRM_PROMPTS,
        on_unclear=lambda: voice_feedback.state_changed.emit("unclear"),
        listen_once=locked_listen_once,
        spoken_language=settings.conversation_language,
    )
    voice_worker = VoiceWorker(stt, assistant, mic_lock)
    push_to_talk = PushToTalk(stt, assistant, mic_lock)

    def resume_wake_word_if_no_realtime() -> None:
        if not closing.is_set() and not panel_voice_active() and not realtime_worker.running and not voice_conversation.running and not push_to_talk.running:
            voice_worker.resume()

    def resume_after_realtime() -> None:
        if not closing.is_set() and not panel_voice_active():
            speech.resume()
            resume_wake_word_if_no_realtime()

    voice_conversation = VoiceConversation(
        stt,
        assistant,
        mic_lock,
        on_started=voice_worker.pause,
        on_stopped=resume_wake_word_if_no_realtime,
    )
    realtime_worker = RealtimeVoiceWorker(
        RealtimeVoiceSession(realtime_config, memory=router.conversation_memory,
                             screen_sharing=router.screen_sharing,
                             memory_enabled=lambda: bool(settings.openai.get("use_memory_context", True))),
        executor.submit_tool_blocking,
        on_started=lambda: (speech.suspend(), voice_conversation.stop(), voice_worker.pause()),
        on_stopped=resume_after_realtime,
        mic_lock=mic_lock,
    )

    def pause_for_panel():
        nonlocal pending_conversation
        pending_conversation = False
        voice_worker.pause()
        voice_conversation.stop()
        realtime_worker.stop()

    panel_voice = PanelVoiceController(settings, router, executor, speech, mic_lock, sharing_indicator,
        pause_for_panel, resume_wake_word_if_no_realtime, dry_run=dry_run)
    game_chat.voice_controller = panel_voice
    screen_chat.voice_controller = panel_voice

    bridge = MonitorBridge()
    dashboard_model = DashboardModel()
    bridge.reading_received.connect(dashboard_model.on_reading)
    monitor = BackgroundMonitor(notify=bridge.notify, on_reading=bridge.on_reading, settings=settings)

    # --- Wiring: GUI thread only, all cross-thread hops already handled by
    # the Signal-based components above (CommandExecutor, MonitorBridge). ---

    window.command_submitted.connect(lambda text, source: executor.submit(text, source))

    def on_result_ready(source: str, text: str, result) -> None:
        if source.startswith("screen_chat_command:"):
            screen_chat.on_command_result(source, text, result)
        if closing.is_set():
            return
        if result.ok and result.metadata.get("proposal_id") and "diff" in result.metadata:
            window.show_edit_preview(result.message)
        # The executor retains the audit trail; the voice surface shows only
        # transient feedback, never a parallel conversation panel.
        if source != "memory":
            window.append_history(source, text, result.message, result.ok)
            if source.startswith("overlay"):
                overlay.show_result(result.message, result.ok)
            if source == "undo_center":
                activity_center.show_undo_result(result.message)
            elif activity_center.isVisible():
                activity_center.refresh()
            if source not in {"voice", "realtime", "overlay_local", "overlay_teach"} and not source.startswith("screen_chat_command:") and not realtime_worker.running and not panel_voice_active() and not dry_run:
                speech.request_speak(gmail_spoken_result(result).message)

    executor.result_ready.connect(on_result_ready)

    def on_reading_updated(kind: str) -> None:
        if closing.is_set():
            return
        reading = dashboard_model.latest(kind)
        window.update_dashboard(kind, _format_reading(kind, reading))

    dashboard_model.updated.connect(on_reading_updated)

    def on_alert(message: str) -> None:
        if closing.is_set():
            return
        info = classify_alert(message)
        tray.notify(info.title, message, category=info.category)
        if info.category == "warning":
            tray.raise_warning()
        if settings.mode_preferences.get("spoken_monitor_alerts", False) and not realtime_worker.running and not panel_voice_active() and not dry_run:
            speech.request_speak(message)

    bridge.alert_received.connect(on_alert)

    # Driver installs finish on their own thread (driver_updates.py, Claude);
    # a MonitorBridge hops the result onto the GUI thread.
    driver_events = MonitorBridge()
    router.driver_updates.on_finished = lambda result: driver_events.on_reading(
        "ok" if result.ok else "failed", result.message)

    def on_driver_update_finished(outcome: str, message: object) -> None:
        if closing.is_set():
            return
        tray.notify("Driver update", str(message)[:300], category="info" if outcome == "ok" else "warning")
        window.show_feedback(str(message), error=outcome != "ok")

    driver_events.reading_received.connect(on_driver_update_finished)

    voice_worker.state_changed.connect(on_mic_state_changed)
    push_to_talk.state_changed.connect(on_mic_state_changed)
    voice_conversation.state_changed.connect(on_mic_state_changed)
    voice_worker.transcript_heard.connect(lambda text: window.set_voice_transcript(text, "Heard"))
    push_to_talk.transcript_heard.connect(lambda text: window.set_voice_transcript(text, "Heard"))
    voice_conversation.transcript_heard.connect(lambda text: window.set_voice_transcript(text, "Heard"))
    def on_realtime_state_changed(state: str) -> None:
        if closing.is_set():
            return
        on_mic_state_changed(_tray_state_for_realtime(state))
        window.set_realtime_active(state != "idle" and state != "error", state)

    realtime_worker.state_changed.connect(lambda state: on_realtime_state_changed(state) if not panel_voice_active() else None)
    panel_voice.state_changed.connect(on_realtime_state_changed)
    realtime_worker.detail_changed.connect(window.set_realtime_detail)
    realtime_worker.tool_error_occurred.connect(window.show_tool_error)
    realtime_worker.user_transcript_received.connect(lambda text: window.set_voice_transcript(text, "You"))
    realtime_worker.assistant_transcript_received.connect(lambda text: window.set_voice_transcript(text, "Jarvis"))
    def remember_live_reply(text: str) -> None:
        nonlocal live_has_spoken
        live_has_spoken = live_has_spoken or bool(text.strip())

    realtime_worker.assistant_transcript_received.connect(remember_live_reply)
    realtime_worker.audio_level_changed.connect(window.set_audio_level)
    realtime_worker.input_muted_changed.connect(window.set_input_muted)
    realtime_worker.keyword_interrupt_changed.connect(window.set_keyword_interrupt_status)
    window.input_mute_requested.connect(realtime_worker.set_input_muted)
    window.interrupt_speech_requested.connect(realtime_worker.interrupt_speech)

    def trigger_push_to_talk() -> None:
        if closing.is_set() or panel_voice_active() or realtime_worker.running or voice_conversation.running or not push_to_talk.available:
            return
        voice_worker.pause()
        push_to_talk.trigger()

    push_to_talk.state_changed.connect(lambda state: resume_wake_word_if_no_realtime() if state == "idle" else None)
    window.push_to_talk_pressed.connect(trigger_push_to_talk)
    window.speaker_test_requested.connect(lambda: _run_speaker_test(window, speech, settings.conversation_language))
    window.speaker_tone_requested.connect(speech.request_tone)
    window.voice_diagnostics_requested.connect(lambda: _run_voice_doctor(window, settings))

    def on_playback_started(text: str) -> None:
        if closing.is_set():
            return
        if not realtime_worker.running:
            voice_worker.pause()
            window.set_assistant_message(text)
            window.set_mic_status("speaking")

    def on_playback_finished(ok: bool, detail: str) -> None:
        if closing.is_set():
            return
        window.set_setup_check("tts", ok, detail)
        if not ok:
            window.set_realtime_detail(detail)
            window.append_history("audio", "Voice playback", detail, False)
        if not panel_voice_active() and not realtime_worker.running and not voice_conversation.running and not push_to_talk.running:
            voice_worker.resume()
            on_mic_state_changed("idle" if ok else "unclear")

    speech.playback_started.connect(on_playback_started)
    speech.playback_finished.connect(on_playback_finished)

    pending_conversation = False

    def start_voice_conversation() -> None:
        nonlocal pending_conversation
        if closing.is_set():
            return
        if panel_voice_active():
            window.show_feedback("Stop the Screen/Game voice call first.", error=True)
            return
        if realtime_worker.running:
            pending_conversation = True
            realtime_worker.stop()
            window.set_realtime_detail("Stopping realtime voice before starting conversation mode...")
            return
        voice_conversation.trigger()

    def finish_voice_switch() -> None:
        nonlocal pending_conversation
        if pending_conversation and not closing.is_set() and not panel_voice_active():
            pending_conversation = False
            voice_conversation.trigger()

    realtime_worker.session_stopped.connect(finish_voice_switch)

    def start_realtime() -> None:
        if closing.is_set() or realtime_worker.running:
            return
        if panel_voice_active():
            window.show_feedback("Stop the Screen/Game voice call first.", error=True)
            return
        speech.suspend()
        config = replace(natural_config(RealtimeVoiceConfig.from_settings(settings)), tools=realtime_tool_schemas(router.tools))
        # An in-flight classic greeting owns mic_lock until playback ends.
        # It must not be followed immediately by a second live introduction.
        if live_has_spoken or (startup_greeting_job and startup_greeting_job.started and (
                not startup_greeting_job.done.is_set() or startup_greeting_job.spoken)):
            config = replace(config, greeting="")
        if realtime_worker.configure(config):
            window.set_voice_mode_profile(config.voice, config.model, language=display_name_for(settings.conversation_language))
            window.set_speaker_guard(config.speaker_guard)
            if not realtime_worker.start():
                speech.resume()
        else:
            speech.resume()

    def refresh_realtime_readiness() -> None:
        if closing.is_set():
            return
        classic_updated = True
        for component in (stt, assistant):
            setter = getattr(component, "set_conversation_language", None)
            if callable(setter):
                setter(settings.conversation_language)
            else:
                classic_updated = False
        # Applied at once everywhere: a running Live call switches through
        # session.update (RealtimeVoiceWorker.update_live_config, Claude).
        if settings.conversation_language == "bg":
            language_notice = "Езикът е приложен веднага."
            language_notice += "" if classic_updated else " За Classic рестартирай Jarvis."
        else:
            language_notice = "Language applied right away."
            language_notice += "" if classic_updated else " Restart Jarvis for Classic voice."
        if realtime_worker.running:
            live = replace(natural_config(RealtimeVoiceConfig.from_settings(settings)), tools=realtime_tool_schemas(router.tools))
            realtime_worker.update_live_config(live)
            window.set_voice_mode_profile(live.voice, live.model, language=display_name_for(settings.conversation_language))
            window.set_realtime_detail(language_notice)
            return
        config = RealtimeVoiceConfig.from_settings(settings)
        status = RealtimeVoiceSession(config).readiness()
        deps = _realtime_dependency_check(status)
        detail = deps[1] if not deps[0] else "Ready to connect"
        if not status["api_key_present"]:
            detail = "Missing OPENAI_API_KEY. " + detail
        window.set_realtime_status(status["ready"], detail)
        window.set_voice_mode_profile(config.voice, config.model, language=display_name_for(settings.conversation_language))
        window.set_setup_check("realtime_deps", *deps)
        window.set_setup_check("openai_key", status["api_key_present"],
                               "Key present; verified on connect" if status["api_key_present"] else "Missing OPENAI_API_KEY")
        if status["ready"]:
            window.set_realtime_detail(language_notice)
        else:
            window.show_feedback(detail + "\n" + language_notice, error=True)

    settings_page.saved.connect(refresh_realtime_readiness)
    from .settings_runtime import SettingsRuntime
    settings_runtime = SettingsRuntime(settings, stt, tts, assistant, mic_lock,
        lambda: closing.is_set() or panel_voice_active() or realtime_worker.running or voice_conversation.running or push_to_talk.running,
        screen_chat, settings_page)

    def stop_realtime() -> None:
        executor.submit("cancel task", "realtime")
        realtime_worker.stop()

    window.voice_conversation_requested.connect(start_voice_conversation)
    window.realtime_start_requested.connect(start_realtime)
    window.realtime_stop_requested.connect(stop_realtime)
    window.realtime_stop_requested.connect(panel_voice.stop)
    window.input_mute_requested.connect(lambda muted: panel_voice.mute(panel_voice.owner, muted))
    window.interrupt_speech_requested.connect(lambda: panel_voice.interrupt(panel_voice.owner))

    # No new cross-thread callback for the active-session indicator: polling
    # a plain bool via session_active() is safe (see its docstring) and
    # avoids replicating on_unclear's un-marshaled cross-thread widget
    # mutation. 1s is frequent enough for a status label, cheap even offscreen.
    session_poll_timer = QTimer()
    session_poll_timer.setInterval(1000)
    session_poll_timer.timeout.connect(lambda: window.set_session_active(assistant.session_active()))
    session_poll_timer.start()
    window.stop_session_requested.connect(assistant.end_session)
    window.stop_session_requested.connect(voice_conversation.stop)

    def run_wizard() -> None:
        # Reuses the live settings object (mutated in place, same as
        # SettingsPage), so a re-run from the tray menu takes effect
        # immediately without needing a restart.
        FirstRunWizard(settings, parent=window).exec()

    tray.run_wizard_requested.connect(run_wizard)

    # Ctrl+Space: toggles the overlay and triggers push-to-talk. Connected
    # once, unconditionally -- harmless while unregistered, since WM_HOTKEY
    # (and therefore this signal) simply never fires in that state. Doing it
    # this way (rather than inside the registration branch below) means
    # later re-registering after a live Settings toggle never risks a
    # duplicate connection, which would double-fire every press.
    hotkey_manager.hotkey_pressed.connect(overlay.toggle)
    hotkey_manager.hotkey_pressed.connect(trigger_push_to_talk)
    overlay_hotkey_manager.hotkey_pressed.connect(overlay.toggle)
    game_hotkey_manager.hotkey_pressed.connect(game_chat.toggle)
    def sync_game_hotkey(enabled: bool) -> None:
        if offscreen:
            return
        game_hotkey_manager.unregister()
        app.removeNativeEventFilter(game_hotkey_manager)
        if enabled and game_hotkey_manager.register():
            app.installNativeEventFilter(game_hotkey_manager)
            game_button.setToolTip("Gaming advice | Ctrl+Alt+Space")
        elif enabled:
            game_button.setToolTip("Ctrl+Alt+Space unavailable. Open Game Chat with this button.")
            tray.notify("Jarvis", "Ctrl+Alt+Space is unavailable. Use Settings > Game Chat.", category="info")
        else:
            game_button.setToolTip("Gaming advice | Global shortcut disabled")

    def save_game_hotkey(enabled: bool) -> None:
        settings.mode_preferences["game_chat_hotkey_enabled"] = enabled
        sync_game_hotkey(enabled)
        try:
            settings.save()
        except OSError:
            window.show_feedback("Game Chat shortcut changed for this session; settings could not be saved.", error=True)

    game_hotkey_toggle.toggled.connect(save_game_hotkey)
    sync_game_hotkey(game_hotkey_toggle.isChecked())

    def sync_overlay_hotkey(enabled: bool) -> None:
        if offscreen:
            return
        if enabled and overlay_hotkey_manager.register():
            app.removeNativeEventFilter(overlay_hotkey_manager)
            app.installNativeEventFilter(overlay_hotkey_manager)
            settings_page._overlay_hotkey_status.setText("")
        elif enabled:
            settings_page._overlay_hotkey_status.setText("Alt+Space is unavailable. Use the command-overlay button.")
            window.show_feedback("Alt+Space is unavailable. The command-overlay button still works.", error=True)
        else:
            overlay_hotkey_manager.unregister()
            app.removeNativeEventFilter(overlay_hotkey_manager)
            settings_page._overlay_hotkey_status.setText("")

    settings_page.overlay_hotkey_toggled.connect(sync_overlay_hotkey)
    sync_overlay_hotkey(bool(settings.mode_preferences.get("overlay_hotkey_enabled", True)))

    _native_filter_installed = False

    def _sync_hotkey_native_filter() -> None:
        # Keeps installNativeEventFilter in lockstep with
        # hotkey_manager.registered. Explicit state tracking (not just
        # "install whenever registered"), since installing the same filter
        # object twice makes Qt call it twice per message -- SettingsPage's
        # toggle handler already updated .registered by the time this runs
        # (Qt direct-connection Signals are synchronous on the GUI thread),
        # so this only ever needs to react to real state, never guess at it.
        nonlocal _native_filter_installed
        should_be_installed = hotkey_manager.registered
        if should_be_installed and not _native_filter_installed:
            app.installNativeEventFilter(hotkey_manager)
            _native_filter_installed = True
        elif not should_be_installed and _native_filter_installed:
            app.removeNativeEventFilter(hotkey_manager)
            _native_filter_installed = False

    # Skipped entirely under offscreen test runs -- see _is_offscreen()'s
    # docstring; a real RegisterHotKey call would leave a real system-wide
    # Ctrl+Space registration dangling across test runs regardless of Qt's
    # platform plugin. A failed registration (e.g. already bound by another
    # application) is non-fatal: notify once, never block startup on it.
    if not offscreen and settings.mode_preferences.get("hotkey_enabled", True):
        if not hotkey_manager.register():
            tray.notify(
                "Jarvis",
                "Global hotkey Ctrl+Space is unavailable (already in use by another application).",
                category="info",
            )
    _sync_hotkey_native_filter()

    # SettingsPage's toggle handler already called register()/unregister()
    # itself (see its docstring) -- this only needs to keep the native event
    # filter in sync with whatever that left hotkey_manager.registered as.
    settings_page.hotkey_toggled.connect(lambda _enabled: _sync_hotkey_native_filter())

    def shutdown() -> None:
        nonlocal pending_conversation
        if closing.is_set():
            return
        closing.set()
        settings_runtime.stop()
        panel_voice.shutdown()
        pending_conversation = False
        monitor.stop()
        gmail_settings.shutdown()
        screen_chat.shutdown()
        game_chat.shutdown()
        game_hotkey_manager.unregister()
        app.removeNativeEventFilter(game_hotkey_manager)
        sharing_indicator.shutdown()
        safety.shutdown()
        hotkey_manager.unregister()
        overlay_hotkey_manager.unregister()
        app.removeNativeEventFilter(overlay_hotkey_manager)
        overlay.hide()
        activity_center.hide()
        app.removeNativeEventFilter(hotkey_manager)
        session_poll_timer.stop()
        voice_worker.stop()
        voice_conversation.stop()
        realtime_worker.stop()
        executor.stop()
        speech.stop()

    app.aboutToQuit.connect(shutdown)

    # Profiles, Kid/Guest levels and habits (gui/profile_wiring.py, Claude).
    profiles = wire_profiles(window=window, settings_page=settings_page, router=router, executor=executor,
                             audit=audit, settings=settings, stt=stt, assistant=assistant,
                             live_call_active=lambda: realtime_worker.running, pause_listening=voice_worker.pause,
                             resume_listening=resume_wake_word_if_no_realtime, live_audio=realtime_worker)
    profiles.language_changed.connect(lambda _code: refresh_realtime_readiness())

    executor.start()
    speech.start()
    monitor.start()
    # Microphone capture is opt-in. The primary call uses Realtime; classic
    # voice is available explicitly from Settings, never a hidden listener.
    tray.show()
    if tts_status.get("provider") == "openai" and not tts_status.get("openai_key_present"):
        tray.notify(
            "Jarvis voice",
            "OpenAI voice is selected, but OPENAI_API_KEY is not visible to this process. "
            "Jarvis will use Windows fallback voice if available.",
            category="info",
        )
    # Show the main window on launch. The app still behaves as a tray app
    # after that: closing the window hides it, and the tray menu can show it
    # again. Without this, launching --gui appears to do nothing unless the
    # user notices the tray icon.
    window.show()
    window.raise_()
    window.activateWindow()
    def startup_greeting() -> None:
        nonlocal startup_greeting_job
        if not closing.is_set() and not panel_voice_active() and not realtime_worker.running and not live_has_spoken:
            startup_greeting_job = _announce_startup_greeting(window, speech, settings.conversation_language)

    if not dry_run:
        QTimer.singleShot(1200, startup_greeting)

    return app, {
        "shutdown": shutdown,
        "panel_voice": panel_voice,
        "settings_runtime": settings_runtime,
        "gmail_settings": gmail_settings,
        "gmail_button": gmail_button,
        "screen_chat": screen_chat,
        "game_chat": game_chat,
        "game_button": game_button,
        "game_hotkey_manager": game_hotkey_manager,
        "game_hotkey_toggle": game_hotkey_toggle,
        "sharing_indicator": sharing_indicator,
        "window": window,
        "tray": tray,
        "executor": executor,
        "speech": speech,
        "monitor": monitor,
        "router": router,
        "safety": safety,
        "settings": settings,
        "dashboard_model": dashboard_model,
        "bridge": bridge,
        "stt": stt,
        "assistant": assistant,
        "voice_worker": voice_worker,
        "push_to_talk": push_to_talk,
        "voice_conversation": voice_conversation,
        "realtime_worker": realtime_worker,
        "audit": audit,
        "overlay": overlay,
        "activity_center": activity_center,
        "overlay_hotkey_manager": overlay_hotkey_manager,
        "hotkey_manager": hotkey_manager,
        "session_poll_timer": session_poll_timer,
        "settings_page": settings_page,
        "profiles": profiles,
        "splash": splash,
    }


def main(dry_run: bool = False) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    if not _is_offscreen(app) and needs_first_run_wizard():
        # Runs before build_app() constructs its own settings object;
        # build_app()'s own JarvisSettings.load() picks up whatever this
        # saves. Cancelling (not Finish) leaves data/settings.json absent,
        # so the wizard is offered again on the next launch rather than
        # being silently skipped forever.
        FirstRunWizard(JarvisSettings.load()).exec()

    app, _components = build_app(dry_run=dry_run)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
