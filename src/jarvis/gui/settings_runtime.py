"""Apply saved controls at a safe audio boundary without rebuilding the UI."""
import os
from contextlib import ExitStack

from PySide6.QtCore import QObject, QTimer

from ..ai_client import DEFAULT_MODEL
from ..audio.text_to_speech import DEFAULT_OPENAI_TTS_INSTRUCTIONS
from .panel_voice import NATURAL_DELIVERY


class SettingsRuntime(QObject):
    def __init__(self, settings, stt, tts, assistant, mic_lock, busy, screen_chat, page, parent=None):
        super().__init__(parent)
        self.settings, self.stt, self.tts, self.assistant = settings, stt, tts, assistant
        self.mic_lock, self.busy, self.screen_chat, self.page = mic_lock, busy, screen_chat, page
        self._pending = False
        self._save_error = ""
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.apply_audio)
        page._browser_combo.currentTextChanged.connect(self.load_browser_path)
        page.saved.connect(self.saved)

    def load_browser_path(self, browser):
        self.page._browser_path_input.setText(self.settings.browser_paths.get(browser.strip().lower(), ""))

    def saved(self):
        self._save_error = ""
        browser = self.settings.preferred_browser
        if browser and not self.page._browser_path_input.text().strip():
            self.settings.browser_paths.pop(browser, None)
            try:
                self.settings.save(self.page._settings_path)
            except OSError:
                self._save_error = "Could not save cleared browser path. "
        model = str(self.settings.openai.get("model") or DEFAULT_MODEL).strip()
        if self.page._ai is not None:
            self.page._ai.model = model
        os.environ["JARVIS_OPENAI_MODEL"] = model
        self.screen_chat.sharing.ai.model = model
        self.screen_chat.model_label.setText(model)
        # A deliberate UI save takes precedence over process-local audio overrides.
        for name in ("JARVIS_STT_PROVIDER", "JARVIS_STT_MODEL", "JARVIS_TTS_PROVIDER", "JARVIS_TTS_MODEL", "JARVIS_TTS_VOICE", "JARVIS_AUDIO_OUTPUT_DEVICE"):
            os.environ.pop(name, None)
        self._pending = True
        if not self.apply_audio():
            self.page._status_label.setText(self._save_error + "Audio changes apply when the current call finishes.")
            self.timer.start()

    def apply_audio(self):
        if not self._pending or self.busy():
            return False
        with ExitStack() as locks:
            for lock in (self.mic_lock, getattr(self.tts, "_lock", None), getattr(self.stt, "_listen_lock", None)):
                if lock is not None:
                    if not lock.acquire(blocking=False):
                        return False
                    locks.callback(lock.release)
            data = self.settings.openai
            self.stt.provider = str(data.get("speech_to_text_provider") or "google")
            self.stt.openai_model = str(data.get("speech_to_text_model") or "gpt-transcribe")
            recognizer = getattr(self.stt, "_recognizer", None)
            if recognizer is not None:
                energy = data.get("energy_threshold")
                recognizer.energy_threshold = energy or 300
                recognizer.dynamic_energy_threshold = not bool(energy)
                recognizer.pause_threshold = max(0.3, float(data.get("pause_threshold_ms") or 800)/1000)
                recognizer.non_speaking_duration = min(recognizer.non_speaking_duration, recognizer.pause_threshold)
            self.tts.provider = str(data.get("tts_provider") or "windows")
            self.tts.openai_model = str(data.get("text_to_speech_model") or "gpt-4o-mini-tts")
            self.tts.openai_voice = str(data.get("text_to_speech_voice") or "cedar")
            custom = data.get("text_to_speech_instructions")
            self.tts.openai_instructions = str(custom) if custom and custom != DEFAULT_OPENAI_TTS_INSTRUCTIONS else NATURAL_DELIVERY
            self.tts.enabled = bool((self.tts.provider == "openai" and os.getenv("OPENAI_API_KEY")) or getattr(self.tts, "_engine", None))
            if hasattr(self.assistant, "tts"):
                self.assistant.tts.enabled = self.tts.enabled
        self._pending = False
        self.timer.stop()
        self.page._status_label.setText(self._save_error + "Audio settings applied; Live changes use the next call.")
        return True

    def stop(self):
        self.timer.stop()
        self._pending = False
