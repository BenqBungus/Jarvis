"""Role packs (src/jarvis/role_packs.py): selection rules, guidance and the
quick actions the HUD shows."""
from __future__ import annotations

from jarvis.gui.main_window import MainWindow
from jarvis.realtime import RealtimeVoiceConfig
from jarvis.role_packs import DEFAULT_PACKS, PACKS, normalize_packs, pack_instructions
from jarvis.user_settings import JarvisSettings


def test_never_chosen_means_default_packs_but_an_empty_choice_is_respected():
    assert normalize_packs(None) == list(DEFAULT_PACKS)
    assert normalize_packs([]) == []
    assert normalize_packs(["business", "nope", 3, "gamer"]) == ["gamer", "business"]  # PACKS order
    assert normalize_packs("gamer") == []


def test_only_chosen_packs_add_guidance():
    text = pack_instructions(["student"])
    assert "Studying:" in text and "Gaming:" not in text
    assert pack_instructions([]) == ""
    settings = JarvisSettings(personalization={"role_packs": []})
    assert "Gaming:" not in RealtimeVoiceConfig.from_settings(settings).instructions
    assert "Gaming:" in RealtimeVoiceConfig.from_settings(JarvisSettings()).instructions


def test_quick_actions_are_real_commands_or_real_window_signals():
    for pack in PACKS.values():
        assert pack.quick_actions, pack.id
        for action in pack.quick_actions:
            assert bool(action.command) != bool(action.signal), (pack.id, action.label)
            if action.signal:
                assert hasattr(MainWindow, action.signal), (pack.id, action.signal)
