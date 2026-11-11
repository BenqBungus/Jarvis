"""Personality presets (src/jarvis/personality.py) and how they reach the
Live-voice session."""
from __future__ import annotations

from jarvis.audio.language import greeting_for
from jarvis.personality import (
    DEFAULT_PRESET,
    DETAIL_LEVELS,
    HUMOR_LEVELS,
    PRESETS,
    SAFETY_RULE,
    normalize,
    persona_instructions,
    sample_line,
)
from jarvis.realtime import RealtimeVoiceConfig
from jarvis.user_settings import JarvisSettings


def test_normalize_repairs_whatever_was_stored():
    assert normalize(None) == {"preset": DEFAULT_PRESET, "humor": 1, "detail": 1, "address_as": ""}
    assert normalize({"preset": "pirate", "humor": 99, "detail": -4, "address_as": "  Берк  "}) == {
        "preset": DEFAULT_PRESET, "humor": len(HUMOR_LEVELS) - 1, "detail": 0, "address_as": "Берк"}
    assert normalize({"humor": True})["humor"] == 1  # a bool is not a level


def test_every_preset_keeps_the_safety_rule_and_stays_language_neutral():
    for preset_id in PRESETS:
        for humor in range(len(HUMOR_LEVELS)):
            for detail in range(len(DETAIL_LEVELS)):
                text = persona_instructions({"preset": preset_id, "humor": humor, "detail": detail})
                assert PRESETS[preset_id].instructions in text
                assert text.endswith(SAFETY_RULE)
                # The language policy is added separately; naming one here would fight it.
                for word in ("English", "Bulgarian", "Български", "английски"):
                    assert word not in text


def test_how_jarvis_addresses_the_person():
    assert "“Сър”" in persona_instructions({"address_as": "Сър"}, address_name="Берк")
    assert "“Берк”" in persona_instructions({}, address_name="Берк")
    assert "when you know it" in persona_instructions({})


def test_every_preset_has_a_preview_line_in_both_languages():
    for preset_id, preset in PRESETS.items():
        assert preset.samples["en"] and preset.samples["bg"]
        assert sample_line({"preset": preset_id}, "bg") == preset.samples["bg"]
        assert sample_line({"preset": preset_id}, "auto") == preset.samples["en"]


def test_live_session_uses_the_saved_personality_and_name():
    settings = JarvisSettings(personalization={"personality": {"preset": "coach", "humor": 0},
                                               "address_name": "мария"},
                              openai={"conversation_language": "bg"})
    config = RealtimeVoiceConfig.from_settings(settings)
    assert PRESETS["coach"].instructions in config.instructions
    assert PRESETS["jarvis"].instructions not in config.instructions
    assert "Use no humor." in config.instructions
    assert config.greeting == "Здравей, Мария. Как мога да помогна?"
    assert "English" not in config.session_update_event()["session"]["instructions"]


def test_a_profile_wins_over_settings_and_custom_instructions_win_over_both():
    settings = JarvisSettings(personalization={"personality": {"preset": "coach"}})
    profile = {"display_name": "Ани", "language": "en", "personality": {"preset": "tutor"},
               "role_packs": ["student"], "voice": {"live_voice": "marin"}}
    config = RealtimeVoiceConfig.from_settings(settings, profile=profile)
    assert PRESETS["tutor"].instructions in config.instructions
    assert "Studying:" in config.instructions and "Gaming:" not in config.instructions
    assert config.voice == "marin" and config.greeting == greeting_for("en", "Ани")
    custom = JarvisSettings(openai={"realtime_instructions": "Talk naturally."})
    assert RealtimeVoiceConfig.from_settings(custom, profile=profile).instructions == "Talk naturally."
