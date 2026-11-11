from __future__ import annotations

import json

from jarvis.ai_client import JarvisAI
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.tool_registry import ToolCall, build_core_tool_registry
from jarvis.user_settings import JarvisSettings
from jarvis.windows_actions import WindowsActions


def test_settings_save_and_load_personalization(tmp_path):
    path = tmp_path / "settings.json"
    settings = JarvisSettings()

    settings.set_user_preference("preferred_browser", "Opera GX")
    settings.set_user_preference("preferred_volume", 32)
    settings.set_user_preference("address_name", "Berk")
    settings.save(path)

    loaded = JarvisSettings.load(path)

    assert loaded.preferred_browser == "opera_gx"
    assert loaded.mode_preferences["preferred_volume"] == 32
    assert loaded.personalization["address_name"] == "Berk"
    assert json.loads(path.read_text(encoding="utf-8"))["personalization"]["address_name"] == "Berk"


def test_router_can_save_and_show_user_preferences(tmp_path):
    settings = JarvisSettings()
    router = CommandRouter(
        actions=WindowsActions(dry_run=True, settings=settings),
        safety=SafetyPolicy(auto_confirm=True),
        ai=JarvisAI(dry_run=True),
        settings=settings,
        settings_path=tmp_path / "settings.json",
    )

    named = router.handle("jarvis наричай ме берк")
    browser = router.handle("jarvis любимият ми браузър е opera gx")
    volume = router.handle("jarvis предпочитан звук 30")
    shown = router.handle("jarvis покажи предпочитания")

    assert named.ok
    assert browser.ok
    assert volume.ok
    assert settings.personalization["address_name"] == "берк"
    assert settings.preferred_browser == "opera_gx"
    assert settings.mode_preferences["preferred_volume"] == 30
    assert shown.intent == "settings.show_preferences"
    assert shown.metadata["preferences"]["preferred_browser"] == "opera_gx"


def test_router_can_apply_saved_preferred_volume(tmp_path):
    settings = JarvisSettings(mode_preferences={"preferred_volume": 37})
    router = CommandRouter(
        actions=WindowsActions(dry_run=True, settings=settings),
        safety=SafetyPolicy(auto_confirm=True),
        ai=JarvisAI(dry_run=True),
        settings=settings,
        settings_path=tmp_path / "settings.json",
    )

    result = router.handle("jarvis сложи предпочитания звук")

    assert result.ok
    assert result.intent == "system.volume_set_preferred"
    assert "37%" in result.message
    assert result.metadata["preferred_volume"] == 37


def test_router_reports_missing_preferred_volume(tmp_path):
    settings = JarvisSettings()
    router = CommandRouter(
        actions=WindowsActions(dry_run=True, settings=settings),
        safety=SafetyPolicy(auto_confirm=True),
        ai=JarvisAI(dry_run=True),
        settings=settings,
        settings_path=tmp_path / "settings.json",
    )

    result = router.handle("jarvis сложи предпочитания звук")

    assert not result.ok
    assert "not saved" in result.message


def test_tool_registry_exposes_user_preference_tools(tmp_path):
    settings = JarvisSettings()
    registry = build_core_tool_registry(
        WindowsActions(dry_run=True, settings=settings),
        settings=settings,
        settings_path=tmp_path / "settings.json",
    )

    saved = registry.execute(ToolCall("set_user_preference", {"key": "preferred_browser", "value": "chrome"}))
    shown = registry.execute(ToolCall("show_user_preferences"))

    assert saved.ok
    assert saved.metadata["preference_key"] == "preferred_browser"
    assert settings.preferred_browser == "chrome"
    assert shown.metadata["preferences"]["preferred_browser"] == "chrome"


def test_windows_actions_modes_read_settings_in_dry_run():
    settings = JarvisSettings(
        mode_preferences={"gaming_volume": 75, "study_volume": 22},
        gaming={"close_processes": ["Discord"], "launch_apps": ["Steam"]},
    )
    actions = WindowsActions(dry_run=True, settings=settings)

    study = actions.apply_mode("study")
    gaming = actions.game_mode()

    assert "volume 22%" in study.message
    assert "close: Discord" in gaming.message
    assert "launch: Steam" in gaming.message
    assert gaming.metadata["close_processes"] == ["Discord"]
    assert gaming.metadata["launch_apps"] == ["Steam"]
