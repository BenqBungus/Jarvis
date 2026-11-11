from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from .config import WAKE_WORDS

_DEFAULT_FUZZY_THRESHOLD = 0.8
_MAX_WAKE_WORD_SPAN = max(len(w.split()) for w in WAKE_WORDS)


@dataclass(frozen=True)
class WakeWordMatch:
    wake_word: str
    remainder: str
    score: float


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def match_wake_word(text: str, fuzzy_threshold: float = _DEFAULT_FUZZY_THRESHOLD) -> WakeWordMatch | None:
    """Return the matched wake word and remaining command text, or None.

    Tries an exact prefix match first, then falls back to fuzzy-matching the
    leading word(s) against known wake words so minor speech-to-text errors
    ("jarviss", "джарви") still trigger. Longer wake phrases are checked
    before shorter ones so "hey jarvis" wins over a bare "jarvis" match.
    """
    normalized = _normalize(text)
    if not normalized:
        return None

    for wake_word in sorted(WAKE_WORDS, key=len, reverse=True):
        if normalized == wake_word or normalized.startswith(wake_word + " "):
            remainder = normalized[len(wake_word) :].strip(" ,.!?")
            return WakeWordMatch(wake_word, remainder, 1.0)

    words = normalized.split()
    for span in range(min(_MAX_WAKE_WORD_SPAN, len(words)), 0, -1):
        candidate = " ".join(words[:span])
        best: WakeWordMatch | None = None
        for wake_word in WAKE_WORDS:
            score = SequenceMatcher(None, candidate, wake_word).ratio()
            if score >= fuzzy_threshold and (best is None or score > best.score):
                remainder = " ".join(words[span:]).strip(" ,.!?")
                best = WakeWordMatch(wake_word, remainder, score)
        if best is not None:
            return best

    return None


def contains_wake_word(text: str) -> bool:
    return match_wake_word(text) is not None
