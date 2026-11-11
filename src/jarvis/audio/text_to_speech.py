from __future__ import annotations

import logging
import os
import tempfile
import threading
import winsound
from collections.abc import Callable

from ..lang_detect import detect_language
from ..config import ensure_openai_api_key_visible
from .output_device import configured_output_device, play_wav_file
from ..user_settings import JarvisSettings
from ..privacy import redact_sensitive_text

logger = logging.getLogger(__name__)
DEFAULT_OPENAI_TTS_MODEL = "gpt-4o-mini-tts"
DEFAULT_OPENAI_TTS_VOICE = "cedar"
# Style/delivery only -- OpenAI TTS speaks whatever language `text` is
# actually written in regardless of this instruction, so it must stay
# language-neutral rather than naming a specific language (previously
# "Speak English in a calm..." here silently fought Bulgarian replies).
DEFAULT_OPENAI_TTS_INSTRUCTIONS = "Speak in a calm, natural, conversational voice."
OPENAI_TTS_VOICES = (
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "nova",
    "onyx",
    "sage",
    "shimmer",
    "verse",
    "marin",
    "cedar",
)

_VOICE_NAME_HINTS = {
    "bg": ("bulgarian", "bg-bg", "bg_bg", "ivan"),
    "en": ("english", "en-us", "en_us", "david", "zira", "mark"),
}
# SAPI token "Language" attributes are hex LCIDs, e.g. "409" or "409;9".
_VOICE_LCIDS = {"402": "bg", "409": "en", "809": "en"}
_SAPI_VOICE_KEYS = (r"SOFTWARE\Microsoft\Speech\Voices\Tokens",
                    r"SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens")


def windows_voice_languages() -> set[str]:
    """Languages of the Windows (SAPI) voices the offline engine can use,
    read from the registry without starting a speech engine -- cheap enough
    for Settings to warn that Bulgarian replies would be silent."""
    if os.name != "nt":
        return set()
    import winreg

    found: set[str] = set()
    for path in _SAPI_VOICE_KEYS:
        try:
            voices = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path)
        except OSError:
            continue
        with voices:
            index = 0
            while True:
                try:
                    token = winreg.EnumKey(voices, index)
                except OSError:
                    break
                index += 1
                text, lcids = token.lower(), []
                try:
                    with winreg.OpenKey(voices, token + r"\Attributes") as attributes:
                        for name in ("Name", "Language"):
                            try:
                                value = str(winreg.QueryValueEx(attributes, name)[0]).lower()
                            except OSError:
                                continue
                            text += " " + value
                            if name == "Language":
                                lcids = [part.strip() for part in value.split(";")]
                except OSError:
                    pass
                found.update(_VOICE_LCIDS[lcid] for lcid in lcids if lcid in _VOICE_LCIDS)
                found.update(lang for lang, hints in _VOICE_NAME_HINTS.items() if any(hint in text for hint in hints))
    return found


def speak_with_openai(
    text: str,
    model: str = DEFAULT_OPENAI_TTS_MODEL,
    voice: str = DEFAULT_OPENAI_TTS_VOICE,
    instructions: str | None = DEFAULT_OPENAI_TTS_INSTRUCTIONS,
    client=None,
    on_error: Callable[[str], None] | None = None,
) -> bool:
    def fail(message: str) -> bool:
        clean = redact_sensitive_text(message).text
        logger.warning("OpenAI text-to-speech failed: %s", clean)
        if on_error is not None:
            on_error(clean)
        return False

    ensure_openai_api_key_visible()
    if not os.getenv("OPENAI_API_KEY"):
        return fail("OPENAI_API_KEY is missing. Add the key locally and restart Jarvis.")
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package is not installed; OpenAI text-to-speech is unavailable.")
        return fail("Install the openai package to enable this voice.")

    owned_client = client is None
    client = client or OpenAI(timeout=20.0, max_retries=0)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_path = temp_file.name

        request = {
            "model": model,
            "voice": voice,
            "input": text,
            "response_format": "wav",
        }
        if instructions:
            request["instructions"] = instructions

        with client.audio.speech.with_streaming_response.create(**request) as response:
            response.stream_to_file(temp_path)

        if not play_wav_file(temp_path):
            if configured_output_device() is not None:
                return fail("Speech was generated, but the selected speaker could not play it. Choose an available audio output in Settings.")
            winsound.PlaySound(temp_path, winsound.SND_FILENAME)
        return True
    except Exception as exc:
        return fail(str(exc))
    finally:
        if owned_client:
            client.close()
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


class TextToSpeech:
    """Wraps pyttsx3 for offline Bulgarian/English speech output.

    pyttsx3 drives a single SAPI5 engine; concurrent speak() calls from
    multiple threads would corrupt its internal queue, so every call goes
    through one lock and callers can safely share one instance.
    """

    def __init__(
        self,
        rate: int | None = None,
        volume: float | None = None,
        enabled: bool = True,
        provider: str | None = None,
        openai_model: str | None = None,
        openai_voice: str | None = None,
        openai_instructions: str | None = None,
    ) -> None:
        ensure_openai_api_key_visible()
        self.enabled = enabled
        self.last_error = ""
        self._engine_thread = threading.get_ident()
        self._rate = rate
        self._volume = volume
        self._lock = threading.Lock()
        self._engine = None
        self._voices_by_lang: dict[str, str] = {}
        settings = JarvisSettings.load()
        openai_settings = settings.openai
        self.provider = provider or os.getenv("JARVIS_TTS_PROVIDER") or str(
            openai_settings.get("tts_provider") or ("openai" if os.getenv("OPENAI_API_KEY") else "windows")
        )
        self.openai_model = openai_model or os.getenv(
            "JARVIS_TTS_MODEL",
            str(openai_settings.get("text_to_speech_model") or DEFAULT_OPENAI_TTS_MODEL),
        )
        self.openai_voice = openai_voice or os.getenv(
            "JARVIS_TTS_VOICE",
            str(openai_settings.get("text_to_speech_voice") or DEFAULT_OPENAI_TTS_VOICE),
        )
        self.openai_instructions = openai_instructions or os.getenv(
            "JARVIS_TTS_INSTRUCTIONS",
            str(openai_settings.get("text_to_speech_instructions") or DEFAULT_OPENAI_TTS_INSTRUCTIONS),
        )

        if not enabled:
            return

        provider_is_openai = self.provider.lower() == "openai"

        try:
            import pyttsx3
        except ImportError:
            if provider_is_openai:
                # self.enabled must reflect whether OpenAI TTS can actually
                # speak, not just "an enabled instance was requested" -- a
                # bare `return` here previously left self.enabled at its
                # constructor default (True) even with no working engine and
                # no API key, which fed a false "ready" readiness indicator.
                self.enabled = bool(os.getenv("OPENAI_API_KEY"))
                logger.warning(
                    "pyttsx3 not installed; Windows text-to-speech fallback is unavailable. %s",
                    "OpenAI text-to-speech can still be used because OPENAI_API_KEY is set."
                    if self.enabled
                    else "OPENAI_API_KEY is also not set, so text-to-speech is disabled.",
                )
                return
            logger.warning(
                "pyttsx3 not installed; text-to-speech is disabled. Install with: pip install -e .[voice]"
            )
            self.enabled = False
            return

        try:
            self._engine = pyttsx3.init()
        except Exception as exc:  # pragma: no cover - depends on the OS speech stack
            if provider_is_openai:
                self.enabled = bool(os.getenv("OPENAI_API_KEY"))
                logger.warning(
                    "Could not start Windows text-to-speech fallback: %s%s",
                    exc,
                    "" if self.enabled else " and OPENAI_API_KEY is not set; text-to-speech is disabled.",
                )
                return
            logger.warning("Could not start text-to-speech engine: %s", exc)
            self.enabled = False
            return

        if rate is not None:
            self._engine.setProperty("rate", rate)
        if volume is not None:
            self._engine.setProperty("volume", volume)

        self._index_voices()

    def _index_voices(self) -> None:
        for voice in self._get_voices():
            languages = " ".join(str(item) for item in (getattr(voice, "languages", None) or []))
            haystack = f"{voice.name} {voice.id} {languages}".lower()
            for lang, hints in _VOICE_NAME_HINTS.items():
                if lang in self._voices_by_lang:
                    continue
                if any(hint in haystack for hint in hints):
                    self._voices_by_lang[lang] = voice.id

    def _get_voices(self) -> list:
        if self._engine is None:
            return []
        try:
            return list(self._engine.getProperty("voices") or [])
        except Exception:  # pragma: no cover - depends on the OS speech stack
            return []

    def speak(self, text: str, lang: str | None = None) -> bool:
        """Speak text, blocking until done. Returns True if speech was attempted."""
        if not self.enabled or not text or not text.strip():
            return False

        lang = lang or detect_language(text)
        with self._lock:
            self.last_error = ""
            if self.provider == "openai":
                spoken = speak_with_openai(
                    text,
                    model=self.openai_model,
                    voice=self.openai_voice,
                    instructions=self.openai_instructions,
                    on_error=lambda message: setattr(self, "last_error", message),
                )
                if spoken:
                    return True
            if self._engine is None:
                self.last_error = self.last_error or "No speech engine is available. Check the selected voice provider."
                return False
            if self._engine_thread != threading.get_ident():
                # SAPI objects belong to the COM thread that created them.
                try:
                    import comtypes
                    import pyttsx3
                    comtypes.CoInitialize()
                    self._engine = None
                    self._engine = pyttsx3.init()
                    self._engine_thread = threading.get_ident()
                    self._voices_by_lang.clear()
                    self._index_voices()
                    if self._rate is not None:
                        self._engine.setProperty("rate", self._rate)
                    if self._volume is not None:
                        self._engine.setProperty("volume", self._volume)
                except Exception as exc:
                    self.last_error = redact_sensitive_text(f"Windows voice initialization failed: {exc}").text
                    return False
            if lang == "bg" and "bg" not in self._voices_by_lang:
                self.last_error = (self.last_error + " Windows has no Bulgarian fallback voice.").strip()
                return False
            try:
                voice_id = self._voices_by_lang.get(lang)
                if voice_id:
                    self._engine.setProperty("voice", voice_id)
                self._engine.say(text)
                self._engine.runAndWait()
            except Exception as exc:  # pragma: no cover - depends on the OS speech stack
                self.last_error = redact_sensitive_text(str(exc)).text
                logger.warning("Text-to-speech failed: %s", self.last_error)
                return False
        return True

    def available_languages(self) -> list[str]:
        return sorted(self._voices_by_lang)

    def describe_voices(self) -> list[str]:
        lines = []
        for voice in self._get_voices():
            languages = getattr(voice, "languages", None) or []
            lines.append(f"{voice.name} | id={voice.id} | languages={languages}")
        return lines

    def describe_openai_voices(self) -> list[str]:
        return [f"{voice} | OpenAI {self.openai_model}" for voice in OPENAI_TTS_VOICES]

    def status_summary(self) -> dict[str, object]:
        """Small diagnostic payload for GUI/settings status surfaces."""
        ensure_openai_api_key_visible()
        openai_key_present = bool(os.getenv("OPENAI_API_KEY"))
        return {
            "enabled": self.enabled,
            "provider": self.provider,
            "openai_key_present": openai_key_present,
            "openai_model": self.openai_model,
            "openai_voice": self.openai_voice,
            "windows_fallback_available": self._engine is not None,
            "available_languages": self.available_languages(),
            "last_error": self.last_error,
        }
