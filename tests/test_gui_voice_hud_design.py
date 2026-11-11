"""Design-system checks for the "Aurora" UI (voice_core, main window, settings,
overlay, splash, wizard, tray). Offscreen tests run Fusion with no fonts, so
these check structure and behaviour; the real look is verified by renders."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QCheckBox, QPushButton, QStyle, QWidget

from jarvis.gui import voice_core
from jarvis.user_settings import JarvisSettings


def _collect_qt_warnings(qapp, apply):
    from PySide6.QtCore import qInstallMessageHandler

    messages: list[str] = []
    previous = qInstallMessageHandler(lambda _mode, _context, message: messages.append(message))
    try:
        apply()
        qapp.processEvents()
    finally:
        qInstallMessageHandler(previous)
    return messages


def test_every_stylesheet_parses_and_keeps_its_scoped_selectors(qapp):
    from jarvis.gui.first_run_wizard import WIZARD_STYLE
    from jarvis.gui.main_window import HUD_STYLE
    from jarvis.gui.overlay import OVERLAY_STYLE
    from jarvis.gui.settings_page import SETTINGS_STYLE
    from jarvis.gui.splash import SPLASH_STYLE

    required = {
        HUD_STYLE: ('QPushButton[variant="primary"]', "#hud", "#settingsDialog"),
        SETTINGS_STYLE: ("#settingsPage QGroupBox", "#settingsNav QPushButton"),
        OVERLAY_STYLE: ("#commandOverlay", "#modeSwitch QPushButton:checked"),
        WIZARD_STYLE: ("#setupWizard", "#setupSteps"),
        SPLASH_STYLE: ("#startupSplash QProgressBar::chunk",),
    }
    for sheet, selectors in required.items():
        for selector in selectors:
            assert selector in sheet

    def apply():
        for sheet in required:
            host = QWidget()
            host.setStyleSheet(sheet)
            QPushButton("probe", host)
            host.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            host.show()
            qapp.processEvents()
            host.close()

    warnings = _collect_qt_warnings(qapp, apply)
    assert not [message for message in warnings if "parse" in message.lower()]


def test_global_rules_stay_neutral_for_codex_dialogs():
    # Codex's GmailSettingsDialog and the safety QMessageBox inherit every
    # global rule, so the base sheet must not carry component layouts.
    for selector in ("QGroupBox", "#hud", "#settingsNav", "QCheckBox::indicator", "QGraphics"):
        assert selector not in voice_core.BASE_STYLE


def test_glyph_icon_falls_back_to_the_codex_icon_without_icon_fonts(qapp, monkeypatch):
    monkeypatch.setattr(voice_core, "_GLYPH_FAMILY", None)
    monkeypatch.setattr(voice_core, "_ICON_CACHE", {})
    style = qapp.style()
    assert not voice_core.glyph_icon("mic", QStyle.StandardPixmap.SP_MediaVolume, style).isNull()
    assert not voice_core.glyph_icon("not-a-glyph", QStyle.StandardPixmap.SP_DialogOkButton, style).isNull()


def test_arrow_images_are_real_pngs_at_every_density():
    if not voice_core._ARROWS:
        pytest.skip("temp folder not writable; native arrows are used instead")
    for key, path in voice_core._ARROWS.items():
        for suffix, size in (("", 10), ("@2x", 20), ("@3x", 30)):
            image = QImage(path.replace(".png", f"{suffix}.png"))
            assert not image.isNull(), (key, suffix)
            assert (image.width(), image.height()) == (size, size)
        assert path in voice_core.BASE_STYLE


@pytest.mark.parametrize("state", ["idle", "listening", "thinking", "speaking", "error", "muted"])
def test_orb_center_is_bright_in_every_state(qapp, state):
    from jarvis.gui.main_window import MainWindow

    window = MainWindow()
    window.resize(1360, 850)
    window._core.set_state(state)
    for _ in range(12):
        window._core.set_level(0.4)
        window._core._animate()
    image = window.grab().toImage()
    center = window._core.mapTo(window, window._core.rect().center())
    color = image.pixelColor(center)
    assert max(color.red(), color.green(), color.blue()) >= 90, (state, color.name())
    window.close()


def _settings_page(tmp_path):
    from jarvis.gui.settings_page import SettingsPage

    page = SettingsPage(JarvisSettings(), settings_path=tmp_path / "settings.json")
    page.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    page.resize(980, 620)
    page.show()
    return page


def test_settings_navigation_scrolls_the_section_to_the_top(qapp, tmp_path, pump_events):
    page = _settings_page(tmp_path)
    qapp.processEvents()
    page._scroll_animation.setDuration(1)
    group, button = next(entry for entry in page._sections if entry[0].title() == "Safety confirmations")
    button.click()
    bar = page._scroll.verticalScrollBar()
    assert pump_events(lambda: abs(group.y() - 4 - bar.value()) <= 1 or bar.value() == bar.maximum())
    assert button.isChecked()
    assert sum(entry.isChecked() for _group, entry in page._sections) == 1
    page.close()


def test_settings_navigation_follows_a_manual_scroll(qapp, tmp_path):
    page = _settings_page(tmp_path)
    qapp.processEvents()
    bar = page._scroll.verticalScrollBar()
    bar.setValue(bar.maximum())
    qapp.processEvents()
    assert page._sections[-1][1].isChecked()
    target = page._sections[4][0]
    bar.setValue(target.y() + 10)
    qapp.processEvents()
    assert page._sections[4][1].isChecked()
    page.close()


def test_app_py_integration_widgets_land_in_the_rail_and_the_hotkey_card(qapp, tmp_path):
    from PySide6.QtWidgets import QCheckBox

    page = _settings_page(tmp_path)
    # Exactly what app.py does: two buttons at index 0, a shortcut toggle at index 1.
    gmail = QPushButton("Gmail", page)
    page.layout().insertWidget(0, gmail)
    game = QPushButton("Game Chat", page)
    page.layout().insertWidget(0, game)
    shortcut = QCheckBox("Ctrl+Alt+Space | Game Chat", page)
    page.layout().insertWidget(1, shortcut)
    qapp.processEvents()
    assert gmail.parentWidget() is page._nav and game.parentWidget() is page._nav
    assert page._accounts_label.text() == "INTEGRATIONS" and not page._accounts_label.isHidden()
    assert page._hotkey_card.group.isAncestorOf(shortcut)
    assert all(page.layout().indexOf(widget) == -1 for widget in (gmail, game, shortcut))
    page.close()


def test_settings_toggles_are_still_checkboxes_and_click_anywhere(qapp, tmp_path):
    page = _settings_page(tmp_path)
    qapp.processEvents()
    switch = page._full_access_checkbox
    assert isinstance(switch, QCheckBox)
    was = switch.isChecked()
    QTest.mouseClick(switch, Qt.MouseButton.LeftButton, pos=QPoint(4, switch.height() // 2))
    assert switch.isChecked() is not was
    for checkbox in page._safety_checkboxes.values():
        assert isinstance(checkbox, QCheckBox)
    page.close()


def test_settings_status_lines_only_take_space_with_text(qapp, tmp_path):
    page = _settings_page(tmp_path)
    label = page._hotkey_status_label
    assert label.isHidden()
    label.setText("Could not enable: Ctrl+Space may already be used by another application.")
    assert not label.isHidden()
    label.setText("")
    assert label.isHidden()
    page.close()


def test_settings_warn_when_bulgarian_replies_would_be_silent(qapp, tmp_path, monkeypatch):
    from jarvis.gui.settings_page import SettingsPage

    monkeypatch.setattr(SettingsPage, "_installed_windows_voices", staticmethod(lambda: {"en"}))
    page = _settings_page(tmp_path)
    warning = page._tts_language_warning
    page._language_combo.setCurrentIndex(page._language_combo.findData("bg"))
    page._tts_provider_combo.setCurrentText("windows")
    assert not warning.isHidden() and "Bulgarian" in warning.text()
    page._tts_provider_combo.setCurrentText("openai")
    assert warning.isHidden()
    page._tts_provider_combo.setCurrentText("windows")
    page._language_combo.setCurrentIndex(page._language_combo.findData("en"))
    assert warning.isHidden()
    page.close()


def test_save_shows_saved_and_keeps_the_primary_button(qapp, tmp_path):
    page = _settings_page(tmp_path)
    assert page._save_button.property("variant") == "primary"
    page._on_save()
    assert page._status_label.text() == "Saved."
    assert page._status_timer.isActive()
    page.close()


def test_overlay_mode_switch_mirrors_the_mode_combo(qapp):
    from jarvis.gui.overlay import OverlayWidget

    overlay = OverlayWidget()
    assert [overlay.mode.itemData(i) for i in range(overlay.mode.count())] == [
        "overlay", "overlay_local", "overlay_teach"]
    overlay.mode.setCurrentIndex(2)
    assert overlay._mode_buttons.button(2).isChecked()
    overlay._mode_buttons.button(1).click()
    assert overlay.mode.currentData() == "overlay_local"
    overlay.set_state("processing")
    assert overlay.current_state_text() == "Thinking..."
    overlay.show_result("Nope.", False)
    assert overlay.output.property("tone") == "error"


def test_splash_shows_readable_stage_and_percent(qapp):
    from jarvis.gui.splash import StartupSplash

    splash = StartupSplash()
    splash.set_progress(40)
    assert splash._status == "LOADING MODULES"
    assert splash._status_label.text() == "Loading modules"
    assert splash._percent_label.text() == "40%"


def test_wizard_step_rail_follows_the_current_page(qapp, tmp_path, monkeypatch):
    from jarvis.gui.first_run_wizard import FirstRunWizard
    from PySide6.QtWidgets import QWizard

    monkeypatch.chdir(tmp_path)
    wizard = FirstRunWizard(JarvisSettings())
    wizard.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    wizard.show()
    qapp.processEvents()
    wizard.next()
    wizard.next()
    states = [row._state for row in wizard._step_rail._rows]
    assert states[:3] == ["done", "done", "current"]
    assert set(states[3:]) == {"upcoming"}
    assert wizard.button(QWizard.WizardButton.NextButton).property("variant") == "primary"
    wizard.close()


def test_load_chart_follows_percent_readings_only(qapp):
    from jarvis.gui.main_window import MainWindow

    window = MainWindow()
    window.update_dashboard("cpu", "12%")
    window.update_dashboard("gpu", "63% (47C)")
    window.update_dashboard("memory", "49% (6.6/16.0 GB)")
    window.update_dashboard("gpu", "not detected")
    window.update_dashboard("disk", "61% free (302/496 GB)")  # not a series; ignored
    history = window._load_chart._history
    assert list(history["cpu"]) == [12.0]
    assert list(history["gpu"]) == [63.0]
    assert list(history["memory"]) == [49.0]
    assert "disk" not in history
    assert window._dashboard_labels["gpu"].text() == "not detected"
    window.close()


def test_header_health_summarises_the_readiness_checks(qapp):
    from jarvis.gui.main_window import MainWindow

    window = MainWindow()
    assert window._health_label.text() == "STANDING BY"
    window.set_setup_checks({"openai_key": (True, "ok"), "realtime_deps": (True, "ok")})
    assert window._health_label.text() == "ALL SYSTEMS NOMINAL"
    window.set_setup_check("tts", False, "Windows has no Bulgarian fallback voice.")
    assert window._health_label.text() == "1 CHECK NEEDS ATTENTION"
    assert "STARTUP VOICE" in window._health_label.toolTip()
    window.set_setup_check("classic_mic", False, "No microphone")
    assert window._health_label.text() == "2 CHECKS NEED ATTENTION"
    window.close()


def test_orb_rings_boot_in_after_first_show_only(qapp):
    from jarvis.gui.voice_core import JarvisCoreWidget

    core = JarvisCoreWidget()
    assert core._boot_progress() == 1.0  # never shown: renders fully booted
    core.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    core.show()
    assert core._boot_progress() < 1.0
    core._booted_at -= 5
    assert core._boot_progress() == 1.0
    core.close()


def test_overlay_shimmer_runs_only_while_work_is_pending(qapp):
    from jarvis.gui.overlay import OverlayWidget

    overlay = OverlayWidget()
    assert not overlay._shimmer.is_active()
    overlay.command_input.setText("звук на 30")
    overlay._submit()
    assert overlay._shimmer.is_active()
    overlay.show_result("Volume set to 30%.", True)
    assert not overlay._shimmer.is_active()
    overlay.set_state("processing")
    assert overlay._shimmer.is_active()
    overlay.set_state("idle")
    assert not overlay._shimmer.is_active()


def test_tray_quick_controls_press_the_windows_own_buttons(qapp):
    from jarvis.gui.main_window import MainWindow
    from jarvis.gui.tray import TrayIcon

    window = MainWindow()
    tray = TrayIcon(window)
    started, muted, overlays = [], [], []
    window.realtime_start_requested.connect(lambda: started.append(True))
    window.input_mute_requested.connect(muted.append)
    window.overlay_requested.connect(lambda: overlays.append(True))
    tray._sync_menu()
    assert tray._call_action.text() == "Start live call"
    assert not tray._mute_action.isEnabled()  # no call, nothing to mute
    window.set_realtime_status(True, "Ready to connect")
    tray._sync_menu()
    assert tray._call_action.isEnabled()
    tray._call_action.trigger()
    assert started == [True]
    window.set_realtime_active(True, "listening")
    tray._sync_menu()
    assert tray._call_action.text() == "End live call" and tray._mute_action.isEnabled()
    tray._mute_action.trigger()
    assert muted == [True]
    next(action for action in tray._menu.actions() if action.text() == "Command overlay").trigger()
    assert overlays == [True]
    window.close()


def test_tray_icons_are_drawn_at_native_tray_sizes(qapp):
    from jarvis.gui import tray

    for color in tray._STATE_COLORS.values():
        sizes = {(size.width(), size.height()) for size in tray._make_state_icon(color).availableSizes()}
        assert {(16, 16), (24, 24), (64, 64)} <= sizes
