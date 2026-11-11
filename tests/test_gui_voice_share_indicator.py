"""The screen-sharing indicator (gui/screen_sharing.py): clear states, drag to
move, double-click to re-center, and kept out of the frames Jarvis sends."""
from __future__ import annotations

import ctypes
import sys
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QGuiApplication, QMouseEvent

from jarvis.gui import screen_sharing
from jarvis.gui.screen_sharing import ScreenSharingIndicator
from jarvis.vision.sharing import ScreenSharing


@pytest.fixture
def indicator(qapp):
    ScreenSharingIndicator._saved_position = None
    sharing = ScreenSharing(Mock())
    widget = ScreenSharingIndicator(sharing)
    yield widget
    widget.shutdown()
    widget.deleteLater()
    ScreenSharingIndicator._saved_position = None


def _mouse(widget, kind, local, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton):
    local = QPointF(local)
    event = QMouseEvent(kind, local, QPointF(widget.mapToGlobal(local.toPoint())), button, buttons,
                        Qt.KeyboardModifier.NoModifier)
    QGuiApplication.sendEvent(widget, event)


def test_states_say_what_is_happening(indicator):
    sharing = indicator.sharing
    sharing.start()
    indicator.refresh()
    assert indicator.label.text() == "SCREEN SHARING  ·  READY" and "voice call" in indicator.detail.text()
    assert indicator.toolTip().startswith("Shared just now")
    sharing.mark_live(sharing.state()["session_id"])
    indicator.refresh()
    assert "LIVE" in indicator.label.text() and "during the voice call" in indicator.detail.text()
    indicator.stop_button.click()
    assert not sharing.state()["sharing"] and not indicator.isVisible()


def test_screen_chat_state(qapp):
    sharing = ScreenSharing(Mock(), chat_only=True)
    widget = ScreenSharingIndicator(sharing)
    sharing.start()
    widget.refresh()
    assert widget.label.text().startswith("SCREEN CHAT") and "per question" in widget.detail.text()
    widget.shutdown()
    widget.deleteLater()


def test_drag_moves_it_and_double_click_puts_it_back(indicator):
    indicator.sharing.start()
    indicator.refresh()
    home = indicator.pos()
    _mouse(indicator, QEvent.Type.MouseButtonPress, QPoint(60, 20))
    _mouse(indicator, QEvent.Type.MouseMove, QPoint(60, 140), button=Qt.MouseButton.NoButton)
    _mouse(indicator, QEvent.Type.MouseButtonRelease, QPoint(60, 140), buttons=Qt.MouseButton.NoButton)
    assert indicator.pos().y() > home.y()
    assert ScreenSharingIndicator._saved_position == indicator.pos()
    moved = indicator.pos()
    indicator.stop()
    indicator.sharing.start()
    indicator.refresh()
    assert indicator.pos() == moved  # remembered for the next share
    _mouse(indicator, QEvent.Type.MouseButtonDblClick, QPoint(60, 20))
    assert indicator.pos() == home and ScreenSharingIndicator._saved_position is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows display affinity")
def test_kept_out_of_screen_captures_on_windows(indicator, monkeypatch):
    calls = []
    monkeypatch.setattr(ctypes.windll.user32, "SetWindowDisplayAffinity", lambda hwnd, flag: calls.append(flag) or 1)
    screen_sharing._exclude_from_capture(indicator)
    assert calls == []  # offscreen test platform: nothing to do
    monkeypatch.setattr(screen_sharing.QGuiApplication, "platformName", staticmethod(lambda: "windows"))
    screen_sharing._exclude_from_capture(indicator)
    assert calls == [0x11]  # WDA_EXCLUDEFROMCAPTURE
