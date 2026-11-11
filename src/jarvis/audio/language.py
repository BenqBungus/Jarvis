"""Conversation-language profiles shared by the voice entry points.

Three codes are used throughout: "en" (English), "bg" (Bulgarian), and
"auto" (mirror whichever language the user is currently using). These are
bare codes, deliberately distinct from the BCP-47-ish locale codes
(en-US/bg-BG) needed at the narrow boundary where Google's speech
recognition API requires them -- see speech_to_text.py.
"""

_GREETINGS = {
    "en": "Hello Berk, how can I help you?",
    "bg": "Здравей, Берк. Как мога да помогна?",
}

_SPEAKER_TESTS = {
    "en": "Hello Berk, this is a voice test. If you can hear me, Jarvis voice is working.",
    "bg": "Здравей, Берк, това е тест на гласа. Ако ме чуваш, гласът на Jarvis работи.",
}

_CONVERSATION_INSTRUCTIONS = {
    "en": (
        "Speak and reply only in English. Do not switch languages based on previous conversation, "
        "transcripts, or tool results. If the user speaks another language or the audio is unclear, "
        "briefly ask them in English to repeat in English. Keep app names, URLs, and filenames unchanged. "
    ),
    "bg": (
        "Говори и отговаряй само на български. Не сменяй езика въз основа на предишен разговор, "
        "преписи или резултати от инструменти. Ако потребителят говори на друг език или звукът е неясен, "
        "помоли го накратко на български да повтори на български. Пази имената на приложения, "
        "URL адресите и имената на файловете непроменени. "
    ),
    # Written in English, like the rest of the base instructions this gets
    # spliced into -- unlike "bg" above, there is no single target output
    # language here to reinforce by matching the instruction's own language.
    "auto": (
        "Speak and reply in whichever language the user is speaking, English or Bulgarian, and follow "
        "them if they switch languages mid-conversation -- judge the current turn, not just past "
        "history. If the audio is unclear, briefly ask them to repeat, in the language they were most "
        "recently using. Keep app names, URLs, and filenames unchanged. "
    ),
}

# Unchanged values, kept as plain constants so existing direct importers
# (cli.py, gui/app.py) keep working until they switch to the functions below.
STARTUP_GREETING = _GREETINGS["en"]
SPEAKER_TEST = _SPEAKER_TESTS["en"]
ENGLISH_ONLY_INSTRUCTIONS = _CONVERSATION_INSTRUCTIONS["en"]

_DISPLAY_NAMES = {"en": "English", "bg": "Bulgarian", "auto": "Automatic"}


def greeting_for(lang: str, name: str | None = None) -> str:
    """The Live-call greeting; `name` is the person's own name when a
    profile or "call me ..." preference supplies one (default: Berk)."""
    greeting = _GREETINGS.get(lang, _GREETINGS["en"])
    if name and name.strip():
        name = name.strip()
        name = name[:1].upper() + name[1:]  # "наричай ме берк" stores it as spoken
        greeting = greeting.replace("Berk", name).replace("Берк", name)
    return greeting


def speaker_test_for(lang: str) -> str:
    return _SPEAKER_TESTS.get(lang, _SPEAKER_TESTS["en"])


def conversation_instructions_for(lang: str) -> str:
    return _CONVERSATION_INSTRUCTIONS.get(lang, _CONVERSATION_INSTRUCTIONS["en"])


def resolved_spoken_language(lang: str) -> str:
    """Collapse to the two real spoken languages -- for pairing with
    TextToSpeech.speak(text, lang) when the text came from greeting_for()/
    speaker_test_for(), which never return mixed-language text."""
    return "bg" if lang == "bg" else "en"


def display_name_for(lang: str) -> str:
    return _DISPLAY_NAMES.get(lang, "English")


def transcription_language_options(model: str, lang: str = "en") -> dict:
    """OpenAI transcription request options for the given conversation
    language. "auto" omits the language hint entirely, which is the
    documented way to request auto-detection from Whisper-family models."""
    if lang == "auto":
        return {}
    code = "bg" if lang == "bg" else "en"
    # New transcription models accept plural hints; legacy models use language.
    if model.startswith(("gpt-transcribe", "gpt-live-transcribe")):
        return {"languages": [code]}
    return {"language": code}
