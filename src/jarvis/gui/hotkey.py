from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
MOD_CONTROL = 0x0002
MOD_ALT = 0x0001
MOD_NOREPEAT = 0x4000  # without this, holding the key auto-repeats WM_HOTKEY
VK_SPACE = 0x20
_HOTKEY_ID = 1
_ERROR_HOTKEY_ALREADY_REGISTERED = 1409


class HotkeyManager(QObject, QAbstractNativeEventFilter):
    """Registers the global Ctrl+Space hotkey via Win32's RegisterHotKey
    (ctypes, no new dependency -- avoids the admin/AV baggage of packages
    like `keyboard`/`pynput`) and intercepts it inside Qt's own event loop
    via QAbstractNativeEventFilter, translating it into a Qt signal.

    Registers with hWnd=None deliberately: WM_HOTKEY is then posted to the
    *calling thread's* message queue (must be the Qt GUI thread, i.e.
    wherever QApplication.exec() runs) instead of any window's queue --
    this sidesteps needing a window handle at all, important since this is
    a tray app that may have zero visible windows at any given moment.
    """

    hotkey_pressed = Signal()

    def __init__(self, parent: QObject | None = None, *, modifiers: int = MOD_CONTROL,
                 hotkey_id: int = _HOTKEY_ID, label: str = "Ctrl+Space") -> None:
        QObject.__init__(self, parent)
        QAbstractNativeEventFilter.__init__(self)
        # use_last_error=True is required to get a reliable GetLastError()
        # afterward -- plain ctypes.windll.user32 does not guarantee this.
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._registered = False
        self._modifiers = modifiers
        self._hotkey_id = hotkey_id
        self._label = label

    def register(self) -> bool:
        if self._registered:
            return True
        ok = self._user32.RegisterHotKey(None, self._hotkey_id, self._modifiers | MOD_NOREPEAT, VK_SPACE)
        if not ok:
            error = ctypes.get_last_error()
            if error == _ERROR_HOTKEY_ALREADY_REGISTERED:
                logger.warning("%s is already bound by another application; hotkey disabled.", self._label)
            else:
                logger.warning("RegisterHotKey failed (error %s); hotkey disabled.", error)
            return False
        self._registered = True
        return True

    def unregister(self) -> None:
        if self._registered:
            self._user32.UnregisterHotKey(None, self._hotkey_id)
            self._registered = False

    @property
    def registered(self) -> bool:
        return self._registered

    def nativeEventFilter(self, eventType, message):  # noqa: N802 - Qt override signature
        # Runs for every native Windows message this app receives (mouse
        # moves, paint, timers), not just WM_HOTKEY -- must stay fast and
        # catch ordinary Python-level failures (e.g. a non-int-convertible
        # message). This does NOT guard against a genuinely invalid memory
        # address: ctypes.wintypes.MSG.from_address() dereferences raw
        # memory with no bounds checking, so a bad address is a hard access
        # violation (segfault), not a catchable exception. Not a real-world
        # risk: Qt only ever calls this with the address of a message it
        # just received from its own live Win32 message loop.
        try:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                self.hotkey_pressed.emit()
        except Exception:
            logger.exception("nativeEventFilter failed while checking WM_HOTKEY")
        return False, 0
