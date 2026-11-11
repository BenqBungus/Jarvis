from __future__ import annotations

import json

from jarvis.gui.settings_io import load_raw
from jarvis.gui.settings_page import SettingsPage
from jarvis.user_settings import JarvisSettings


def _make_page(qapp, tmp_path, **settings_kwargs):
    path = tmp_path / "settings.json"
    settings = JarvisSettings(**settings_kwargs)
    page = SettingsPage(settings, settings_path=path)
    return page, settings, path


def test_loads_existing_website_and_app_aliases(qapp, tmp_path):
    page, _settings, _path = _make_page(
        qapp,
        tmp_path,
        website_aliases={"plasico": "https://plasico.bg"},
        app_aliases={"disco": "discord.exe"},
    )
    assert page._website_table.to_dict() == {"plasico": "https://plasico.bg"}
    assert page._app_table.to_dict() == {"disco": "discord.exe"}


def test_loads_existing_safety_flags(qapp, tmp_path):
    page, _settings, _path = _make_page(
        qapp, tmp_path, safety={"confirm_restart": False, "confirm_gaming_mode": True}
    )
    assert page._safety_checkboxes["confirm_restart"].isChecked() is False
    assert page._safety_checkboxes["confirm_gaming_mode"].isChecked() is True


def test_safety_flags_default_to_checked_when_unset(qapp, tmp_path):
    # JarvisSettings.safety_enabled() defaults True when a key is absent --
    # the checkboxes must reflect that same default.
    page, _settings, _path = _make_page(qapp, tmp_path, safety={})
    assert all(checkbox.isChecked() for checkbox in page._safety_checkboxes.values())


def test_add_and_remove_website_alias_row(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    page._website_table.add_blank_row()
    row = page._website_table.rowCount() - 1
    page._website_table.item(row, 0).setText("youtube")
    page._website_table.item(row, 1).setText("https://youtube.com")
    assert page._website_table.to_dict() == {"youtube": "https://youtube.com"}

    page._website_table.selectRow(row)
    page._website_table.remove_selected_row()
    assert page._website_table.to_dict() == {}


def test_blank_or_incomplete_rows_are_excluded_from_to_dict(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    page._website_table.add_blank_row()  # left fully blank
    page._website_table.add_blank_row()
    row = page._website_table.rowCount() - 1
    page._website_table.item(row, 0).setText("onlykey")  # no value
    assert page._website_table.to_dict() == {}


def test_save_persists_to_disk_at_the_given_path(qapp, tmp_path):
    page, settings, path = _make_page(qapp, tmp_path)
    page._website_table.add_blank_row()
    row = page._website_table.rowCount() - 1
    page._website_table.item(row, 0).setText("youtube")
    page._website_table.item(row, 1).setText("https://youtube.com")

    page._on_save()

    assert path.exists()
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk["website_aliases"] == {"youtube": "https://youtube.com"}


def test_save_mutates_the_shared_settings_object_in_place(qapp, tmp_path):
    page, settings, _path = _make_page(qapp, tmp_path)
    original_dict_identity = settings.website_aliases

    page._website_table.add_blank_row()
    row = page._website_table.rowCount() - 1
    page._website_table.item(row, 0).setText("plasico")
    page._website_table.item(row, 1).setText("https://plasico.bg")

    page._on_save()

    # Same dict object mutated in place (clear+update), not replaced -- this
    # is what makes a live router.py instance see the change without
    # needing to reload JarvisSettings.
    assert settings.website_aliases is original_dict_identity
    assert settings.website_aliases == {"plasico": "https://plasico.bg"}


def test_save_persists_safety_checkbox_state(qapp, tmp_path):
    page, settings, path = _make_page(qapp, tmp_path)
    page._safety_checkboxes["confirm_restart"].setChecked(False)

    page._on_save()

    assert settings.safety["confirm_restart"] is False
    on_disk = load_raw(path)
    assert on_disk["safety"]["confirm_restart"] is False


def test_save_emits_saved_signal(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    received = []
    page.saved.connect(lambda: received.append(True))
    page._on_save()
    assert received == [True]


def test_save_with_empty_model_field_does_not_touch_openai_model_key(qapp, tmp_path):
    page, _settings, path = _make_page(qapp, tmp_path)
    page._on_save()
    on_disk = load_raw(path)
    assert "openai_model" not in on_disk


def test_save_with_model_field_persists_and_updates_env(qapp, tmp_path, monkeypatch):
    # JarvisSettings.openai is now a real dataclass field (was an ad hoc
    # top-level "openai_model" key before Codex added it) -- the model
    # lives at settings.openai["model"], persisted via dataclasses.asdict().
    monkeypatch.delenv("JARVIS_OPENAI_MODEL", raising=False)

    class _FakeAi:
        model = "gpt-5.6"

    page, _settings, path = _make_page(qapp, tmp_path)
    ai = _FakeAi()
    page._ai = ai
    page._model_input.setText("gpt-5.6-terra")

    page._on_save()

    on_disk = load_raw(path)
    assert on_disk["openai"]["model"] == "gpt-5.6-terra"
    assert ai.model == "gpt-5.6-terra"
    import os

    assert os.environ["JARVIS_OPENAI_MODEL"] == "gpt-5.6-terra"


def test_loads_previously_saved_openai_model_on_construction(qapp, tmp_path):
    from jarvis.gui.settings_io import save_settings

    path = tmp_path / "settings.json"
    save_settings(JarvisSettings(openai={"model": "gpt-5.6-mini"}), path=path)

    page = SettingsPage(JarvisSettings.load(path), settings_path=path)

    assert page._model_input.text() == "gpt-5.6-mini"


# --- Preferred browser ----------------------------------------------------------


def test_loads_existing_preferred_browser_and_path(qapp, tmp_path):
    page, _settings, _path = _make_page(
        qapp, tmp_path, preferred_browser="opera_gx", browser_paths={"opera_gx": "C:\\Opera GX\\opera.exe"}
    )
    assert page._browser_combo.currentText() == "opera_gx"
    assert page._browser_path_input.text() == "C:\\Opera GX\\opera.exe"


def test_save_persists_preferred_browser_and_path(qapp, tmp_path):
    page, settings, path = _make_page(qapp, tmp_path)
    page._browser_combo.setCurrentText("chrome")
    page._browser_path_input.setText("C:\\Chrome\\chrome.exe")

    page._on_save()

    assert settings.preferred_browser == "chrome"
    assert settings.browser_paths["chrome"] == "C:\\Chrome\\chrome.exe"
    on_disk = load_raw(path)
    assert on_disk["preferred_browser"] == "chrome"
    assert on_disk["browser_paths"]["chrome"] == "C:\\Chrome\\chrome.exe"


def test_save_without_a_path_override_does_not_add_a_browser_paths_entry(qapp, tmp_path):
    page, settings, _path = _make_page(qapp, tmp_path)
    page._browser_combo.setCurrentText("edge")
    page._on_save()
    assert "edge" not in settings.browser_paths


# --- Mode volumes ----------------------------------------------------------------


def test_mode_volumes_default_to_windows_actions_hardcoded_values(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    assert page._mode_spinboxes["quiet_volume"].value() == 20
    assert page._mode_spinboxes["study_volume"].value() == 35
    assert page._mode_spinboxes["battery_volume"].value() == 20
    assert page._mode_spinboxes["gaming_volume"].value() == 60
    assert page._temperature_spinbox.value() == 85


def test_loads_existing_mode_preferences(qapp, tmp_path):
    page, _settings, _path = _make_page(
        qapp, tmp_path, mode_preferences={"quiet_volume": 15, "temperature_warning_c": 90}
    )
    assert page._mode_spinboxes["quiet_volume"].value() == 15
    assert page._temperature_spinbox.value() == 90


def test_save_persists_mode_preferences(qapp, tmp_path):
    page, settings, path = _make_page(qapp, tmp_path)
    page._mode_spinboxes["gaming_volume"].setValue(75)
    page._temperature_spinbox.setValue(95)

    page._on_save()

    assert settings.mode_preferences["gaming_volume"] == 75
    assert settings.mode_preferences["temperature_warning_c"] == 95
    on_disk = load_raw(path)
    assert on_disk["mode_preferences"]["gaming_volume"] == 75


# --- Gaming apps -------------------------------------------------------------------


def test_loads_existing_gaming_app_lists(qapp, tmp_path):
    page, _settings, _path = _make_page(
        qapp, tmp_path, gaming={"close_processes": ["Discord", "Spotify"], "launch_apps": ["Steam"]}
    )
    assert page._close_processes_list.to_list() == ["Discord", "Spotify"]
    assert page._launch_apps_list.to_list() == ["Steam"]


def test_add_and_remove_gaming_close_process(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    page._close_processes_list.add_blank_item()
    page._close_processes_list.item(0).setText("Teams")
    assert page._close_processes_list.to_list() == ["Teams"]

    page._close_processes_list.setCurrentRow(0)
    page._close_processes_list.remove_selected_item()
    assert page._close_processes_list.to_list() == []


def test_save_persists_gaming_app_lists(qapp, tmp_path):
    page, settings, path = _make_page(qapp, tmp_path)
    page._close_processes_list.add_blank_item()
    page._close_processes_list.item(0).setText("EpicGamesLauncher")
    page._launch_apps_list.add_blank_item()
    page._launch_apps_list.item(0).setText("Steam")

    page._on_save()

    assert settings.gaming["close_processes"] == ["EpicGamesLauncher"]
    assert settings.gaming["launch_apps"] == ["Steam"]
    on_disk = load_raw(path)
    assert on_disk["gaming"]["close_processes"] == ["EpicGamesLauncher"]


# --- Voice provider settings -------------------------------------------------------


def test_loads_existing_voice_provider_settings(qapp, tmp_path):
    page, _settings, _path = _make_page(
        qapp,
        tmp_path,
        openai={
            "speech_to_text_provider": "openai",
            "speech_to_text_model": "gpt-transcribe",
            "tts_provider": "openai",
            "text_to_speech_model": "gpt-4o-mini-tts",
            "text_to_speech_voice": "marin",
            "audio_output_device": "2: SteelSeries Sonar - Gaming (WASAPI)",
        },
    )
    assert page._stt_provider_combo.currentText() == "openai"
    assert page._stt_model_input.text() == "gpt-transcribe"
    assert page._tts_provider_combo.currentText() == "openai"
    assert page._tts_model_input.text() == "gpt-4o-mini-tts"
    assert page._tts_voice_combo.currentText() == "marin"
    assert page._audio_output_combo.currentText() == "2: SteelSeries Sonar - Gaming (WASAPI)"


def test_voice_provider_defaults_when_unset(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    assert page._stt_provider_combo.currentText() == "google"
    assert page._tts_provider_combo.currentText() == "windows"
    assert page._live_audio_mode.currentText() == "Speakers"


def test_live_headphone_mode_persists_and_reloads(qapp, tmp_path):
    page, settings, path = _make_page(qapp, tmp_path)
    page._live_audio_mode.setCurrentIndex(1)
    page._on_save()
    assert settings.openai["realtime_speaker_guard"] is False
    assert load_raw(path)["openai"]["realtime_speaker_guard"] is False
    page._load_from_settings()
    assert page._live_audio_mode.currentText() == "Headphones"


def test_tts_voice_combo_offers_the_real_openai_voice_list(qapp, tmp_path):
    from jarvis.audio.text_to_speech import OPENAI_TTS_VOICES

    page, _settings, _path = _make_page(qapp, tmp_path)
    combo_items = {page._tts_voice_combo.itemText(i) for i in range(page._tts_voice_combo.count())}
    assert combo_items == set(OPENAI_TTS_VOICES)


def test_save_persists_voice_provider_settings(qapp, tmp_path):
    page, settings, path = _make_page(qapp, tmp_path)
    page._stt_provider_combo.setCurrentText("openai")
    page._stt_model_input.setText("gpt-transcribe")
    page._tts_provider_combo.setCurrentText("openai")
    page._tts_voice_combo.setCurrentText("cedar")
    page._audio_output_combo.setCurrentText("2: SteelSeries Sonar - Gaming (WASAPI)")

    page._on_save()

    assert settings.openai["speech_to_text_provider"] == "openai"
    assert settings.openai["speech_to_text_model"] == "gpt-transcribe"
    assert settings.openai["tts_provider"] == "openai"
    assert settings.openai["text_to_speech_voice"] == "cedar"
    assert settings.openai["audio_output_device"] == "2: SteelSeries Sonar - Gaming (WASAPI)"
    on_disk = load_raw(path)
    assert on_disk["openai"]["speech_to_text_provider"] == "openai"


# --- Noise threshold settings ------------------------------------------------------


def test_noise_thresholds_default_to_auto(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    assert page._energy_threshold_spinbox.value() == 0
    assert page._pause_threshold_spinbox.value() == 0


def test_loads_existing_noise_thresholds(qapp, tmp_path):
    page, _settings, _path = _make_page(
        qapp, tmp_path, openai={"energy_threshold": 500, "pause_threshold_ms": 1200}
    )
    assert page._energy_threshold_spinbox.value() == 500
    assert page._pause_threshold_spinbox.value() == 1200


def test_save_persists_noise_thresholds(qapp, tmp_path):
    page, settings, path = _make_page(qapp, tmp_path)
    page._energy_threshold_spinbox.setValue(400)
    page._pause_threshold_spinbox.setValue(600)

    page._on_save()

    assert settings.openai["energy_threshold"] == 400
    assert settings.openai["pause_threshold_ms"] == 600
    on_disk = load_raw(path)
    assert on_disk["openai"]["energy_threshold"] == 400
    assert on_disk["openai"]["pause_threshold_ms"] == 600


def test_save_with_thresholds_left_at_auto_stores_none(qapp, tmp_path):
    page, settings, _path = _make_page(qapp, tmp_path)
    page._on_save()
    assert settings.openai["energy_threshold"] is None
    assert settings.openai["pause_threshold_ms"] is None


# --- Startup (autostart) -----------------------------------------------------------


def test_startup_checkbox_reflects_real_autostart_state_when_enabled(qapp, tmp_path, monkeypatch):
    from jarvis.gui import settings_page

    monkeypatch.setattr(settings_page.autostart, "is_enabled", lambda: True)
    page, _settings, _path = _make_page(qapp, tmp_path)
    assert page._autostart_checkbox.isChecked() is True


def test_startup_checkbox_reflects_real_autostart_state_when_disabled(qapp, tmp_path, monkeypatch):
    from jarvis.gui import settings_page

    monkeypatch.setattr(settings_page.autostart, "is_enabled", lambda: False)
    page, _settings, _path = _make_page(qapp, tmp_path)
    assert page._autostart_checkbox.isChecked() is False


def test_constructing_the_page_never_calls_enable_or_disable(qapp, tmp_path, monkeypatch):
    # Regression guard for the blockSignals() guard in _load_from_settings():
    # merely opening Settings must never touch the real Startup folder just
    # to sync the checkbox to what is already true on disk.
    from jarvis.gui import settings_page

    def _fail(*_args, **_kwargs):
        raise AssertionError("enable()/disable() must not be called while loading settings")

    monkeypatch.setattr(settings_page.autostart, "is_enabled", lambda: True)
    monkeypatch.setattr(settings_page.autostart, "enable", _fail)
    monkeypatch.setattr(settings_page.autostart, "disable", _fail)
    _make_page(qapp, tmp_path)  # must not raise


def test_checking_the_startup_checkbox_calls_enable_immediately(qapp, tmp_path, monkeypatch):
    from jarvis.gui import settings_page

    calls = []
    monkeypatch.setattr(settings_page.autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(settings_page.autostart, "enable", lambda: calls.append("enable") or True)
    monkeypatch.setattr(settings_page.autostart, "disable", lambda: calls.append("disable") or True)

    page, _settings, _path = _make_page(qapp, tmp_path)
    page._autostart_checkbox.setChecked(True)

    assert calls == ["enable"]
    assert page._autostart_status_label.text() == ""


def test_unchecking_the_startup_checkbox_calls_disable_immediately(qapp, tmp_path, monkeypatch):
    from jarvis.gui import settings_page

    calls = []
    monkeypatch.setattr(settings_page.autostart, "is_enabled", lambda: True)
    monkeypatch.setattr(settings_page.autostart, "enable", lambda: calls.append("enable") or True)
    monkeypatch.setattr(settings_page.autostart, "disable", lambda: calls.append("disable") or True)

    page, _settings, _path = _make_page(qapp, tmp_path)
    page._autostart_checkbox.setChecked(False)

    assert calls == ["disable"]
    assert page._autostart_status_label.text() == ""


def test_toggle_failure_shows_a_message_and_reverts_the_checkbox(qapp, tmp_path, monkeypatch):
    from jarvis.gui import settings_page

    monkeypatch.setattr(settings_page.autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(settings_page.autostart, "enable", lambda: False)

    page, _settings, _path = _make_page(qapp, tmp_path)
    page._autostart_checkbox.setChecked(True)

    assert page._autostart_checkbox.isChecked() is False
    assert "Could not enable" in page._autostart_status_label.text()


# --- Privacy: use_memory_context ---------------------------------------------------


def test_use_memory_context_defaults_to_checked_when_unset(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    assert page._use_memory_context_checkbox.isChecked() is True


def test_loads_existing_use_memory_context_value(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path, openai={"use_memory_context": False})
    assert page._use_memory_context_checkbox.isChecked() is False


def test_save_persists_use_memory_context(qapp, tmp_path):
    page, settings, path = _make_page(qapp, tmp_path)
    page._use_memory_context_checkbox.setChecked(False)

    page._on_save()

    assert settings.openai["use_memory_context"] is False
    on_disk = load_raw(path)
    assert on_disk["openai"]["use_memory_context"] is False


def test_saving_settings_does_not_touch_autostart(qapp, tmp_path, monkeypatch):
    # Save is for the batched fields only -- autostart applies on toggle,
    # not on Save, so _on_save() must never call enable()/disable().
    from jarvis.gui import settings_page

    def _fail(*_args, **_kwargs):
        raise AssertionError("_on_save() must not touch autostart")

    monkeypatch.setattr(settings_page.autostart, "is_enabled", lambda: False)
    monkeypatch.setattr(settings_page.autostart, "enable", _fail)
    monkeypatch.setattr(settings_page.autostart, "disable", _fail)

    page, _settings, _path = _make_page(qapp, tmp_path)
    page._on_save()  # must not raise


# --- Global hotkey -----------------------------------------------------------------


class _FakeHotkeyManager:
    def __init__(self, register_result: bool = True) -> None:
        self.register_result = register_result
        self.register_calls = 0
        self.unregister_calls = 0
        self.registered = False

    def register(self) -> bool:
        self.register_calls += 1
        if self.register_result:
            self.registered = True
        return self.register_result

    def unregister(self) -> None:
        self.unregister_calls += 1
        self.registered = False


def test_hotkey_checkbox_defaults_to_checked_when_unset(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    assert page._hotkey_checkbox.isChecked() is True


def test_loads_existing_hotkey_enabled_value(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path, mode_preferences={"hotkey_enabled": False})
    assert page._hotkey_checkbox.isChecked() is False


def test_constructing_the_page_never_calls_hotkey_register_or_unregister(qapp, tmp_path):
    manager = _FakeHotkeyManager()
    path = tmp_path / "settings.json"
    settings = JarvisSettings(mode_preferences={"hotkey_enabled": True})
    SettingsPage(settings, settings_path=path, hotkey_manager=manager)
    assert manager.register_calls == 0
    assert manager.unregister_calls == 0


def test_checking_the_hotkey_checkbox_calls_register_and_persists(qapp, tmp_path):
    manager = _FakeHotkeyManager(register_result=True)
    path = tmp_path / "settings.json"
    settings = JarvisSettings(mode_preferences={"hotkey_enabled": False})
    page = SettingsPage(settings, settings_path=path, hotkey_manager=manager)

    page._hotkey_checkbox.setChecked(True)

    assert manager.register_calls == 1
    assert page._hotkey_status_label.text() == ""
    assert settings.mode_preferences["hotkey_enabled"] is True
    on_disk = load_raw(path)
    assert on_disk["mode_preferences"]["hotkey_enabled"] is True


def test_unchecking_the_hotkey_checkbox_calls_unregister_and_persists(qapp, tmp_path):
    manager = _FakeHotkeyManager()
    manager.registered = True
    path = tmp_path / "settings.json"
    settings = JarvisSettings(mode_preferences={"hotkey_enabled": True})
    page = SettingsPage(settings, settings_path=path, hotkey_manager=manager)

    page._hotkey_checkbox.setChecked(False)

    assert manager.unregister_calls == 1
    assert settings.mode_preferences["hotkey_enabled"] is False
    on_disk = load_raw(path)
    assert on_disk["mode_preferences"]["hotkey_enabled"] is False


def test_hotkey_registration_failure_reverts_checkbox_and_settings(qapp, tmp_path):
    manager = _FakeHotkeyManager(register_result=False)
    path = tmp_path / "settings.json"
    settings = JarvisSettings(mode_preferences={"hotkey_enabled": False})
    page = SettingsPage(settings, settings_path=path, hotkey_manager=manager)

    page._hotkey_checkbox.setChecked(True)

    assert page._hotkey_checkbox.isChecked() is False
    assert "Could not enable" in page._hotkey_status_label.text()
    assert settings.mode_preferences["hotkey_enabled"] is False
    on_disk = load_raw(path)
    assert on_disk["mode_preferences"]["hotkey_enabled"] is False


def test_hotkey_toggled_signal_emits_the_final_checked_state(qapp, tmp_path):
    manager = _FakeHotkeyManager(register_result=True)
    path = tmp_path / "settings.json"
    settings = JarvisSettings(mode_preferences={"hotkey_enabled": False})
    page = SettingsPage(settings, settings_path=path, hotkey_manager=manager)
    received = []
    page.hotkey_toggled.connect(received.append)

    page._hotkey_checkbox.setChecked(True)

    assert received == [True]


def test_hotkey_toggled_signal_emits_false_after_a_reverted_failed_registration(qapp, tmp_path):
    manager = _FakeHotkeyManager(register_result=False)
    path = tmp_path / "settings.json"
    settings = JarvisSettings(mode_preferences={"hotkey_enabled": False})
    page = SettingsPage(settings, settings_path=path, hotkey_manager=manager)
    received = []
    page.hotkey_toggled.connect(received.append)

    page._hotkey_checkbox.setChecked(True)

    # The checkbox reverted to unchecked before the signal fired, so
    # listeners see the real final state, not the momentarily-requested one.
    assert received == [False]


def test_toggling_hotkey_with_no_manager_does_not_raise(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    page._hotkey_checkbox.setChecked(True)  # hotkey_manager=None by default in _make_page
    page._hotkey_checkbox.setChecked(False)
