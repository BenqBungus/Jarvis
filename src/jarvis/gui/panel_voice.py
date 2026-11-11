"""Shared opt-in realtime voice ownership for screen and gaming panels."""
from dataclasses import replace
import json

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QHBoxLayout, QLabel,
                             QPushButton, QStyle, QToolButton, QVBoxLayout, QWidget)

from ..realtime import RealtimeVoiceConfig, RealtimeVoiceSession, realtime_tool_schemas
from .aurora import segmented, set_role
from .realtime_worker import RealtimeVoiceWorker
from .voice_core import glyph_icon

NATURAL_DELIVERY = (
    "Speak naturally to one person, not like a presenter. Use comfortable pacing, short phrases, "
    "natural pauses and varied intonation. Avoid repetitive greetings, exaggerated enthusiasm, "
    "announcing every step, or reading markdown and URLs aloud. Be concise during gameplay. "
    "Do not repeatedly use the user's name. Let the user finish; stop promptly when interrupted. "
)


def natural_config(config):
    return replace(config, instructions=config.instructions + "\n" + NATURAL_DELIVERY)


class PanelVoiceControls(QWidget):
    mode_changed = Signal(int)
    call_requested = Signal()
    interrupt_requested = Signal()
    mute_changed = Signal(bool)

    def __init__(self, parent=None, *, commands=False, screen_optional=False):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        group = QButtonGroup(self)
        self.text_mode = QPushButton("Text")
        self.voice_mode = QPushButton("Voice")
        for index, button in enumerate((self.text_mode, self.voice_mode)):
            button.setCheckable(True)
            group.addButton(button, index)
        row.addWidget(segmented(self.text_mode, self.voice_mode))
        self.text_mode.setChecked(True)
        group.idClicked.connect(self.mode_changed)
        row.addStretch()
        self.call = self._button("mic", QStyle.StandardPixmap.SP_MediaPlay, "Start / stop voice conversation")
        self.call.clicked.connect(self.call_requested)
        self.mute = self._button("mic", QStyle.StandardPixmap.SP_MediaVolumeMuted, "Mute microphone")
        self.mute.setCheckable(True)
        self.mute.toggled.connect(self.mute_changed)
        self.interrupt = self._button("skip", QStyle.StandardPixmap.SP_MediaStop, "Interrupt Jarvis")
        self.interrupt.clicked.connect(self.interrupt_requested)
        set_role(self.call, "call", active="false")
        for button in (self.mute, self.interrupt):
            set_role(button, "ghost")
        for button in (self.mute, self.interrupt, self.call):
            row.addWidget(button)
        layout.addLayout(row)
        options = QHBoxLayout()
        self.commands = QCheckBox("Commands")
        self.commands.setToolTip("Allow requested laptop actions through Jarvis permissions. Discussion alone performs no actions.")
        self.commands.setVisible(commands)
        options.addWidget(self.commands)
        self.screen = QCheckBox("Share screen")
        self.screen.setToolTip("Ask permission to send primary-screen images to the voice model until Stop.")
        self.screen.setVisible(screen_optional)
        options.addWidget(self.screen)
        options.addStretch()
        layout.addLayout(options)
        self.state = QLabel("Voice off")
        self.state.setObjectName("panelVoiceState")
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.set_active(False)

    def _button(self, name, fallback, label):
        button = QToolButton()
        button.setFixedSize(34, 34)
        button.setIcon(glyph_icon(name, fallback, self.style()))
        button.setToolTip(label)
        button.setAccessibleName(label)
        return button

    def set_active(self, active):
        self.call.setIcon(glyph_icon("hang_up" if active else "mic",
            QStyle.StandardPixmap.SP_MediaStop if active else QStyle.StandardPixmap.SP_MediaPlay, self.style(),
            color="#04131A", size=18))
        if self.call.property("active") != ("true" if active else "false"):
            self.call.setProperty("active", "true" if active else "false")
            self.call.style().unpolish(self.call)
            self.call.style().polish(self.call)
        self.mute.setEnabled(active)
        self.interrupt.setEnabled(active)
        self.commands.setEnabled(not active)
        self.screen.setEnabled(not active)
        if not active:
            self.mute.blockSignals(True)
            self.mute.setChecked(False)
            self.mute.blockSignals(False)


class PanelVoiceController(QObject):
    """One panel call at a time; all workers share the application's mic lock."""
    state_changed = Signal(str)
    def __init__(self, settings, router, executor, speech, mic_lock, indicator,
                 pause_others, resume_others, *, dry_run=False):
        super().__init__()
        self.settings, self.router, self.executor = settings, router, executor
        self.speech, self.mic_lock, self.indicator = speech, mic_lock, indicator
        self.pause_others, self.resume_others = pause_others, resume_others
        self.dry_run = dry_run
        self.worker = None
        self.owner = None
        self._generation = 0
        self._closed = False
        self._owns_screen = False
        self._actions = False
        self._starting = False
        self._accept_events = False

    @property
    def active(self):
        return self._starting or (self.worker is not None and self.worker.running)

    def start(self, owner, *, context="", screen=False, commands=False, game=None, web=False):
        if self._closed:
            return False
        if self.active:
            owner.voice_controls.state.setText("Stop the current panel call before starting another.")
            return False
        if self.dry_run:
            owner.voice_controls.state.setText("Dry run: microphone and screen capture are disabled.")
            return False
        self._generation += 1
        generation = self._generation
        config = natural_config(RealtimeVoiceConfig.from_settings(self.settings))
        tools = realtime_tool_schemas(self.router.tools) if commands else []
        if game and not commands:
            tools = [{"type": "function", "name": "game_advice", "description": "Get detailed gaming advice and optional web sources.",
                      "parameters": {"type": "object", "properties": {"question": {"type": "string"}},
                                     "required": ["question"], "additionalProperties": False}}]
        boundary = ("Requested laptop actions must use the registered permission-gated tools. " if commands else
                    "Discussion only. No computer actions are available. Never claim to operate the game or laptop. ")
        config = replace(config, tools=tools, greeting="", instructions=config.instructions + "\n" + boundary
                         + "Only use current screen context while sharing is enabled. "
                         + "Game/context supplied by user: " + json.dumps(context[:2000], ensure_ascii=False))
        session = RealtimeVoiceSession(config, memory=None, memory_enabled=lambda: False,
                                       screen_sharing=self.router.screen_sharing if screen else None)
        status = session.readiness()
        if not status["ready"]:
            owner.voice_controls.state.setText("Voice unavailable: " + ", ".join(status["missing"]))
            return False
        if screen:
            result = self.router.screen_sharing.start()
            self.indicator.refresh()
            if not result.ok or not self.router.screen_sharing.state()["ready"]:
                self.indicator.stop()
                owner.voice_controls.state.setText(result.message)
                return False
        self._owns_screen, self._actions = screen, commands
        self.owner = owner
        self._accept_events = True

        def dispatch(name, arguments):
            if generation != self._generation or self._closed:
                return {"ok": False, "message": "Panel call stopped."}
            if commands:
                return self.executor.submit_tool_blocking(name, arguments)
            if game and name == "game_advice" and isinstance(arguments, dict) and set(arguments) == {"question"} and isinstance(arguments["question"], str):
                result = self.router.ai.answer_game_question(arguments["question"], game=game,
                    context=context[:600], web=web)
                return {"ok": result.ok, "message": result.message, "metadata": result.metadata}
            return {"ok": False, "message": "No action tools are available in this discussion."}

        worker = RealtimeVoiceWorker(session, dispatch, mic_lock=self.mic_lock)
        self.worker = worker
        worker.state_changed.connect(lambda state: self._state(worker, state))
        worker.detail_changed.connect(lambda detail: self._detail(worker, detail))
        worker.transcript_completed.connect(lambda who, text: self._transcript(worker, who, text))
        worker.session_stopped.connect(lambda: self._stopped(worker))
        self.speech.suspend()
        self._starting = True
        self.pause_others()
        owner.voice_controls.voice_mode.setChecked(True)
        owner.voice_controls.set_active(True)
        owner.voice_controls.state.setText("Connecting...")
        self.state_changed.emit("connecting")
        started = worker.start()
        self._starting = False
        if not started:
            self._stopped(worker)
            return False
        return True

    def _state(self, worker, state):
        if self.worker is worker and self.owner and self._accept_events and not self._closed:
            self.owner.voice_controls.state.setText(state.capitalize())
            self.state_changed.emit(state)

    def _detail(self, worker, detail):
        if self.worker is worker and self.owner and self._accept_events and not self._closed:
            self.owner.voice_controls.state.setText(detail)

    def _transcript(self, worker, who, text):
        if self.worker is worker and self.owner and self._accept_events and not self._closed:
            self.owner.append_voice_transcript(who, text)

    def stop(self, owner=None):
        if owner is not None and owner is not self.owner:
            return
        self._generation += 1
        self._accept_events = False
        if self._owns_screen:
            self.indicator.stop()
            self._owns_screen = False
        if self._actions and self.active:
            self.executor.cancel_pending()
        if self.worker:
            self.worker.stop()
        if self.owner:
            self.owner.voice_controls.set_active(False)
            self.owner.voice_controls.state.setText("Stopping voice...")

    def _stopped(self, worker):
        if self.worker is not worker:
            return
        self._generation += 1
        self._starting = False
        self._accept_events = False
        if self._owns_screen:
            self.indicator.stop()
            self._owns_screen = False
        owner, self.owner = self.owner, None
        self.worker = None
        self.state_changed.emit("idle")
        if owner:
            owner.voice_controls.set_active(False)
            # Keep errors visible instead of replacing them with a false ready state.
            if owner.voice_controls.state.text() in {"Idle", "Stopping voice...", "Connecting..."}:
                owner.voice_controls.state.setText("Voice off")
        if not self._closed:
            self.speech.resume()
            self.resume_others()
        worker.deleteLater()

    def mute(self, owner, muted):
        if self.owner is owner and self.active:
            self.worker.set_input_muted(muted)

    def interrupt(self, owner):
        if self.owner is owner and self.active:
            self.worker.interrupt_speech()

    def shutdown(self):
        self._closed = True
        self.stop()
