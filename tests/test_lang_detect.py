from __future__ import annotations

from jarvis.lang_detect import detect_language


def test_detects_bulgarian_from_cyrillic_text():
    assert detect_language("Здравей, отвори Фейсбук") == "bg"


def test_detects_english_from_latin_text():
    assert detect_language("open facebook please") == "en"


def test_empty_text_defaults_to_english():
    assert detect_language("") == "en"


def test_any_cyrillic_presence_is_enough_to_flag_bulgarian():
    assert detect_language("jarvis отвори facebook") == "bg"
    assert detect_language("Джарвис open the app") == "bg"
