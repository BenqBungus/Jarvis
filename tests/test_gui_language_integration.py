import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from jarvis.gui import app as gui_app
from jarvis.user_settings import JarvisSettings
from jarvis.models import CommandResult


@pytest.fixture
def language_app(qapp, monkeypatch, request):
    if os.getenv('JARVIS_LANGUAGE_UI_SNAPSHOT'):
        from PySide6.QtGui import QFontDatabase, QFont
        for name in ('segoeui.ttf', 'segoeuib.ttf', 'arial.ttf'):
            QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts') / name))
        qapp.setFont(QFont('Segoe UI', 10))
    monkeypatch.setattr(gui_app.BackgroundMonitor, 'start', lambda self: None)
    # Exercise the real language setter without constructing microphone hardware.
    stt = gui_app.SpeechToText.__new__(gui_app.SpeechToText)
    stt.available = False
    stt.set_conversation_language('bg')
    monkeypatch.setattr(gui_app, '_UnavailableSpeechToText', lambda: stt)
    monkeypatch.setattr(gui_app, 'TextToSpeech', lambda: Mock(enabled=False, status_summary=lambda: {}))
    monkeypatch.setattr(gui_app.RealtimeVoiceSession, 'readiness', lambda self: {
        'ready': False, 'api_key_present': False, 'websocket_available': True, 'audio_stream_available': False,
        'missing': ['OPENAI_API_KEY', 'sounddevice'], 'voice': self.config.voice,
        'model': self.config.model, 'sample_rate': 24000,
    })
    settings = JarvisSettings(openai={'conversation_language': 'bg'})
    settings.save()
    _, components = gui_app.build_app(dry_run=getattr(request, 'param', True))
    yield components
    components['shutdown']()
    components['tray']._icon.hide()
    components['window'].hide()


def test_bulgarian_setting_reaches_both_ai_clients_and_voice_entry_points(language_app, monkeypatch):
    c = language_app
    assert c['settings'].conversation_language == 'bg'
    assert c['router'].ai.settings is c['settings']
    assert c['screen_chat'].sharing.ai.settings is c['settings']
    assert c['assistant']._spoken_language == 'bg'
    assert 'Bulgarian' in c['window']._profile_label.text()
    spoken = Mock()
    monkeypatch.setattr(c['speech'], 'request_speak', spoken)
    c['window'].speaker_test_requested.emit()
    assert spoken.call_args.args[1] == 'bg'
    assert 'Здравей' in spoken.call_args.args[0]
    gui_app._announce_startup_greeting(c['window'], c['speech'], c['settings'].conversation_language)
    assert spoken.call_args.args == ('Здравей, Берк. Как мога да помогна?', 'bg')


def test_real_settings_selector_saves_and_updates_next_live_session(language_app, monkeypatch, qapp):
    c = language_app
    page = c['settings_page']
    combo = page._language_combo
    assert {combo.itemData(i) for i in range(combo.count())} == {'en', 'bg', 'auto'}
    assert combo.currentData() == 'bg'
    combo.setCurrentIndex(combo.findData('auto'))
    page._on_save()
    assert JarvisSettings.load().conversation_language == 'auto'
    assert c['screen_chat'].sharing.ai.settings.conversation_language == 'auto'
    assert c['stt'].conversation_language == 'auto'
    assert c['assistant']._spoken_language is None
    assert 'Automatic' in c['window']._profile_label.text()
    monkeypatch.setattr(c['realtime_worker'], 'start', lambda: False)
    c['window'].realtime_start_requested.emit()
    assert c['realtime_worker']._session.config.conversation_language == 'auto'
    combo.setCurrentIndex(combo.findData('bg'))
    page._on_save()
    assert c['stt'].conversation_language == 'bg'
    assert c['stt'].languages == ('bg-BG',)
    assert c['assistant']._spoken_language == 'bg'
    assert 'рестартирай' not in c['window']._feedback_text
    target = os.getenv('JARVIS_LANGUAGE_UI_SNAPSHOT')
    if target:
        c['window']._settings_button.click()
        qapp.processEvents()
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        assert c['window']._settings_dialog.grab().save(target)


def test_language_save_switches_the_active_call_without_restarting_it(language_app):
    # User decision 2026-09-28: a language change applies at once, also to a
    # running Live call (session.update), without tearing the call down.
    c = language_app
    worker = c['realtime_worker']
    old_config = worker._session.config
    with worker._lock:
        worker._running = True
    try:
        combo = c['settings_page']._language_combo
        combo.setCurrentIndex(combo.findData('en'))
        c['settings_page']._on_save()
        assert worker._session.config is old_config  # the call keeps running
        assert worker.running
        assert worker._session._take_live_update().conversation_language == 'en'
        assert 'applied right away' in c['window']._feedback_text
    finally:
        with worker._lock:
            worker._running = False


def test_settings_save_keeps_missing_voice_requirements_visible(language_app):
    c = language_app
    c['settings_page']._on_save()
    assert not c['window']._realtime_ready
    assert 'OPENAI_API_KEY' in c['window']._feedback_text
    assert 'microphone/speaker unavailable' in c['window']._feedback_text
    assert 'Езикът е приложен веднага' in c['window']._feedback_text


def test_shutdown_does_not_start_pending_classic_switch_or_resume_audio(language_app, monkeypatch):
    c = language_app
    worker = c['realtime_worker']
    trigger = Mock()
    resume = Mock()
    monkeypatch.setattr(c['voice_conversation'], 'trigger', trigger)
    monkeypatch.setattr(c['speech'], 'resume', resume)
    with worker._lock:
        worker._running = True
    try:
        c['window'].voice_conversation_requested.emit()
        c['shutdown']()
        worker._on_stopped()
        worker.session_stopped.emit()
        c['window'].voice_conversation_requested.emit()
        c['window'].realtime_start_requested.emit()
        c['shutdown']()
        trigger.assert_not_called()
        resume.assert_not_called()
        assert not c['session_poll_timer'].isActive()
    finally:
        with worker._lock:
            worker._running = False


@pytest.mark.parametrize('language_app', [False], indirect=True)
def test_delayed_startup_greeting_is_cancelled_by_shutdown(language_app, monkeypatch, pump_events):
    c = language_app
    greeting = Mock()
    monkeypatch.setattr(gui_app, '_announce_startup_greeting', greeting)
    c['shutdown']()
    elapsed = []
    gui_app.QTimer.singleShot(1400, lambda: elapsed.append(True))
    assert pump_events(lambda: bool(elapsed), timeout=3)
    greeting.assert_not_called()


def test_late_state_signals_do_not_reactivate_closed_voice_ui(language_app):
    c = language_app
    c['shutdown']()
    previous_feedback = c['window']._feedback_text
    c['realtime_worker'].state_changed.emit('listening')
    c['voice_worker'].state_changed.emit('listening')
    c['settings_page'].saved.emit()
    assert not c['window']._realtime_active
    assert c['window']._feedback_text == previous_feedback


def test_classic_dispatch_uses_spoken_email_after_executor(language_app, monkeypatch):
    c = language_app
    original = CommandResult(True, 'UNTRUSTED JSON', action='gmail_read', confirmed=True,
                             metadata={'private_content': True, 'tool_category': 'gmail', 'gmail_spoken_text': 'Meeting at ten.'})
    dispatch = Mock(return_value=original)
    monkeypatch.setattr(c['executor'], 'submit_blocking', dispatch)
    spoken = c['assistant']._dispatch('read email 1')
    dispatch.assert_called_once_with('read email 1')
    assert spoken.message == 'Meeting at ten.'
    assert spoken.confirmed is True
    assert original.message == 'UNTRUSTED JSON'
