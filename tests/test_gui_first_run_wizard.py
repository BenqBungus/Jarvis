from __future__ import annotations

import json

from jarvis.gui.first_run_wizard import FirstRunWizard, needs_first_run_wizard
from jarvis.user_settings import JarvisSettings


def test_needs_wizard_true_when_settings_file_absent(tmp_path):
    assert needs_first_run_wizard(tmp_path / "does_not_exist.json") is True


def test_needs_wizard_false_when_settings_file_present(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{}", encoding="utf-8")
    assert needs_first_run_wizard(path) is False


def test_wizard_has_all_eight_pages(qapp):
    wizard = FirstRunWizard(JarvisSettings())
    assert len(wizard.pageIds()) == 8


def test_api_key_page_reports_unconfigured_when_env_var_absent(qapp, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    wizard = FirstRunWizard(JarvisSettings())
    assert wizard._api_key_page.is_configured() is False
    assert "not set" in wizard._api_key_page._status_label.text().lower()


def test_api_key_page_reports_configured_when_env_var_present(qapp, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    wizard = FirstRunWizard(JarvisSettings())
    assert wizard._api_key_page.is_configured() is True
    # Must never display the actual key value anywhere.
    assert "sk-test-not-a-real-key" not in wizard._api_key_page._status_label.text()


def test_api_key_page_offers_masked_input_instead_of_terminal_commands(qapp, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    wizard = FirstRunWizard(JarvisSettings())
    from PySide6.QtWidgets import QLineEdit
    assert wizard._api_key_page._key_input.echoMode() == QLineEdit.EchoMode.Password
    assert wizard._api_key_page._key_input.text() == ""


def test_wake_word_page_lists_the_real_configured_wake_words(qapp):
    from jarvis.config import WAKE_WORDS

    wizard = FirstRunWizard(JarvisSettings())
    assert wizard._wake_word_page.listed_phrases() == set(WAKE_WORDS)


def test_permissions_page_reports_writable_directories(qapp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    wizard = FirstRunWizard(JarvisSettings())
    # All three checks should succeed in a fresh writable tmp_path.
    assert wizard._permissions_page.is_writable("data") is True
    assert wizard._permissions_page.is_writable("logs") is True
    assert wizard._permissions_page.is_writable("workspace") is True


def test_check_writable_returns_false_for_an_unwritable_path(qapp):
    from jarvis.gui.first_run_wizard import _PermissionsPage
    from pathlib import Path

    # A path that cannot possibly be created (invalid character sequence on
    # Windows) -- exercises the False branch without relying on real ACLs.
    result = _PermissionsPage._check_writable(Path("Z:\\definitely\\not\\a\\real\\drive\\path"))
    assert result is False


def test_browser_page_loads_existing_preferred_browser(qapp):
    wizard = FirstRunWizard(JarvisSettings(preferred_browser="chrome"))
    assert wizard._browser_page._browser_combo.currentText() == "chrome"


def test_browser_page_selected_browser_reflects_combo_choice(qapp):
    wizard = FirstRunWizard(JarvisSettings())
    wizard._browser_page._browser_combo.setCurrentText("opera_gx")
    assert wizard._browser_page.selected_browser() == "opera_gx"


def test_accept_saves_the_selected_browser(qapp, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = JarvisSettings()
    wizard = FirstRunWizard(settings)
    wizard._browser_page._browser_combo.setCurrentText("edge")

    wizard.accept()

    assert settings.preferred_browser == "edge"
    on_disk = json.loads((tmp_path / "data" / "settings.json").read_text(encoding="utf-8"))
    assert on_disk["preferred_browser"] == "edge"


def test_microphone_page_constructs_without_a_real_mic(qapp):
    # Must not attempt real microphone access just from being constructed --
    # only the "Test microphone" button click should ever touch hardware.
    wizard = FirstRunWizard(JarvisSettings())
    assert wizard._microphone_page is not None


def test_speaker_page_constructs_without_speaking(qapp):
    wizard = FirstRunWizard(JarvisSettings())
    assert wizard._speaker_page is not None
