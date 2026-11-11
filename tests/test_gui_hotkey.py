from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes

from jarvis.gui.hotkey import HotkeyManager, _HOTKEY_ID, WM_HOTKEY


def _synthetic_message_address(message: int, wparam: int) -> int:
    """Builds a real ctypes.wintypes.MSG in memory and returns its address,
    the same shape nativeEventFilter receives from a real Win32 message
    loop -- lets us test the WM_HOTKEY-detection logic without a real OS
    keypress, which headless/offscreen test runs can't deliver anyway."""
    msg = wintypes.MSG()
    msg.message = message
    msg.wParam = wparam
    # Keep the struct alive by returning it alongside the address -- ctypes
    # doesn't keep a reference once the caller only holds an int.
    return msg, ctypes.addressof(msg)


def test_native_event_filter_emits_on_matching_wm_hotkey(qapp):
    manager = HotkeyManager()
    received = []
    manager.hotkey_pressed.connect(lambda: received.append(True))

    msg, address = _synthetic_message_address(WM_HOTKEY, _HOTKEY_ID)
    result = manager.nativeEventFilter(b"windows_generic_MSG", address)

    assert received == [True]
    assert result == (False, 0)  # never claims to have handled the message


def test_native_event_filter_ignores_non_hotkey_messages(qapp):
    manager = HotkeyManager()
    received = []
    manager.hotkey_pressed.connect(lambda: received.append(True))

    msg, address = _synthetic_message_address(0x0201, _HOTKEY_ID)  # WM_LBUTTONDOWN
    manager.nativeEventFilter(b"windows_generic_MSG", address)

    assert received == []


def test_native_event_filter_ignores_hotkey_id_mismatch(qapp):
    # Defensive: only our own registered ID (1) should ever fire, even
    # though only one ID is ever registered in practice.
    manager = HotkeyManager()
    received = []
    manager.hotkey_pressed.connect(lambda: received.append(True))

    msg, address = _synthetic_message_address(WM_HOTKEY, wparam=99)
    manager.nativeEventFilter(b"windows_generic_MSG", address)

    assert received == []


def test_native_event_filter_does_not_raise_when_message_is_not_int_convertible(qapp):
    # A message value ctypes can't coerce to an address (TypeError/ValueError
    # from int(message)) must be caught, not propagate. NOTE: this is NOT
    # the same as an invalid-but-int-shaped address (e.g. 0) -- ctypes.
    # wintypes.MSG.from_address() dereferences raw memory with no bounds
    # checking, so a bad-but-well-formed address segfaults the whole
    # process (a hard access violation, not a catchable Python exception)
    # rather than raising. Verified empirically; not worth (or safely
    # possible to) unit test. In real use this is never a problem: Qt only
    # ever calls nativeEventFilter with the address of a message it just
    # received from a live Win32 message loop, which is always valid.
    manager = HotkeyManager()
    result = manager.nativeEventFilter(b"windows_generic_MSG", object())
    assert result == (False, 0)


def test_starts_unregistered():
    manager = HotkeyManager()
    assert manager.registered is False


def test_register_and_unregister_round_trip_for_real():
    # Real Win32 call, not mocked -- low-risk (register then immediately
    # unregister within the same test) and the only way to actually verify
    # the ctypes signature/argument types are correct for this Python/OS.
    manager = HotkeyManager()
    try:
        assert manager.register() is True
        assert manager.registered is True
    finally:
        manager.unregister()
    assert manager.registered is False


def test_unregister_before_register_is_a_safe_noop():
    manager = HotkeyManager()
    manager.unregister()  # must not raise
    assert manager.registered is False


def test_register_twice_on_the_same_manager_is_reported_as_still_registered():
    # A second RegisterHotKey call for the same (thread, id) fails at the
    # Win32 level -- but the manager was already successfully registered
    # from the first call, so .registered must stay True either way; it
    # must not flip back to False just because a redundant call failed.
    manager = HotkeyManager()
    try:
        assert manager.register() is True
        manager.register()  # redundant; Win32 will reject it, that's fine
        assert manager.registered is True
    finally:
        manager.unregister()


def test_alt_space_has_its_own_registration_and_does_not_trigger_ctrl_space(qapp):
    from jarvis.gui.hotkey import MOD_ALT, MOD_NOREPEAT, VK_SPACE

    calls = []

    class User32:
        def RegisterHotKey(self, *args):
            calls.append(("register", args))
            return True

        def UnregisterHotKey(self, *args):
            calls.append(("unregister", args))

    alt = HotkeyManager(modifiers=MOD_ALT, hotkey_id=2, label="Alt+Space")
    alt._user32 = User32()
    ctrl = HotkeyManager()
    pressed = []
    alt.hotkey_pressed.connect(lambda: pressed.append("alt"))
    ctrl.hotkey_pressed.connect(lambda: pressed.append("ctrl"))
    assert alt.register()
    msg, address = _synthetic_message_address(WM_HOTKEY, 2)
    alt.nativeEventFilter(b"windows_generic_MSG", address)
    ctrl.nativeEventFilter(b"windows_generic_MSG", address)
    alt.unregister()
    assert pressed == ["alt"]
    assert calls == [("register", (None, 2, MOD_ALT | MOD_NOREPEAT, VK_SPACE)), ("unregister", (None, 2))]
