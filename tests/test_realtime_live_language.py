"""Switching the conversation language without a restart: the running Live
call (session.update), the worker, the HUD switch and the voice tool."""
from __future__ import annotations

import asyncio
import json

import pytest
from PySide6.QtCore import QObject, Signal

from jarvis import trusted_actions
from jarvis.audit import AuditLogger
from jarvis.gui.main_window import MainWindow
from jarvis.gui.profile_wiring import ProfileController
from jarvis.gui.realtime_worker import RealtimeVoiceWorker
from jarvis.gui.settings_page import SettingsPage
from jarvis.profiles import ProfileStore
from jarvis.realtime import RealtimeVoiceConfig, RealtimeVoiceSession
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.tool_registry import ToolCall
from jarvis.user_settings import JarvisSettings
from jarvis.windows_actions import WindowsActions


def _config(language: str) -> RealtimeVoiceConfig:
    return RealtimeVoiceConfig.from_settings(JarvisSettings(openai={"conversation_language": language}))


def test_live_update_changes_instructions_and_transcription_but_not_the_voice():
    event = _config("en").live_update_event()
    session = event["session"]
    assert event["type"] == "session.update" and session["type"] == "realtime"
    assert "Speak and reply only in English" in session["instructions"]
    assert session["audio"] == {"input": {"transcription": _config("en").session_update_event()["session"]
                                          ["audio"]["input"]["transcription"]}}
    assert "voice" not in json.dumps(session) and "tools" not in session


def test_a_running_call_switches_within_the_watch_loop():
    session = RealtimeVoiceSession(_config("bg"))
    session.update_live_config(_config("bg"))  # nothing changed: nothing to send
    assert session._take_live_update() is None
    session.update_live_config(_config("en"))
    update = session._take_live_update()
    events = session._live_update_events(update)
    assert events[0]["type"] == "session.update" and session.config.conversation_language == "en"
    assert "switched the conversation language to English" in events[1]["item"]["content"][0]["text"]
    assert events[1]["item"]["role"] == "system"


def test_the_watch_loop_sends_the_update():
    session = RealtimeVoiceSession(_config("bg"))
    sent = []

    class Socket:
        async def send(self, text):
            sent.append(json.loads(text))
            raise asyncio.CancelledError  # stop the loop after the first event

    class Playback:
        pending = False
        error = ""

        def interrupt(self):
            return []

    session.update_live_config(_config("en"))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(session._watch_playback(Playback(), None, Socket(), None))
    assert sent[0]["type"] == "session.update"


def test_the_worker_updates_a_running_call_or_the_next_one(qapp):
    session = RealtimeVoiceSession(_config("bg"))
    worker = RealtimeVoiceWorker(session, lambda name, arguments: {})
    assert worker.update_live_config(_config("en")) is False
    assert session.config.conversation_language == "en"  # used by the next call
    worker._running = True
    assert worker.update_live_config(_config("bg")) is True
    assert session._take_live_update().conversation_language == "bg"


class FakeExecutor(QObject):
    result_ready = Signal(str, str, object)

    def submit(self, *args, **kwargs):
        pass

    def submit_tool(self, *args, **kwargs):
        pass


class Voice:
    language = None

    def set_conversation_language(self, code):
        self.language = code


@pytest.fixture
def controller(qapp, tmp_path):
    settings = JarvisSettings(personalization={"address_name": "Берк"}, openai={"conversation_language": "bg"})
    store = ProfileStore(tmp_path / "profiles", settings=settings, windows_user="Berk")
    router = CommandRouter(WindowsActions(dry_run=True), SafetyPolicy(), settings=settings)
    window = MainWindow()
    page = SettingsPage(settings, settings_path=tmp_path / "settings.json")
    window.set_settings_widget(page)
    stt = Voice()
    controller = ProfileController(store, window=window, settings_page=page, router=router, executor=FakeExecutor(),
                                   audit=AuditLogger(tmp_path / "audit.jsonl"), settings=settings, stt=stt)
    yield controller
    trusted_actions.allow_full_access(True)
    window.deleteLater()


def test_the_header_switch_applies_everywhere_at_once(controller):
    changed = []
    controller.language_changed.connect(changed.append)
    window = controller.window
    assert window._language_button.isVisibleTo(window) and window._language_button.text() == "БГ"
    window._language_actions["en"].trigger()
    assert changed == ["en"]
    assert controller.store.active()["language"] == "en"
    assert controller.settings.conversation_language == "en" and controller.stt.language == "en"
    assert window._language_button.text() == "EN" and window._language_actions["en"].isChecked()
    page = controller.settings_page
    assert page._language_combo.currentData() == "en"


def test_the_voice_tool_switches_language(controller, qapp):
    changed = []
    controller.language_changed.connect(changed.append)
    result = controller.router.tools.execute(ToolCall("set_conversation_language", {"language": "English"}))
    assert result.ok and result.message == "Switched to English."
    qapp.processEvents()
    assert changed == ["en"] and controller.store.active()["language"] == "en"
    bad = controller.router.tools.execute(ToolCall("set_conversation_language", {"language": "klingon"}))
    assert not bad.ok
