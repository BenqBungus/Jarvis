from __future__ import annotations

from jarvis.gui.overlay import OverlayWidget


def test_starts_hidden(qapp):
    overlay = OverlayWidget()
    assert overlay.isVisible() is False


def test_starts_with_idle_label(qapp):
    overlay = OverlayWidget()
    assert overlay.current_state_text() == "Jarvis"


def test_set_state_updates_the_label(qapp):
    overlay = OverlayWidget()
    overlay.set_state("listening")
    assert overlay.current_state_text() == "Listening..."


def test_set_state_falls_back_to_the_raw_state_for_unknown_states(qapp):
    overlay = OverlayWidget()
    overlay.set_state("some_future_state")
    assert overlay.current_state_text() == "some_future_state"


def test_toggle_shows_when_hidden(qapp):
    overlay = OverlayWidget()
    overlay.toggle()
    assert overlay.isVisible() is True


def test_toggle_hides_when_visible(qapp):
    overlay = OverlayWidget()
    overlay.toggle()
    overlay.toggle()
    assert overlay.isVisible() is False


def test_toggle_does_not_raise_without_a_primary_screen(qapp, monkeypatch):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(QApplication, "primaryScreen", staticmethod(lambda: None))
    overlay = OverlayWidget()
    overlay.toggle()  # must not raise even if _reposition() can't find a screen
    assert overlay.isVisible() is True


def test_all_known_voice_states_have_a_distinct_label(qapp):
    overlay = OverlayWidget()
    labels = set()
    for state in ("idle", "listening", "processing", "unclear", "warning"):
        overlay.set_state(state)
        labels.add(overlay.current_state_text())
    assert len(labels) == 5
