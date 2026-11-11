from __future__ import annotations

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QStyle, QSystemTrayIcon

from .voice_core import AURORA, BASE_STYLE, glyph_icon

# Idle wears the brand gradient; every other state is a single, clearly
# different hue so it still reads at 16px in the notification area.
_STATE_COLORS = {
    "idle": QColor(AURORA["accent"]),
    "listening": QColor(AURORA["success"]),
    "processing": QColor(AURORA["accent_2_light"]),
    "unclear": QColor(AURORA["warning"]),
    "warning": QColor(AURORA["danger"]),
}
# Keyed by color name: the idle cyan shades into violet, others into themselves.
_GRADIENT_ENDS = {QColor(AURORA["accent"]).name(): QColor(AURORA["accent_2"])}

# "unclear" (speech heard but empty/too short to be a command) is a voice
# state like idle/listening/processing, not an alert like "warning" -- it
# naturally reverts on the next loop iteration's "listening" emission, no
# timer needed the way raise_warning()/clear_warning() need one.
_VOICE_STATES = ("idle", "listening", "processing", "unclear")


def _draw_orb(color: QColor, end: QColor, size: int) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    center = QPointF(size / 2, size / 2)
    radius = size * 0.46
    disc = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
    gradient = QLinearGradient(disc.topLeft(), disc.bottomRight())
    gradient.setColorAt(0.0, color.lighter(115))
    gradient.setColorAt(1.0, end)
    painter.setBrush(gradient)
    painter.drawEllipse(disc)
    painter.setBrush(QColor(AURORA["bg"]))
    painter.drawEllipse(center, radius * 0.5, radius * 0.5)
    painter.setBrush(color.lighter(135))
    painter.drawEllipse(center, max(1.0, radius * 0.2), max(1.0, radius * 0.2))
    painter.end()
    return pixmap


def _make_state_icon(color: QColor, size: int = 64) -> QIcon:
    """The Jarvis orb mark tinted per state, drawn natively at each common
    tray size (no icon asset files; small sizes stay crisp, not downscaled)."""
    end = _GRADIENT_ENDS.get(color.name(), color.darker(135))
    icon = QIcon()
    for pixels in sorted({16, 20, 24, 32, 48, size}):
        icon.addPixmap(_draw_orb(color, end, pixels))
    return icon


class TrayIcon(QObject):
    """QSystemTrayIcon wrapper: 5 procedurally-drawn status-orb icons, a
    context menu, and native toast notifications.

    Two independent, overlapping pieces of state feed the icon: the voice
    worker's mutually-exclusive idle/listening/processing state, and an
    orthogonal "warning" flag raised by monitor alerts (which can fire while
    voice is in any state). Warning always wins the icon while active, and
    auto-reverts a few seconds after the last warning so it never gets stuck
    on screen once alerts stop.
    """

    run_wizard_requested = Signal()

    def __init__(self, main_window, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._main_window = main_window
        self._icons = {name: _make_state_icon(color) for name, color in _STATE_COLORS.items()}
        self._voice_state = "idle"
        self._warning_active = False

        self._icon = QSystemTrayIcon(self._icons["idle"])
        self._icon.setToolTip("Jarvis: idle")
        self._icon.activated.connect(self._on_activated)

        self._warning_timer = QTimer(self)
        self._warning_timer.setSingleShot(True)
        self._warning_timer.timeout.connect(self.clear_warning)

        self._menu = QMenu()
        self._menu.setStyleSheet(BASE_STYLE)  # the dark menu of the rest of the app
        self._build_menu()
        self._icon.setContextMenu(self._menu)

    def _build_menu(self) -> None:
        show_action = QAction("Show Jarvis", self._menu)
        show_action.triggered.connect(self._show_window)
        self._menu.addAction(show_action)
        self._menu.addSeparator()
        # Quick controls go through the main window's own buttons, so the tray
        # follows exactly the same checks as clicking them in the HUD.
        self._call_action = QAction("Start live call", self._menu)
        self._call_action.triggered.connect(lambda: self._click("_voice_button"))
        self._mute_action = QAction("Mute microphone", self._menu)
        self._mute_action.triggered.connect(lambda: self._click("_mute_button"))
        overlay_action = QAction("Command overlay", self._menu)
        overlay_action.triggered.connect(self._open_overlay)
        self._settings_action = QAction("Settings", self._menu)
        self._settings_action.triggered.connect(self._open_settings)
        self._passwords_action = QAction("Passwords", self._menu)
        self._passwords_action.triggered.connect(self._open_passwords)
        for action in (self._call_action, self._mute_action, overlay_action, self._settings_action,
                       self._passwords_action):
            self._menu.addAction(action)
        # Filled from the window's profiles on open (MainWindow.set_profiles).
        self._profiles_menu = QMenu("Switch profile", self._menu)
        self._profiles_action = self._menu.addMenu(self._profiles_menu)
        self._menu.addSeparator()
        wizard_action = QAction("Run Setup Wizard...", self._menu)
        wizard_action.triggered.connect(self.run_wizard_requested.emit)
        self._menu.addAction(wizard_action)
        self._menu.addSeparator()
        quit_action = QAction("Quit", self._menu)
        quit_action.triggered.connect(self._quit)
        self._menu.addAction(quit_action)
        style, pixmaps = self._menu.style(), QStyle.StandardPixmap
        for action, glyph in ((show_action, "apps"), (self._call_action, "mic"), (self._mute_action, "mic_off"),
                              (overlay_action, "keyboard"), (self._settings_action, "settings"),
                              (self._passwords_action, "lock"),
                              (self._profiles_action, "person"), (wizard_action, "sparkle"), (quit_action, "power")):
            action.setIcon(glyph_icon(glyph, pixmaps.SP_FileDialogInfoView, style, size=16))
        self._menu.aboutToShow.connect(self._sync_menu)
        self._sync_menu()

    def _sync_menu(self) -> None:
        """Label/enable the quick controls from the window's current state."""
        window = self._main_window
        live = bool(getattr(window, "_realtime_active", False))
        call_button = getattr(window, "_voice_button", None)
        self._call_action.setText("End live call" if live else "Start live call")
        self._call_action.setEnabled(call_button is not None and call_button.isEnabled())
        mute_button = getattr(window, "_mute_button", None)
        self._mute_action.setText("Unmute microphone" if getattr(window, "_input_muted", False) else "Mute microphone")
        self._mute_action.setEnabled(live and mute_button is not None and mute_button.isEnabled())
        adult = getattr(window, "_permission_level", "adult") == "adult"
        self._settings_action.setEnabled(adult)
        self._passwords_action.setEnabled(adult and hasattr(window, "passwords_requested"))
        self._sync_profiles_menu()

    def _sync_profiles_menu(self) -> None:
        window = self._main_window
        profiles = list(getattr(window, "_profiles", []) or [])
        active = str((getattr(window, "_profile", {}) or {}).get("id") or "")
        self._profiles_menu.clear()
        for profile in profiles:
            profile_id = str(profile.get("id") or "")
            action = self._profiles_menu.addAction(str(profile.get("display_name") or profile_id))
            action.setCheckable(True)
            action.setChecked(profile_id == active)
            action.triggered.connect(lambda _checked=False, value=profile_id: self._switch_profile(value))
        self._profiles_action.setVisible(len(profiles) > 1)

    def _switch_profile(self, profile_id: str) -> None:
        request = getattr(self._main_window, "_request_profile_switch", None)
        if callable(request):
            request(profile_id)

    def _click(self, name: str) -> None:
        button = getattr(self._main_window, name, None)
        if button is not None and button.isEnabled():
            button.click()

    def _open_overlay(self) -> None:
        signal = getattr(self._main_window, "overlay_requested", None)
        if signal is not None:
            signal.emit()

    def _open_passwords(self) -> None:
        self._show_window()
        signal = getattr(self._main_window, "passwords_requested", None)
        if signal is not None:
            signal.emit()

    def _open_settings(self) -> None:
        self._show_window()
        show_settings = getattr(self._main_window, "_show_settings", None)
        if callable(show_settings):
            show_settings()

    def _show_window(self) -> None:
        self._main_window.show()
        self._main_window.raise_()
        self._main_window.activateWindow()

    def _quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()

    def show(self) -> None:
        self._icon.show()

    def set_voice_state(self, state: str) -> None:
        if state not in _VOICE_STATES:
            raise ValueError(f"Unknown voice state: {state!r}")
        self._voice_state = state
        self._refresh_icon()

    def raise_warning(self, timeout_ms: int = 5000) -> None:
        self._warning_active = True
        self._refresh_icon()
        self._warning_timer.start(timeout_ms)

    def clear_warning(self) -> None:
        self._warning_active = False
        self._warning_timer.stop()
        self._refresh_icon()

    def current_state(self) -> str:
        return "warning" if self._warning_active else self._voice_state

    def _refresh_icon(self) -> None:
        current = self.current_state()
        self._icon.setIcon(self._icons[current])
        self._icon.setToolTip(f"Jarvis: {current}")

    def notify(self, title: str, message: str, category: str = "info", timeout_ms: int = 8000) -> None:
        icon = {
            "warning": QSystemTrayIcon.MessageIcon.Warning,
            "critical": QSystemTrayIcon.MessageIcon.Critical,
        }.get(category, QSystemTrayIcon.MessageIcon.Information)
        self._icon.showMessage(title, message, icon, timeout_ms)
