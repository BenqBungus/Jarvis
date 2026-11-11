from __future__ import annotations

import logging
import os
import tempfile
import threading
from dataclasses import dataclass

from ..lang_detect import detect_language
from ..config import ensure_openai_api_key_visible
from ..user_settings import JarvisSettings
from .language import transcription_language_options

logger = logging.getLogger(__name__)

DEFAULT_LANGUAGES = ("en-US",)
DEFAULT_OPENAI_TRANSCRIBE_MODEL = "gpt-transcribe"

# Google's free recognize_google() needs a single BCP-47-ish locale per
# attempt, tried in order until one produces a non-empty result -- distinct
# from the bare "en"/"bg"/"auto" conversation_language codes used elsewhere.
# "auto" tries Bulgarian first (this app's primary audience) then English,
# but this is a much weaker approximation than the OpenAI provider path:
# Google's API tends to force-transcribe into whichever locale is requested
# rather than cleanly rejecting a mismatch, so real per-utterance language
# detection mainly happens on the OpenAI path (also this app's effective
# default whenever an API key is present).
_LANGUAGE_TO_GOOGLE_CODES = {
    "en": ("en-US",),
    "bg": ("bg-BG",),
    "auto": ("bg-BG", "en-US"),
}

# Biases the OpenAI transcription model's vocabulary/spelling -- not a
# system instruction, so plain descriptive English text is fine even for
# the "bg" case; what matters is naming the wake word's actual spelling.
_TRANSCRIPTION_PROMPT_HINTS = {
    "en": "The conversation is in English. Preserve app names, website names, and the wake words Hey Jarvis as accurately as possible.",
    "bg": "The conversation is in Bulgarian. Preserve app names, website names, and the wake words Джарвис / Здравей Джарвис as accurately as possible.",
    "auto": "The conversation may be in English or Bulgarian. Preserve app names, website names, and the wake words Hey Jarvis / Джарвис as accurately as possible.",
}


@dataclass(frozen=True)
class RecognizedSpeech:
    text: str
    language: str


def recognize_with_fallback(audio, recognizer, sr_module, languages=DEFAULT_LANGUAGES) -> RecognizedSpeech | None:
    """Try Google Web Speech recognition in each language in turn, returning
    the first non-empty transcription. Kept as a free function (recognizer
    and sr_module passed in) so the fallback logic is testable without a
    real microphone, network call, or the SpeechRecognition package."""
    for language in languages:
        try:
            text = recognizer.recognize_google(audio, language=language)
        except sr_module.UnknownValueError:
            continue
        except sr_module.RequestError as exc:
            logger.warning("Speech recognition request failed (%s): %s", language, exc)
            continue
        if text and text.strip():
            return RecognizedSpeech(text.strip(), language)
    return None


def recognize_with_openai(
    audio,
    model: str = DEFAULT_OPENAI_TRANSCRIBE_MODEL,
    client=None,
    lang: str = "en",
) -> RecognizedSpeech | None:
    """Transcribe captured SpeechRecognition audio with OpenAI.

    `audio` is a SpeechRecognition AudioData object. We write a temporary
    WAV file because the OpenAI transcription endpoint accepts file-like
    uploads and WAV keeps the capture lossless. The optional `client`
    parameter keeps this function testable without making network calls.
    """
    ensure_openai_api_key_visible()
    if client is None:
        if not os.getenv("OPENAI_API_KEY"):
            return None
        try:
            from openai import OpenAI
        except ImportError:
            logger.warning("openai package is not installed; OpenAI transcription is unavailable.")
            return None
        client = OpenAI()

    wav_data = audio.get_wav_data()
    prompt = (
        "The user is speaking to a Windows assistant named Jarvis. "
        + _TRANSCRIPTION_PROMPT_HINTS.get(lang, _TRANSCRIPTION_PROMPT_HINTS["en"])
    )

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
            temp_file.write(wav_data)
            temp_path = temp_file.name

        with open(temp_path, "rb") as audio_file:
            language_options = transcription_language_options(model, lang)
            request_options = ({"extra_body": language_options} if "languages" in language_options else language_options)
            transcription = client.audio.transcriptions.create(
                model=model,
                file=audio_file,
                prompt=prompt,
                **request_options,
            )
    except Exception as exc:
        logger.warning("OpenAI transcription failed: %s", exc)
        return None
    finally:
        if temp_path:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

    text = getattr(transcription, "text", None)
    if not text and isinstance(transcription, str):
        text = transcription
    if not text or not str(text).strip():
        return None

    lang = "bg-BG" if detect_language(str(text)) == "bg" else "en-US"
    return RecognizedSpeech(str(text).strip(), lang)


class SpeechToText:
    """Wraps SpeechRecognition with English-only capture by default.

    Uses the free Google Web Speech API through the `speech_recognition`
    package: no API key needed, but it requires internet access and has no
    official uptime or quota guarantee. Swap `recognize_with_fallback` for an
    offline engine later if that becomes a problem.
    """

    def __init__(
        self,
        languages: tuple[str, ...] | None = None,
        energy_threshold: int | None = None,
        pause_threshold: float | None = None,
        provider: str | None = None,
        openai_model: str | None = None,
        fallback_to_google: bool = True,
        conversation_language: str | None = None,
    ) -> None:
        ensure_openai_api_key_visible()
        settings = JarvisSettings.load()
        openai_settings = settings.openai
        self.conversation_language = conversation_language or settings.conversation_language
        self.languages = languages if languages is not None else _LANGUAGE_TO_GOOGLE_CODES.get(
            self.conversation_language, DEFAULT_LANGUAGES
        )
        self.provider = provider or os.getenv("JARVIS_STT_PROVIDER") or str(
            openai_settings.get("speech_to_text_provider") or ("openai" if os.getenv("OPENAI_API_KEY") else "google")
        )
        self.openai_model = openai_model or os.getenv(
            "JARVIS_STT_MODEL",
            str(openai_settings.get("speech_to_text_model") or DEFAULT_OPENAI_TRANSCRIBE_MODEL),
        )
        self.fallback_to_google = fallback_to_google
        self.available = False
        self._sr = None
        self._recognizer = None
        self._microphone = None
        self._listen_lock = threading.RLock()

        try:
            import speech_recognition as sr
        except ImportError:
            logger.warning(
                "SpeechRecognition not installed; voice input is disabled. "
                "Install with: pip install -e .[voice]"
            )
            return

        try:
            microphone = sr.Microphone()
        except Exception as exc:  # pragma: no cover - depends on local audio hardware/drivers
            logger.warning("No microphone available: %s", exc)
            return

        self._sr = sr
        self._recognizer = sr.Recognizer()
        self._microphone = microphone
        if energy_threshold is not None:
            self._recognizer.energy_threshold = energy_threshold
        if pause_threshold is not None:
            self._recognizer.pause_threshold = pause_threshold
        self.available = True

    def set_conversation_language(self, code: str) -> None:
        """Apply a new conversation language to this already-constructed
        instance -- lets a settings save take effect on the next listen_once()
        call without tearing down and reconstructing SpeechToText (which would
        also mean losing the live microphone/recognizer handles)."""
        self.conversation_language = code
        self.languages = _LANGUAGE_TO_GOOGLE_CODES.get(code, DEFAULT_LANGUAGES)

    def calibrate(self, duration: float = 0.5) -> None:
        if not self.available:
            return
        with self._listen_lock:
            with self._microphone as source:
                self._recognizer.adjust_for_ambient_noise(source, duration=duration)

    def listen_once(
        self, timeout: float | None = 5.0, phrase_time_limit: float | None = 8.0
    ) -> RecognizedSpeech | None:
        """Capture one phrase and return the first successful transcription
        across `self.languages`, or None if nothing was captured/recognized."""
        if not self.available:
            return None

        with self._listen_lock:
            with self._microphone as source:
                try:
                    audio = self._recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
                except self._sr.WaitTimeoutError:
                    return None

        return self.recognize(audio)

    def recognize(self, audio) -> RecognizedSpeech | None:
        if not self.available:
            return None
        if self.provider == "openai":
            result = recognize_with_openai(audio, model=self.openai_model, lang=self.conversation_language)
            if result is not None or not self.fallback_to_google:
                return result
        return recognize_with_fallback(audio, self._recognizer, self._sr, self.languages)
