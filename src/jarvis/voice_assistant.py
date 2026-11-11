from __future__ import annotations

import time
from typing import Callable

from .audio.speech_to_text import RecognizedSpeech, SpeechToText
from .audio.text_to_speech import TextToSpeech
from .lang_detect import detect_language
from .models import CommandResult
from .router import CommandRouter
from .wake_word import match_wake_word

# Mirrors the destructive-action keywords in router.py's confirmation checks.
# Duplicated (not imported) because router.py only exposes them inline; this
# lets us warn the user *before* CommandRouter blocks on a confirmation
# prompt, which would otherwise happen silently mid-speech.
_DESTRUCTIVE_HINTS = (
    "restart",
    "рестартирай",
    "shutdown",
    "изключи лаптопа",
    "изключи компютъра",
    "sleep",
    "приспи",
    "заспи",
)

_PROMPTS = {
    "bg": {
        "listening": "Да?",
        "confirm": "Това изисква потвърждение. Провери терминала.",
        "no_speech": "Не чух нищо.",
    },
    "en": {
        "listening": "Yes?",
        "confirm": "This needs confirmation. Check the terminal.",
        "no_speech": "I did not hear anything.",
    },
}

_DEFAULT_CONFIRM_PROMPTS = {lang: prompts["confirm"] for lang, prompts in _PROMPTS.items()}

_STOP_SESSION_PHRASES = (
    "stop listening",
    "stop session",
    "that's all",
    "thanks jarvis",
    "thank you jarvis",
    "спри да слушаш",
    "край джарвис",
    "край jarvis",
    "благодаря jarvis",
    "мерси jarvis",
)

# Checked before dispatch (in dispatch_command, so it covers both the normal
# wake-word flow and push-to-talk): says "OK, cancelled" instead of sending
# these straight to the router, where they'd otherwise land as an opaque
# "I do not know that command yet."
_CANCELLATION_PHRASES = (
    "cancel",
    "never mind",
    "nevermind",
    "forget it",
    "отказ",
    "отказвам",
    "забрави",
    "забрави го",
)

_CANCEL_MESSAGES = {
    "bg": "Добре, отказано.",
    "en": "OK, cancelled.",
}

_STOP_SESSION_MESSAGES = {
    "bg": "Добре, спирам да слушам.",
    "en": "OK, I will stop listening.",
}

# A transcription this short after the wake word is almost always noise or a
# clipped mis-hear, not a real command -- treated the same as "heard
# nothing" rather than sent to the router as an unknown command.
_UNCLEAR_MAX_LENGTH = 2

_UNCLEAR_MESSAGES = {
    "bg": "Не те чух добре. Опитай пак.",
    "en": "I did not hear that clearly. Please try again.",
}

_THINKING_MESSAGES = {
    "bg": "Нека помисля.",
    "en": "Let me think.",
}

_THINKING_HINTS = (
    "защо",
    "обясни",
    "обясниш",
    "сравни",
    "проучи",
    "потърси информация",
    "кажи ми",
    "каква е причината",
    "какви са причините",
    "which",
    "why",
    "explain",
    "compare",
    "research",
    "look up",
    "tell me",
)

_CASUAL_NO_THINKING = (
    "как си",
    "как си?",
    "how are you",
    "what's up",
    "здравей",
    "hello",
    "hi",
)


def looks_destructive(command_text: str) -> bool:
    """Shared with the GUI's push-to-talk path, so both announce an
    upcoming confirmation prompt the same way."""
    lowered = command_text.lower()
    return any(hint in lowered for hint in _DESTRUCTIVE_HINTS)


def _is_cancellation(command_text: str) -> bool:
    lowered = " ".join(command_text.strip().lower().split())
    return any(phrase in lowered for phrase in _CANCELLATION_PHRASES)


def _looks_unclear(command_text: str) -> bool:
    return 0 < len(command_text.strip()) < _UNCLEAR_MAX_LENGTH


def _should_speak_thinking(command_text: str) -> bool:
    lowered = " ".join(command_text.strip().lower().split())
    if not lowered:
        return False
    if any(phrase == lowered or lowered.startswith(f"{phrase} ") for phrase in _CASUAL_NO_THINKING):
        return False
    return any(hint in lowered for hint in _THINKING_HINTS)


class VoiceAssistant:
    """Ties speech input, the wake-word gate, the command router, and speech
    output together. UI-agnostic: only talks to the stt/tts/dispatch objects
    it is given, so it works the same from a terminal loop or a GUI thread.
    """

    def __init__(
        self,
        router: CommandRouter,
        stt: SpeechToText,
        tts: TextToSpeech,
        dispatch: Callable[[str], CommandResult] | None = None,
        confirm_prompts: dict[str, str] | None = None,
        active_session_seconds: float = 20.0,
        on_unclear: Callable[[], None] | None = None,
        listen_once: Callable[..., RecognizedSpeech | None] | None = None,
        spoken_language: str | None = None,
    ) -> None:
        self.router = router
        self.stt = stt
        self.tts = tts
        # "auto" means "no fixed language -- detect per utterance," same as
        # leaving spoken_language unset. Normalized once here so every
        # `self._spoken_language or detect_language(...)` call below needs
        # no change.
        self._spoken_language = None if spoken_language == "auto" else spoken_language
        # The language of the last command, for prompts spoken when nothing
        # was heard at all (auto-detect has no text to detect from then).
        self._last_language: str | None = None
        self._listen_once = listen_once or self.stt.listen_once
        # Fires when speech was captured but was empty/too short to be a
        # real command -- lets a GUI show a distinct "didn't catch that"
        # mic state instead of just going quiet. Optional: the terminal
        # voice loop has no equivalent visual to update.
        self._on_unclear = on_unclear
        # dispatch defaults to calling the router directly (original
        # behavior); the GUI passes CommandExecutor.submit_blocking instead,
        # so every entry point (text/voice/button) still funnels through one
        # serialization point and one GuiSafetyPolicy instance.
        self._dispatch = dispatch or self.router.handle
        # confirm_prompts overrides only the "this needs confirmation..."
        # message per language -- "Check the terminal" is wrong in a GUI
        # process, which may have no terminal at all.
        self._confirm_prompts = confirm_prompts or dict(_DEFAULT_CONFIRM_PROMPTS)
        self._active_session_seconds = max(0.0, active_session_seconds)
        self._active_session_until = 0.0

    def set_conversation_language(self, code: str) -> None:
        """Apply a new conversation language to this already-constructed
        instance -- lets a settings save take effect on the next utterance
        without restarting the classic voice loop. Same "auto" normalization
        as __init__'s spoken_language handling."""
        self._spoken_language = None if code == "auto" else code

    def run_forever(self, on_transcript=None, max_iterations: int | None = None) -> None:
        if not self.stt.available:
            raise RuntimeError(
                "Speech input is not available. Install extras with: pip install -e .[voice]"
            )

        self.stt.calibrate()
        print(
            "Jarvis is listening. Say 'hey jarvis' or 'здравей jarvis' followed by a command. "
            "After Jarvis answers, short follow-up replies are accepted for a few seconds."
        )

        iterations = 0
        while max_iterations is None or iterations < max_iterations:
            iterations += 1
            try:
                heard = self._listen_once()
            except KeyboardInterrupt:
                print("\nGoodbye.")
                return

            if heard is None:
                continue

            if on_transcript:
                on_transcript(heard)

            self.handle_utterance(heard.text)

    def handle_utterance(self, text: str) -> CommandResult | None:
        """Process one recognized utterance. Ignores it silently (returns
        None) if it does not start with a wake word, so ambient conversation
        is never treated as a command. Returns the dispatched CommandResult
        otherwise, or None if no command was ever obtained."""
        match = match_wake_word(text)
        if match is None:
            if not self._session_active():
                return None
            lang = self._spoken_language or detect_language(text)
            if self._is_stop_session_request(text):
                self.end_session()
                self._speak(_STOP_SESSION_MESSAGES.get(lang, _STOP_SESSION_MESSAGES["en"]), lang)
                return CommandResult(True, "Voice session ended.")
            return self.dispatch_command(text, lang)

        command_text = match.remainder
        lang = self._spoken_language or detect_language(text)

        if not command_text:
            self._speak(_PROMPTS[lang]["listening"], lang)
            heard = self._listen_once()
            if heard is None:
                self._speak(_PROMPTS[lang]["no_speech"], lang)
                self._notify_unclear()
                return None
            command_text = heard.text
            lang = self._spoken_language or detect_language(command_text)
            if _looks_unclear(command_text):
                self._speak(_UNCLEAR_MESSAGES[lang], lang)
                self._notify_unclear()
                return None

        if self._is_stop_session_request(command_text):
            self.end_session()
            self._speak(_STOP_SESSION_MESSAGES.get(lang, _STOP_SESSION_MESSAGES["en"]), lang)
            return CommandResult(True, "Voice session ended.")

        return self.dispatch_command(command_text, lang)

    def dispatch_command(self, command_text: str, lang: str | None = None) -> CommandResult:
        """Announce-if-destructive, dispatch, and speak the result. This is
        the part of handle_utterance() that runs after the wake-word gate;
        exposed separately so push-to-talk can reuse the exact same
        confirmation/dispatch/speak behavior while skipping the wake-word
        check entirely -- a manual trigger is itself the deliberate-
        activation signal, the same reasoning as why typed commands don't
        need a wake word either.
        """
        lang = self._spoken_language or lang or detect_language(command_text)
        self._last_language = lang
        print(f"> {command_text}")

        wake_match = match_wake_word(command_text)
        if wake_match is not None:
            if not wake_match.remainder:
                self._speak(_PROMPTS[lang]["listening"], lang)
                self._refresh_session()
                return CommandResult(True, "Jarvis is listening.")
            command_text = wake_match.remainder
            lang = self._spoken_language or detect_language(command_text)

        if self._is_stop_session_request(command_text):
            self.end_session()
            self._speak(_STOP_SESSION_MESSAGES.get(lang, _STOP_SESSION_MESSAGES["en"]), lang)
            return CommandResult(True, "Voice session ended.")

        if _is_cancellation(command_text):
            self._speak(_CANCEL_MESSAGES.get(lang, _CANCEL_MESSAGES["en"]), lang)
            return CommandResult(True, "Command cancelled by user.")

        if looks_destructive(command_text):
            prompt = self._confirm_prompts.get(lang, self._confirm_prompts.get("en"))
            if prompt:
                self._speak(prompt, lang)
        elif _should_speak_thinking(command_text):
            self._speak(_THINKING_MESSAGES.get(lang, _THINKING_MESSAGES["en"]), lang)

        result = self._dispatch(command_text)
        print(result.message)
        self._speak(result.message, lang)
        if result.ok:
            self._refresh_session()
        return result

    def _speak(self, text: str, lang: str | None = None) -> None:
        if self.tts.enabled:
            self.tts.speak(text, lang=lang)

    def speak_no_speech(self) -> None:
        """Say "I did not hear anything" for push-to-talk and conversation
        loops: in the fixed conversation language, else the language of the
        last command, else English (the historical default)."""
        lang = self._spoken_language or self._last_language or "en"
        prompts = _PROMPTS.get(lang, _PROMPTS["en"])
        self._speak(prompts["no_speech"], lang if lang in _PROMPTS else "en")

    def _notify_unclear(self) -> None:
        if self._on_unclear is not None:
            self._on_unclear()

    def session_active(self) -> bool:
        """Public read of the active-session state, for a GUI indicator to
        poll. Safe to call from any thread with no lock: CPython's GIL makes
        a single float read atomic, and time.monotonic() is monotonic by
        definition, so there is nothing to tear here."""
        return self._session_active()

    def end_session(self) -> None:
        self._active_session_until = 0.0

    def start_session(self) -> None:
        self._refresh_session()

    def _refresh_session(self) -> None:
        if self._active_session_seconds <= 0:
            return
        self._active_session_until = time.monotonic() + self._active_session_seconds

    def _session_active(self) -> bool:
        return self._active_session_seconds > 0 and time.monotonic() < self._active_session_until

    @staticmethod
    def _is_stop_session_request(text: str) -> bool:
        lowered = " ".join(text.strip().lower().split())
        return any(phrase in lowered for phrase in _STOP_SESSION_PHRASES)
