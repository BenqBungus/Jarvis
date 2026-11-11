"""Settings page: the Personality and Role packs sections save into
settings.personalization and tell the main window after Save."""
from __future__ import annotations

import json

from jarvis.gui.settings_page import SettingsPage
from jarvis.personality import PRESETS
from jarvis.role_packs import DEFAULT_PACKS, PACKS
from jarvis.user_settings import JarvisSettings


def _make_page(qapp, tmp_path, **settings_kwargs):
    path = tmp_path / "settings.json"
    settings = JarvisSettings(**settings_kwargs)
    return SettingsPage(settings, settings_path=path), settings, path


def test_fresh_settings_show_the_defaults(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path)
    assert page._preset_buttons["jarvis"].isChecked()
    assert set(page._preset_buttons) == set(PRESETS)
    assert page._humor_slider.value() == 1 and page._detail_slider.value() == 1
    assert [pack for pack, switch in page._pack_switches.items() if switch.isChecked()] == list(DEFAULT_PACKS)
    assert set(page._pack_switches) == set(PACKS)
    assert page._address_input.text() == ""


def test_loads_what_was_saved(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path, personalization={
        "personality": {"preset": "coach", "humor": 3, "detail": 0},
        "role_packs": ["student", "developer"], "address_name": "Берк"})
    assert page._preset_buttons["coach"].isChecked()
    assert (page._humor_slider.value(), page._detail_slider.value()) == (3, 0)
    assert [pack for pack, switch in page._pack_switches.items() if switch.isChecked()] == ["student", "developer"]
    assert page._address_input.text() == "Берк"


def test_save_writes_personalization_and_emits_it(qapp, tmp_path):
    page, settings, path = _make_page(qapp, tmp_path, personalization={
        "personality": {"preset": "jarvis", "address_as": "sir"}, "address_name": "Берк"})
    emitted = []
    page.personalization_changed.connect(emitted.append)
    page._preset_buttons["engineer"].click()
    page._humor_slider.setValue(0)
    page._detail_slider.setValue(2)
    page._pack_switches["gamer"].setChecked(False)
    page._pack_switches["business"].setChecked(True)
    page._address_input.setText("  Мария ")
    page._on_save()

    stored = json.loads(path.read_text(encoding="utf-8"))["personalization"]
    assert stored["personality"] == {"preset": "engineer", "humor": 0, "detail": 2, "address_as": "sir"}
    assert stored["role_packs"] == ["business"]
    assert stored["address_name"] == "Мария"
    assert settings.personalization["role_packs"] == ["business"]
    assert emitted and emitted[-1]["role_packs"] == ["business"]
    assert emitted[-1]["personality"]["preset"] == "engineer"


def test_no_packs_is_a_real_choice_and_an_empty_name_is_removed(qapp, tmp_path):
    page, _settings, path = _make_page(qapp, tmp_path, personalization={"address_name": "Берк"})
    for switch in page._pack_switches.values():
        switch.setChecked(False)
    page._address_input.clear()
    page._on_save()
    stored = json.loads(path.read_text(encoding="utf-8"))["personalization"]
    assert stored["role_packs"] == []
    assert "address_name" not in stored
    assert page.current_personalization()["role_packs"] == []


def test_preview_follows_the_preset_and_language(qapp, tmp_path):
    page, _settings, _path = _make_page(qapp, tmp_path, openai={"conversation_language": "en"})
    page._preset_buttons["friend"].click()
    assert PRESETS["friend"].samples["en"] in page._preview_quote.text()
    assert "Friend" in page._preview_caption.text()
    page._language_combo.setCurrentIndex(page._language_combo.findData("bg"))
    assert PRESETS["friend"].samples["bg"] in page._preview_quote.text()
    page._humor_slider.setValue(3)
    assert "playful" in page._preview_caption.text()


def test_main_window_follows_the_saved_packs(qapp, tmp_path):
    from jarvis.gui.main_window import MainWindow

    page, _settings, _path = _make_page(qapp, tmp_path, personalization={"role_packs": ["student"]})
    window = MainWindow()
    window.set_settings_widget(page)
    assert list(window._pack_cards) == ["student"]
    page._pack_switches["gamer"].setChecked(True)
    page._on_save()
    assert list(window._pack_cards) == ["gamer", "student"]
    window.deleteLater()
