from __future__ import annotations

import json
from pathlib import Path

from ..user_settings import SETTINGS_PATH, JarvisSettings

OPENAI_MODEL_KEY = "openai_model"


def save_settings(settings: JarvisSettings, extra: dict | None = None, path: Path = SETTINGS_PATH) -> None:
    """Write settings back to the same JSON shape JarvisSettings.load() reads.

    Uses dataclasses.asdict so a future field added to JarvisSettings is
    picked up automatically instead of silently dropped by a hand-written
    key list. `extra` merges in ad hoc keys JarvisSettings does not model
    yet (e.g. openai_model) -- JarvisSettings.load() already ignores unknown
    top-level keys via its explicit per-field .get() extraction.
    """
    data = settings.to_dict()
    if extra:
        openai_model = extra.get(OPENAI_MODEL_KEY)
        if openai_model:
            data.setdefault("openai", {})["model"] = openai_model
        data.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_raw(path: Path = SETTINGS_PATH) -> dict:
    """Read the settings file as a plain dict, for ad hoc keys JarvisSettings
    does not model (e.g. openai_model) without duplicating its parsing."""
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_openai_model(path: Path = SETTINGS_PATH) -> str | None:
    data = load_raw(path)
    openai = data.get("openai", {})
    value = openai.get("model") if isinstance(openai, dict) else None
    value = value or data.get(OPENAI_MODEL_KEY)
    return str(value) if value else None
