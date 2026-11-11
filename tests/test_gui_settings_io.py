from __future__ import annotations

from jarvis.gui.settings_io import load_openai_model, load_raw, save_settings
from jarvis.user_settings import JarvisSettings


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "settings.json"
    settings = JarvisSettings(
        preferred_browser="chrome",
        website_aliases={"plasico": "https://plasico.bg"},
        app_aliases={"disco": "discord.exe"},
        mode_preferences={"quiet_volume": 20},
        gaming={"close_processes": ["Discord"]},
        safety={"confirm_restart": True, "confirm_gaming_mode": False},
    )

    save_settings(settings, path=path)
    loaded = JarvisSettings.load(path)

    assert loaded.preferred_browser == "chrome"
    assert loaded.website_aliases == {"plasico": "https://plasico.bg"}
    assert loaded.app_aliases == {"disco": "discord.exe"}
    assert loaded.mode_preferences == {"quiet_volume": 20}
    assert loaded.gaming == {"close_processes": ["Discord"]}
    assert loaded.safety == {"confirm_restart": True, "confirm_gaming_mode": False}


def test_save_includes_extra_keys_without_breaking_load(tmp_path):
    path = tmp_path / "settings.json"
    settings = JarvisSettings()

    save_settings(settings, extra={"openai_model": "gpt-5.6-mini"}, path=path)

    raw = load_raw(path)
    assert raw["openai_model"] == "gpt-5.6-mini"
    # JarvisSettings.load() must tolerate the unknown key gracefully.
    loaded = JarvisSettings.load(path)
    assert loaded.website_aliases == {}


def test_load_openai_model_returns_none_when_absent(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(JarvisSettings(), path=path)
    assert load_openai_model(path) is None


def test_load_openai_model_returns_saved_value(tmp_path):
    path = tmp_path / "settings.json"
    save_settings(JarvisSettings(), extra={"openai_model": "gpt-5.6-terra"}, path=path)
    assert load_openai_model(path) == "gpt-5.6-terra"


def test_load_raw_returns_empty_dict_when_file_missing(tmp_path):
    assert load_raw(tmp_path / "does_not_exist.json") == {}


def test_save_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "settings.json"
    save_settings(JarvisSettings(), path=path)
    assert path.exists()
