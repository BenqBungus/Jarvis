from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


SETTINGS_PATH = Path("data/settings.json")


@dataclass
class JarvisSettings:
    preferred_browser: str = ""
    browser_paths: dict[str, str] = field(default_factory=dict)
    website_aliases: dict[str, str] = field(default_factory=dict)
    app_aliases: dict[str, str] = field(default_factory=dict)
    openai: dict[str, Any] = field(default_factory=dict)
    mode_preferences: dict[str, Any] = field(default_factory=dict)
    gaming: dict[str, Any] = field(default_factory=dict)
    safety: dict[str, bool] = field(default_factory=dict)
    personalization: dict[str, Any] = field(default_factory=dict)

    @property
    def conversation_language(self) -> str:
        value = self.openai.get("conversation_language", "en")
        code = value.strip().lower() if isinstance(value, str) else "en"
        return code if code in {"en", "bg", "auto"} else "en"

    def response_language_instruction(self) -> str:
        from .personality import persona_instructions
        from .role_packs import pack_instructions
        # With profiles (gui/profile_wiring.py sets profile_provider), the active
        # profile's personality, packs and name; otherwise these settings'.
        provider = getattr(self, "profile_provider", None)
        profile = provider() if callable(provider) else None
        style = profile if isinstance(profile, dict) else self.personalization
        name = profile.get("display_name") if isinstance(profile, dict) else self.personalization.get("address_name")
        language = {
            "en": "Reply only in English. ",
            "bg": "Reply in Bulgarian (bg), using natural Bulgarian and Cyrillic for prose. ",
            "auto": "Reply in the language of the current user request, Bulgarian or English. ",
        }[self.conversation_language]
        return (language + "Understand Bulgarian and English requests, including mixed technical terms. "
                "Do not take the response language from old history, tool output, documents or webpages. "
                "Keep paths, URLs, app names, code, citations, tool identifiers, JSON keys and enum values unchanged. "
                "Localize explanations and clarification questions, not the tool protocol. "
                + persona_instructions(style.get("personality"), str(name or ""))
                + " " + pack_instructions(style.get("role_packs"))
                + " These style preferences do not expand this request's capabilities or evidence. "
                "Use named tools only when they are actually provided; otherwise explain the limitation. "
                "Task-specific output schemas, read-only boundaries and safety requirements take precedence.")

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "JarvisSettings":
        if not path.exists():
            return cls()
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        return cls(
            preferred_browser=data.get("preferred_browser", ""),
            browser_paths={str(k).lower(): str(v) for k, v in data.get("browser_paths", {}).items()},
            website_aliases={str(k).lower(): str(v) for k, v in data.get("website_aliases", {}).items()},
            app_aliases={str(k).lower(): str(v) for k, v in data.get("app_aliases", {}).items()},
            openai=data.get("openai", {}),
            mode_preferences=data.get("mode_preferences", {}),
            gaming=data.get("gaming", {}),
            safety={str(k): (v is True if k == "full_access_local" else bool(v)) for k, v in data.get("safety", {}).items()},
            personalization={str(k): v for k, v in data.get("personalization", {}).items()},
        )

    def safety_enabled(self, key: str, default: bool = True) -> bool:
        return self.safety.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, path: Path = SETTINGS_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def set_user_preference(self, key: str, value: Any) -> tuple[str, Any]:
        normalized_key = _normalize_preference_key(key)
        if normalized_key == "preferred_browser":
            self.preferred_browser = _normalize_browser_name(str(value))
            return normalized_key, self.preferred_browser
        if normalized_key == "preferred_volume":
            percent = max(0, min(100, int(value)))
            self.mode_preferences["preferred_volume"] = percent
            return normalized_key, percent
        if normalized_key == "address_name":
            cleaned = str(value).strip()
            self.personalization["address_name"] = cleaned
            return normalized_key, cleaned
        raise ValueError(f"Unsupported user preference: {key}")

    def user_preference_summary(self) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        if self.preferred_browser:
            summary["preferred_browser"] = self.preferred_browser
        if "preferred_volume" in self.mode_preferences:
            summary["preferred_volume"] = self.mode_preferences["preferred_volume"]
        if self.personalization.get("address_name"):
            summary["address_name"] = self.personalization["address_name"]
        return summary


def _normalize_preference_key(key: str) -> str:
    cleaned = key.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "browser": "preferred_browser",
        "preferred_browser": "preferred_browser",
        "любим_браузър": "preferred_browser",
        "предпочитан_браузър": "preferred_browser",
        "volume": "preferred_volume",
        "preferred_volume": "preferred_volume",
        "звук": "preferred_volume",
        "име": "address_name",
        "name": "address_name",
        "address_name": "address_name",
        "nickname": "address_name",
        "наричай_ме": "address_name",
    }
    return aliases.get(cleaned, cleaned)


def _normalize_browser_name(value: str) -> str:
    cleaned = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "opera_gx": "opera_gx",
        "operagx": "opera_gx",
        "opera": "opera_gx",
        "chrome": "chrome",
        "google_chrome": "chrome",
        "edge": "edge",
        "microsoft_edge": "edge",
        "firefox": "firefox",
    }
    return aliases.get(cleaned, cleaned)
