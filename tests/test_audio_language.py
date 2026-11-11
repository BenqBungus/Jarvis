from __future__ import annotations

from jarvis.audio.language import (
    ENGLISH_ONLY_INSTRUCTIONS,
    SPEAKER_TEST,
    STARTUP_GREETING,
    conversation_instructions_for,
    display_name_for,
    greeting_for,
    resolved_spoken_language,
    speaker_test_for,
    transcription_language_options,
)


def test_legacy_constants_are_unchanged_english_values():
    # cli.py and gui/app.py still import these three names directly; their
    # values must stay byte-identical until the integration request lands.
    assert STARTUP_GREETING == "Hello Berk, how can I help you?"
    assert SPEAKER_TEST == "Hello Berk, this is a voice test. If you can hear me, Jarvis voice is working."
    assert "only in English" in ENGLISH_ONLY_INSTRUCTIONS


def test_greeting_for_each_language():
    assert greeting_for("en") == STARTUP_GREETING
    assert greeting_for("bg") == "Здравей, Берк. Как мога да помогна?"
    assert greeting_for("auto") == STARTUP_GREETING  # no prior speech to mirror yet


def test_greeting_for_unknown_code_falls_back_to_english():
    assert greeting_for("fr") == STARTUP_GREETING


def test_speaker_test_for_each_language():
    assert speaker_test_for("en") == SPEAKER_TEST
    assert speaker_test_for("bg") == "Здравей, Берк, това е тест на гласа. Ако ме чуваш, гласът на Jarvis работи."
    assert speaker_test_for("auto") == SPEAKER_TEST


def test_conversation_instructions_for_each_language():
    assert conversation_instructions_for("en") == ENGLISH_ONLY_INSTRUCTIONS
    bg = conversation_instructions_for("bg")
    assert "само на български" in bg
    auto = conversation_instructions_for("auto")
    assert "English or Bulgarian" in auto
    assert bg != ENGLISH_ONLY_INSTRUCTIONS != auto


def test_resolved_spoken_language():
    assert resolved_spoken_language("bg") == "bg"
    assert resolved_spoken_language("en") == "en"
    assert resolved_spoken_language("auto") == "en"
    assert resolved_spoken_language("fr") == "en"


def test_display_name_for():
    assert display_name_for("en") == "English"
    assert display_name_for("bg") == "Bulgarian"
    assert display_name_for("auto") == "Automatic"
    assert display_name_for("fr") == "English"


def test_transcription_language_options_default_is_byte_identical_to_legacy_behavior():
    assert transcription_language_options("gpt-4o-transcribe") == {"language": "en"}
    assert transcription_language_options("gpt-transcribe") == {"languages": ["en"]}


def test_transcription_language_options_for_bulgarian():
    assert transcription_language_options("gpt-4o-transcribe", "bg") == {"language": "bg"}
    assert transcription_language_options("gpt-transcribe", "bg") == {"languages": ["bg"]}
    assert transcription_language_options("gpt-live-transcribe", "bg") == {"languages": ["bg"]}


def test_transcription_language_options_for_auto_omits_the_hint_entirely():
    # The documented way to request auto-detection from Whisper-family
    # models is to omit the language hint, not pass a special value.
    assert transcription_language_options("gpt-4o-transcribe", "auto") == {}
    assert transcription_language_options("gpt-transcribe", "auto") == {}


def test_transcription_language_options_unknown_code_falls_back_to_english():
    assert transcription_language_options("gpt-4o-transcribe", "fr") == {"language": "en"}
