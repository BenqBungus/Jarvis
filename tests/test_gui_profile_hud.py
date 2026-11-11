"""Profiles on the HUD: header switcher, permission levels and "Jarvis
noticed" habit cards (MainWindow), the tray's profile menu, and Settings
editing the active profile."""
from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QLineEdit, QToolButton

from jarvis.gui.main_window import MainWindow
from jarvis.gui.settings_page import SettingsPage
from jarvis.gui.tray import TrayIcon
from jarvis.personality import suggestion_line
from jarvis.user_settings import JarvisSettings

BERK = {"id": "berk", "display_name": "Берк", "permission_level": "adult", "role_packs": ["gamer"],
        "personality": {"preset": "jarvis", "address_as": "sir"}}
ANI = {"id": "ani", "display_name": "Ани", "permission_level": "kid", "role_packs": ["student"],
       "personality": {"preset": "tutor"}}
GUEST = {"id": "guest", "display_name": "Гост", "permission_level": "guest", "role_packs": []}
HABITS = [
    {"id": "h1", "title": "Gaming evening", "detail": "You open Discord and Steam most days around 20:00.",
     "evidence": "seen 6 times in 7 days"},
    {"id": "h2", "title": "Study volume", "detail": "You set the volume to 30 when studying."},
    {"id": "h1", "title": "duplicate"},
    {"title": "no id"},
    {"id": "h3", "title": "Morning news"},
    {"id": "h4", "title": "Fourth"},
]


@pytest.fixture
def window(qapp):
    widget = MainWindow()
    widget.show()
    qapp.processEvents()
    yield widget
    widget.hide()
    widget.deleteLater()
    qapp.processEvents()


def _buttons(widget, text):
    return [button for button in widget.findChildren(QToolButton) if button.text() == text]


def test_no_profile_ui_until_a_profile_is_set(window):
    assert not window._profile_button.isVisible()
    assert not window._level_badge.isVisible()
    assert window._settings_button.isEnabled()


def test_set_profile_shows_the_avatar_and_follows_the_profile(window):
    window.set_profiles([BERK, ANI, GUEST])
    window.set_profile(BERK)
    assert window._profile_button.isVisible()
    assert "Берк" in window._profile_button.toolTip()
    assert list(window._pack_cards) == ["gamer"]
    window.set_profile(GUEST)
    assert window._pack_cards == {}
    assert window._personal_column.isVisible()  # the Guest banner still shows
    assert not window.findChildren(QLineEdit)  # no editor or PIN field is built up front


def test_kid_and_guest_levels_badge_lock_settings_and_explain_blocks(window, qapp):
    window.set_profiles([BERK, ANI])
    window.set_profile(ANI)
    assert window._level_badge.isVisible() and window._level_badge.text() == "KID MODE"
    assert window._level_banner.isVisible() and window._level_banner_switch.isVisibleTo(window)
    assert not window._settings_button.isEnabled()
    window._show_settings()
    assert window._transcript_tone == "blocked"
    assert window._feedback_text.startswith("Not in Kid mode")
    window.show_permission_block("Shutdown is not available.")
    assert window._feedback_text == "Not in Kid mode: Shutdown is not available."
    assert not window._feedback_error
    window.set_profile(BERK)
    assert not window._level_badge.isVisible() and not window._level_banner.isVisible()
    assert window._settings_button.isEnabled()


def test_header_still_fits_the_smallest_window(window, qapp):
    window.set_profiles([BERK, ANI])
    window.set_profile(ANI)
    window.resize(900, 660)
    qapp.processEvents()
    assert window.width() == 900


def test_profile_menu_switches_edits_and_adds(window):
    window.set_profiles([BERK, ANI, GUEST])
    window.set_profile(BERK)
    switches, editors = [], []
    window.profile_switch_requested.connect(switches.append)
    window.profile_editor_requested.connect(editors.append)
    window._build_profile_menu()
    actions = {action.text(): action for action in window._profile_menu.actions() if action.text()}
    assert {"Ани", "Гост", "Edit profile…", "Add profile…"} <= set(actions)
    assert "Берк" not in actions  # the active one is the menu's header
    actions["Ани"].trigger()
    actions["Edit profile…"].trigger()
    actions["Add profile…"].trigger()
    assert switches == ["ani"] and editors == ["berk", ""]
    window.set_profile(ANI)
    window._build_profile_menu()
    assert "Add profile…" not in [action.text() for action in window._profile_menu.actions()]


def test_open_profile_editor_limits_what_a_kid_can_change(window):
    window.set_profile(ANI)
    dialog = window.open_profile_editor(ANI)
    assert not dialog.level_cards["kid"].isEnabled()
    dialog.reject()


def test_habit_cards_answer_once_and_disappear(window):
    window.show_habit_suggestions(HABITS)
    assert list(window._habit_cards) == ["h1", "h2", "h3"]  # deduped, id required, three at most
    answers = []
    window.habit_accepted.connect(lambda habit: answers.append(("accepted", habit)))
    window.habit_snoozed.connect(lambda habit: answers.append(("snoozed", habit)))
    window.habit_dismissed.connect(lambda habit: answers.append(("dismissed", habit)))
    _buttons(window._habit_cards["h1"], "Set it up")[0].click()
    _buttons(window._habit_cards["h2"], "Later")[0].click()
    _buttons(window._habit_cards["h3"], "Don't suggest")[0].click()
    assert answers == [("accepted", "h1"), ("snoozed", "h2"), ("dismissed", "h3")]
    assert window._habit_cards == {}
    assert not window._personal_column.isVisible()


def test_habits_are_offered_out_loud_in_both_languages():
    habit = {"detail": "You open Discord and Steam most days around 20:00",
             "detail_bg": "Отваряш Discord и Steam почти всеки ден около 20:00."}
    assert suggestion_line(habit, "en") == ("I noticed something: You open Discord and Steam most days around 20:00. "
                                            "Want me to set that up?")
    assert suggestion_line(habit, "bg").startswith("Забелязах нещо: Отваряш Discord")
    assert suggestion_line({"detail": "X."}, "bg") == "Забелязах нещо: X. Да го настроя ли?"


def test_settings_edit_the_active_profile_instead_of_the_settings(window, qapp, tmp_path):
    settings = JarvisSettings(personalization={"role_packs": ["business"], "address_name": "Берк"})
    page = SettingsPage(settings, settings_path=tmp_path / "settings.json")
    window.set_settings_widget(page)
    assert list(window._pack_cards) == ["business"]
    window.set_profile(BERK)
    assert page._pack_switches["gamer"].isChecked() and not page._pack_switches["business"].isChecked()
    assert page._address_input.text() == "sir"
    assert page._profile_notes[0].isVisibleTo(page)
    changes = []
    page.profile_changes_requested.connect(lambda profile_id, data: changes.append((profile_id, data)))
    page._pack_switches["student"].setChecked(True)
    page._preset_buttons["coach"].click()
    page._on_save()
    profile_id, data = changes[-1]
    assert profile_id == "berk" and data["role_packs"] == ["gamer", "student"]
    assert data["personality"]["preset"] == "coach" and data["personality"]["address_as"] == "sir"
    stored = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["personalization"]
    assert stored == {"role_packs": ["business"], "address_name": "Берк"}  # untouched
    assert list(window._pack_cards) == ["gamer", "student"]


def test_tray_lists_profiles_and_locks_settings_for_kids(window, qapp):
    tray = TrayIcon(window)
    tray._sync_menu()
    assert not tray._profiles_action.isVisible()
    window.set_profiles([BERK, ANI])
    window.set_profile(BERK)
    switches = []
    window.profile_switch_requested.connect(switches.append)
    tray._sync_menu()
    assert tray._profiles_action.isVisible()
    actions = {action.text(): action for action in tray._profiles_menu.actions()}
    assert actions["Берк"].isChecked() and not actions["Ани"].isChecked()
    actions["Ани"].trigger()
    assert switches == ["ani"]
    assert tray._settings_action.isEnabled()
    window.set_profile(ANI)
    tray._sync_menu()
    assert not tray._settings_action.isEnabled()
