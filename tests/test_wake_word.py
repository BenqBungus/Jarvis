from __future__ import annotations

import pytest

from jarvis.wake_word import match_wake_word


@pytest.mark.parametrize(
    "utterance,expected_remainder",
    [
        ("hey jarvis open facebook", "open facebook"),
        ("hi jarvis open facebook", "open facebook"),
        ("здравей jarvis отвори facebook", "отвори facebook"),
        ("здравей джарвис отвори фейсбук", "отвори фейсбук"),
        ("джарвис увеличи звука", "увеличи звука"),
        ("jarvis провери nvidia драйверите", "провери nvidia драйверите"),
    ],
)
def test_exact_wake_word_matches_and_strips_cleanly(utterance, expected_remainder):
    match = match_wake_word(utterance)
    assert match is not None
    assert match.remainder == expected_remainder


def test_wake_word_alone_leaves_empty_remainder():
    match = match_wake_word("hey jarvis")
    assert match is not None
    assert match.remainder == ""


def test_exact_match_respects_word_boundary():
    # "jarviss" must NOT exact-match the "jarvis" prefix and leave a
    # stray "s" glued to the remainder; it should fall through to fuzzy
    # matching instead, which strips the whole mis-heard word.
    match = match_wake_word("jarviss open facebook")
    assert match is not None
    assert match.remainder == "open facebook"


@pytest.mark.parametrize(
    "utterance,expected_remainder",
    [
        ("jarviss open facebook", "open facebook"),
        ("джарви отвори фейсбук", "отвори фейсбук"),
        ("здравей джарвиз отвори фейсбук", "отвори фейсбук"),
    ],
)
def test_fuzzy_matches_recover_from_stt_noise(utterance, expected_remainder):
    match = match_wake_word(utterance)
    assert match is not None
    assert match.remainder == expected_remainder


@pytest.mark.parametrize(
    "utterance",
    [
        "what is the weather today",
        "какво е времето днес",
        "call mom",
        "",
        "   ",
    ],
)
def test_no_false_positive_without_wake_word(utterance):
    assert match_wake_word(utterance) is None
