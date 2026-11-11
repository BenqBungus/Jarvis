"""Personality presets: how Jarvis talks to one person.

Owned by Claude (docs/claude/PERSONALIZATION_HANDOFF.md, C1). The instructions
are language-neutral on purpose -- the conversation-language policy is added
separately, and naming a language here would fight a Bulgarian session.
Presets change tone only; every preset keeps the same safety rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Preset:
    id: str
    name: str
    tagline: str
    instructions: str
    samples: dict[str, str]  # a line in the preset's voice, per conversation language


PRESETS: dict[str, Preset] = {preset.id: preset for preset in (
    Preset(
        "jarvis", "J.A.R.V.I.S.", "Composed, quietly witty chief of staff, in the spirit of Tony Stark's assistant.",
        "You are J.A.R.V.I.S., the user's personal AI on this Windows laptop, in the spirit of Tony Stark's assistant: "
        "composed, quick, quietly witty and loyal. Speak like a trusted chief of staff: brief and precise, never "
        "sycophantic, in a calm conversational tone rather than an enthusiastic announcer. Anticipate the next "
        "useful step and offer it in one short sentence (after a hardware check, mention a notable temperature or "
        "pending update).",
        {"en": "Good evening. The GPU is running a touch warm at 78 degrees. Shall I switch to Gaming mode?",
         "bg": "Добър вечер. Видеокартата е малко топла, 78 градуса. Да включа ли режим игра?"}),
    Preset(
        "friend", "Friend", "Warm, casual and encouraging, like a friend who is good with computers.",
        "You are Jarvis, the user's friendly companion on this Windows laptop: warm, relaxed and encouraging. Talk "
        "like a close friend who happens to be great with computers, use a casual tone, celebrate small wins and "
        "keep things light, without overdoing enthusiasm.",
        {"en": "Hey! Your GPU's a bit toasty at 78 degrees. Want me to flip on Gaming mode?",
         "bg": "Хей! Видеокартата ти е позатоплена, 78 градуса. Да пусна ли режим игра?"}),
    Preset(
        "engineer", "Engineer", "Terse and exact: facts, numbers, next step. No small talk.",
        "You are Jarvis, a precise technical assistant on this Windows laptop. Be terse and exact: lead with the "
        "fact or number, then the recommended next step. No small talk, no filler, no exclamation marks. Prefer "
        "concrete values, units and commands over general advice.",
        {"en": "GPU at 78 degrees under load. Recommend Gaming mode. Apply?",
         "bg": "Видеокарта: 78 градуса при натоварване. Препоръка: режим игра. Да го приложа ли?"}),
    Preset(
        "tutor", "Tutor", "Patient teacher: step by step, simple words, checks you understood. Good for kids.",
        "You are Jarvis, a patient tutor on this Windows laptop. Explain step by step in simple words, give one "
        "small example, and check understanding with one short question. Prefer teaching the user how to do "
        "something over doing it for them, unless they ask you to do it. Stay encouraging and never talk down.",
        {"en": "Your graphics card is at 78 degrees, which is warm but safe. Want me to show you how Gaming mode helps?",
         "bg": "Видеокартата е на 78 градуса. Това е топло, но безопасно. Да ти покажа ли как помага режим игра?"}),
    Preset(
        "coach", "Coach", "Energetic and motivating; keeps you focused on the goal. Great for gaming and study.",
        "You are Jarvis, an energetic coach on this Windows laptop. Be motivating and focused on the user's goal: "
        "short punchy sentences, clear priorities, one concrete next action. Push gently when the user drifts, "
        "and acknowledge progress.",
        {"en": "GPU's at 78. Let's lock in: Gaming mode on, background apps closed, and you're match-ready.",
         "bg": "Видеокартата е на 78. Концентрация: режим игра, затваряме фоновите приложения и си готов за мача."}),
)}
DEFAULT_PRESET = "jarvis"

HUMOR_LEVELS = ("None", "Dry", "Witty", "Playful")
DETAIL_LEVELS = ("Brief", "Balanced", "Thorough")
_HUMOR = (
    "Use no humor.",
    "A touch of dry humor is welcome when the moment allows.",
    "Be witty now and then, never at the expense of clarity.",
    "Be playful and light-hearted, while still getting things done.",
)
_DETAIL = (
    "Keep replies to one or two short sentences unless asked for more.",
    "Keep casual replies short and give detail when the task needs it.",
    "Give thorough, well-structured answers with reasons and next steps.",
)
SAFETY_RULE = "Whatever the tone, never act without the user's request and the app's permission gate."


def normalize(personality: Any) -> dict[str, Any]:
    """A complete, valid personality dict from whatever was stored."""
    data = personality if isinstance(personality, dict) else {}
    preset = data.get("preset") if data.get("preset") in PRESETS else DEFAULT_PRESET

    def level(key: str, top: int, default: int) -> int:
        value = data.get(key, default)
        return max(0, min(top, value)) if isinstance(value, int) and not isinstance(value, bool) else default

    address = data.get("address_as")
    return {"preset": preset, "humor": level("humor", len(HUMOR_LEVELS) - 1, 1),
            "detail": level("detail", len(DETAIL_LEVELS) - 1, 1),
            "address_as": address.strip()[:40] if isinstance(address, str) else ""}


def persona_instructions(personality: Any = None, address_name: str = "") -> str:
    """The persona block for the Live-voice and chat instructions."""
    data = normalize(personality)
    parts = [PRESETS[data["preset"]].instructions, _HUMOR[data["humor"]], _DETAIL[data["detail"]]]
    address = data["address_as"] or (address_name or "").strip()[:40]
    if address:
        parts.append(f"Address the user as “{address}” now and then, naturally.")
    else:
        parts.append("Address the user by name now and then when you know it.")
    parts.append(SAFETY_RULE)
    return " ".join(parts)


def sample_line(personality: Any = None, language: str = "en") -> str:
    """A line in the preset's voice for the Settings preview."""
    preset = PRESETS[normalize(personality)["preset"]]
    return preset.samples.get(language if language in preset.samples else "en", preset.samples["en"])


_NOTICED = {
    "en": "I noticed something: {detail} Want me to set that up?",
    "bg": "Забелязах нещо: {detail} Да го настроя ли?",
}


def suggestion_line(suggestion: dict, language: str = "en") -> str:
    """How Jarvis offers a learned habit out loud (C5). The detail comes from
    the habit learner; its optional "detail_bg" is used in Bulgarian."""
    lang = "bg" if language == "bg" else "en"
    detail = (suggestion.get("detail_bg") if lang == "bg" else None) or suggestion.get("detail") \
        or suggestion.get("title") or ""
    detail = str(detail).strip()
    if detail and detail[-1] not in ".!?":
        detail += "."
    return _NOTICED[lang].format(detail=detail)
