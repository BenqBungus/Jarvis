from __future__ import annotations

import re

_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")


def detect_language(text: str) -> str:
    """Return 'bg' if text contains Cyrillic characters, else 'en'.

    English text essentially never contains Cyrillic, so presence alone is a
    safe, low-noise signal -- no need for character-ratio heuristics.
    """
    if text and _CYRILLIC_RE.search(text):
        return "bg"
    return "en"
