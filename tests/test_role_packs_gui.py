"""Role pack cards on the HUD (MainWindow.set_role_packs): quick actions,
the Gamer readiness line, the Student focus timer and where the cards sit."""
from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QLabel, QToolButton

from jarvis.gui.main_window import MainWindow, _FocusTimer, _gamer_verdict
from jarvis.role_packs import PACKS


@pytest.fixture
def window(qapp):
    widget = MainWindow()
    widget.show()
    qapp.processEvents()
    yield widget
    widget.hide()
    widget.deleteLater()
    qapp.processEvents()


def _chips(card) -> dict[str, QToolButton]:
    return {button.text(): button for button in card.findChildren(QToolButton)
            if button.property("role") == "chip"}


def test_no_cards_until_packs_are_set_and_unknown_ids_are_ignored(window):
    assert window._pack_cards == {}
    assert not window._personal_column.isVisible()
    window.set_role_packs(["business", "pirate", "gamer"])
    assert list(window._pack_cards) == ["gamer", "business"]  # PACKS order
    window.set_role_packs([])
    assert window._pack_cards == {}
    assert not window._personal_column.isVisible()
    assert not window._personal_scroll.isVisible()


def test_every_quick_action_is_a_chip_that_sends_its_command_or_signal(window):
    window.set_role_packs(list(PACKS))
    commands, signals = [], []
    window.command_submitted.connect(lambda text, source: commands.append((text, source)))
    window.screen_chat_requested.connect(lambda: signals.append("screen_chat_requested"))
    window.voice_diagnostics_requested.connect(lambda: signals.append("voice_diagnostics_requested"))
    for pack_id, pack in PACKS.items():
        chips = _chips(window._pack_cards[pack_id])
        for action in pack.quick_actions:
            chips[action.label].click()
            if action.command:
                assert commands[-1] == (action.command, "button")
            else:
                assert signals[-1] == action.signal


def test_cards_never_use_labels_the_main_surface_forbids(window):
    window.set_role_packs(list(PACKS))
    labels = {label.text() for label in window.findChildren(QLabel)}
    assert not {"Conversation", "Quick actions", "Modes", "Tasks", "Tools", "Memory"} & labels
    assert "GAMER PACK" in labels


@pytest.mark.parametrize(("width", "wide"), [(900, False), (1200, False), (1360, True), (1920, True)])
def test_cards_get_their_own_column_only_when_the_window_is_wide(window, qapp, width, wide):
    window.set_role_packs(["gamer", "student"])
    window.resize(width, 850 if width < 1900 else 1080)
    qapp.processEvents()
    assert window._personal_scroll.isVisible() is wide
    in_status_column = window._status_layout.indexOf(window._personal_column) >= 0
    assert in_status_column is (not wide)
    assert window._personal_column.isVisible()
    for widget in (window._core, window._voice_button, window._voice_transcript_label):
        origin = widget.mapTo(window, QPoint(0, 0))
        assert window.rect().contains(origin + QPoint(widget.width() - 1, widget.height() - 1))
    if wide:
        assert window._voice_transcript_label.width() >= 560


def test_long_feedback_is_elided_again_when_the_column_appears(window, qapp):
    window.resize(1360, 850)
    qapp.processEvents()
    window.show_feedback("W" * 3000)
    window.set_role_packs(["gamer"])
    qapp.processEvents()
    label = window._voice_transcript_label
    assert label.fontMetrics().horizontalAdvance(label.text()) <= label.width()


def test_cards_keep_their_natural_height(window, qapp):
    window.resize(1360, 850)
    window.set_permission_level("adult")  # places the still-empty column first, as set_profile does
    window.set_role_packs(["gamer"])
    window.show_habit_suggestions([{"id": "h1", "title": "Gaming evening", "detail": "Discord and Steam at 20:00."}])
    qapp.processEvents()
    for card in (window._pack_cards["gamer"], window._habit_cards["h1"]):
        assert card.height() <= card.layout().heightForWidth(card.width()) + 2


def test_switching_between_layouts_keeps_the_same_cards(window, qapp):
    window.set_role_packs(["gamer"])
    card = window._pack_cards["gamer"]
    for width in (1400, 950, 1500):
        window.resize(width, 850)
        qapp.processEvents()
        assert window._pack_cards["gamer"] is card
        assert card.isVisible()


def test_gamer_card_reads_the_dashboard(window):
    window.set_role_packs(["gamer"])
    dot, headline, detail = window._gamer_status
    assert headline.text() == "Waiting for readings"
    window.update_dashboard("cpu", "23%")
    window.update_dashboard("gpu", "41% (64C)")
    window.update_dashboard("cpu_temperature", "58C")
    assert headline.text() == "Game ready"
    assert detail.text() == "CPU 23%  ·  GPU 41%  ·  64°C"
    window.update_dashboard("gpu", "97% (91C)")
    assert headline.text() == "Running hot · 91°C"


@pytest.mark.parametrize(("readings", "headline"), [
    ({}, "Waiting for readings"),
    ({"cpu": "unavailable", "gpu": "N/A (N/A)", "cpu_temperature": "sensor unavailable"}, "Waiting for readings"),
    ({"cpu": "12%", "battery": "64% (on battery)"}, "On battery power"),
    ({"cpu": "12%", "battery": "64% (charging)"}, "Game ready"),
    ({"cpu": "95%"}, "Heavy background load"),
    ({"memory": "93% (14.9/16.0 GB)"}, "Heavy background load"),
    ({"cpu_temperature": "85C", "battery": "64% (on battery)"}, "Running hot · 85°C"),
])
def test_gamer_verdicts(readings, headline):
    assert _gamer_verdict(readings)[1] == headline


def test_focus_timer_runs_on_a_deadline_and_hands_over_to_a_break(qapp):
    timer = _FocusTimer()
    now = [1000.0]
    timer._clock = lambda: now[0]
    finished = []
    timer.phase_finished.connect(finished.append)
    assert timer._ring._text == "25:00" and timer._start_button.text() == "Start"
    timer._start_button.click()
    assert timer.running and timer._ticker.isActive()
    now[0] += 61.2
    timer._tick()
    assert timer._ring._text == "23:59"
    timer._start_button.click()  # pause
    assert not timer.running and not timer._ticker.isActive()
    assert timer._start_button.text() == "Resume"
    now[0] += 3600  # time while paused does not count
    timer._start_button.click()
    now[0] += 25 * 60
    timer._tick()
    assert finished == ["focus"]
    assert timer._phase == "break" and timer.running
    assert timer._phase_label.text() == "BREAK · 5 MIN"
    now[0] += 5 * 60
    timer._tick()
    assert finished == ["focus", "break"]
    assert timer._phase == "focus" and not timer.running
    assert timer._ring._text == "25:00" and timer._start_button.text() == "Start"


def test_focus_timer_survives_unrelated_pack_changes_and_tells_the_person(window):
    window.set_role_packs(["student"])
    timer = window._focus_timer
    timer.toggle()
    window.set_role_packs(["student", "gamer"])
    assert window._focus_timer is timer and timer.running
    timer.phase_finished.emit("focus")
    assert "break" in window._feedback_text
    window.set_role_packs(["gamer"])
    assert window._focus_timer is None
    assert not timer._ticker.isActive()
