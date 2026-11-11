from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from jarvis.gui.panel_voice import PanelVoiceController
from jarvis.gui.game_chat import GameChatDialog
from jarvis.gui.screen_chat import ScreenChatDialog
from jarvis.models import CommandResult
from jarvis.tool_registry import ToolRegistry
from jarvis.user_settings import JarvisSettings
from jarvis.vision.sharing import ScreenSharing


class FakeWorker(QObject):
    state_changed = Signal(str)
    detail_changed = Signal(str)
    transcript_completed = Signal(str, str)
    session_stopped = Signal()

    def __init__(self, session, dispatch, *, mic_lock):
        super().__init__()
        self.session, self.dispatch, self.mic_lock = session, dispatch, mic_lock
        self.running = False
        self.muted = False
        self.interrupted = False
        self.stopping = False

    def start(self):
        self.running = True
        self.state_changed.emit("listening")
        return True

    def stop(self):
        self.stopping = True

    def finish(self):
        self.running = False
        self.session_stopped.emit()

    def set_input_muted(self, muted):
        self.muted = muted

    def interrupt_speech(self):
        self.interrupted = True


@pytest.fixture
def rig(qapp, monkeypatch):
    monkeypatch.setattr("jarvis.gui.panel_voice.RealtimeVoiceWorker", FakeWorker)
    monkeypatch.setattr("jarvis.gui.panel_voice.RealtimeVoiceSession.readiness", lambda self: {"ready": True, "missing": []})
    sharing = ScreenSharing(ai=MagicMock())
    sharing.indicator_available = True
    indicator = SimpleNamespace(refresh=sharing.indicator_visible, stop=sharing.stop)
    router = SimpleNamespace(screen_sharing=sharing, ai=MagicMock(), tools=ToolRegistry())
    executor, speech, pause, resume = MagicMock(), MagicMock(), MagicMock(), MagicMock()
    lock = object()
    controller = PanelVoiceController(JarvisSettings(openai={"conversation_language": "bg", "realtime_voice": "cedar"}),
        router, executor, speech, lock, indicator, pause, resume)
    dialog = GameChatDialog(router.ai)
    dialog.game.setText("Valorant")
    dialog.voice_controller = controller
    yield SimpleNamespace(c=controller, d=dialog, router=router, speech=speech, executor=executor, lock=lock, pause=pause, resume=resume)
    worker = controller.worker
    controller.shutdown()
    if worker:
        worker.finish()
    dialog.shutdown()


def test_advice_voice_has_no_memory_or_desktop_tools(rig):
    assert rig.c.start(rig.d, context="Ascent", game="Valorant")
    worker = rig.c.worker
    assert worker.mic_lock is rig.lock
    assert worker.session.memory is None and not worker.session._memory_enabled()
    assert worker.session.screen_sharing is None
    assert worker.session.config.conversation_language == "bg"
    assert worker.session.config.voice == "cedar"
    assert "comfortable pacing" in worker.session.config.instructions
    assert [t["name"] for t in worker.session.config.tools] == ["game_advice"]
    assert not worker.dispatch("shutdown", {})["ok"]
    rig.executor.submit_tool_blocking.assert_not_called()
    rig.pause.assert_called_once()
    rig.speech.suspend.assert_called_once()


def test_game_advice_tool_and_input_validation(rig):
    rig.router.ai.answer_game_question.return_value = CommandResult(True, "Answer")
    rig.c.start(rig.d, game="Valorant", web=True)
    worker = rig.c.worker
    assert worker.dispatch("game_advice", {"question": "Patch?"})["ok"]
    assert rig.router.ai.answer_game_question.call_args.kwargs["web"] is True
    assert not worker.dispatch("game_advice", {"question": {}, "extra": 1})["ok"]
    assert not worker.dispatch("game_advice", None)["ok"]


def test_discussion_screen_stream_is_opt_in_and_stops(rig):
    assert rig.c.start(rig.d, screen=True)
    assert rig.c.worker.session.screen_sharing is rig.router.screen_sharing
    assert rig.router.screen_sharing.state()["ready"]
    assert not rig.c.worker.session.config.tools
    rig.c.stop(rig.d)
    assert not rig.router.screen_sharing.state()["sharing"]


def test_commands_always_dispatch_through_existing_executor(rig):
    rig.executor.submit_tool_blocking.return_value = {"ok": False, "message": "Denied"}
    rig.c.start(rig.d, commands=True)
    result = rig.c.worker.dispatch("restart", {})
    assert not result["ok"]
    rig.executor.submit_tool_blocking.assert_called_once_with("restart", {})
    rig.c.stop()
    rig.executor.cancel_pending.assert_called_once()


def test_stop_rejects_late_tool_and_transcript_and_blocks_new_call_until_finish(rig):
    rig.c.start(rig.d)
    worker = rig.c.worker
    worker.transcript_completed.emit("You", "Visible")
    assert "Visible" in rig.d.messages.toPlainText()
    rig.c.stop()
    worker.transcript_completed.emit("Jarvis", "STALE")
    assert "STALE" not in rig.d.messages.toPlainText()
    assert not worker.dispatch("restart", {})["ok"]
    assert not rig.c.start(rig.d)
    worker.finish()
    assert not rig.c.active
    rig.speech.resume.assert_called_once()


def test_shutdown_cannot_resume_microphone(rig):
    rig.c.start(rig.d, screen=True)
    worker = rig.c.worker
    rig.c.shutdown()
    worker.finish()
    rig.speech.resume.assert_not_called()
    rig.resume.assert_not_called()
    assert not rig.router.screen_sharing.state()["ready"]


def test_mute_interrupt_and_owner_isolation(rig):
    rig.c.start(rig.d)
    worker = rig.c.worker
    rig.c.mute(object(), True)
    assert not worker.muted
    rig.c.mute(rig.d, True)
    rig.c.interrupt(rig.d)
    assert worker.muted and worker.interrupted
    rig.c.stop(object())
    assert not worker.stopping


@pytest.mark.parametrize("unavailable", ["dry_run", "missing_dependency"])
def test_no_devices_or_capture_when_not_ready(rig, monkeypatch, unavailable):
    if unavailable == "dry_run":
        rig.c.dry_run = True
    else:
        monkeypatch.setattr("jarvis.gui.panel_voice.RealtimeVoiceSession.readiness", lambda self: {"ready": False, "missing": ["sounddevice"]})
    assert not rig.c.start(rig.d, screen=True)
    assert not rig.router.screen_sharing.state()["sharing"]
    rig.pause.assert_not_called()


def test_hidden_game_call_continues_but_context_change_stops_it(rig):
    rig.c.start(rig.d, game="Valorant")
    rig.d.hide()
    assert rig.c.active and not rig.c.worker.stopping
    rig.d.context.setText("Different map")
    assert rig.c.worker.stopping


def test_panel_states_reach_desktop_and_web_change_stops_call(rig):
    states = []
    rig.c.state_changed.connect(states.append)
    rig.c.start(rig.d, game="Valorant")
    assert states == ["connecting", "listening"]
    worker = rig.c.worker
    rig.d.web.setChecked(True)
    assert worker.stopping
    worker.state_changed.emit("speaking")
    assert "speaking" not in states
    worker.finish()
    assert states[-1] == "idle"


def test_project_check_blocks_screen_text_commands(qapp):
    d = ScreenChatDialog(ai=MagicMock())
    sent = []
    d.command_submitted.connect(lambda *args: sent.append(args))
    try:
        d._project_panel = SimpleNamespace(session_active=True)
        d.voice_controls.commands.setChecked(True)
        d.question.setText("open Notepad")
        d.send_question()
        assert not sent and not d._command_pending
    finally:
        d._project_panel = None
        d.shutdown()


def test_declining_panel_voice_never_starts_capture(rig, monkeypatch):
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    rig.d.toggle_voice()
    assert rig.c.worker is None
    assert not rig.router.screen_sharing.state()["sharing"]


def test_screen_text_command_uses_signal_not_vision(qapp):
    d = ScreenChatDialog(ai=MagicMock())
    sent = []
    d.command_submitted.connect(lambda *args: sent.append(args))
    try:
        d.voice_controls.commands.setChecked(True)
        d.question.setText("open Notepad")
        d.send_question()
        assert len(sent) == 1 and sent[0][0] == "open Notepad"
        d.sharing.ai.describe_image_bytes.assert_not_called()
        d.on_command_result(sent[0][1], sent[0][0], CommandResult(True, "Opened"))
        assert "Opened" in d.messages.toPlainText() and not d._command_pending
    finally:
        d.shutdown()


def test_screen_close_cancels_and_drops_late_command(qapp):
    d = ScreenChatDialog(ai=MagicMock())
    sent, cancelled = [], []
    d.command_submitted.connect(lambda *args: sent.append(args))
    d.command_cancel_requested.connect(lambda: cancelled.append(True))
    try:
        d.voice_controls.commands.setChecked(True)
        d.question.setText("open Notepad")
        d.send_question()
        d.reject()
        d.on_command_result(sent[0][1], sent[0][0], CommandResult(True, "STALE"))
        assert cancelled == [True] and "STALE" not in d.messages.toPlainText()
    finally:
        d.shutdown()
