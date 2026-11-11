from __future__ import annotations

from contextlib import contextmanager


@contextmanager
def _endpoint_volume():
    from ctypes import POINTER, cast

    import comtypes
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    initialized = False
    try:
        comtypes.CoInitialize()
        initialized = True
    except Exception as exc:
        # An existing MTA apartment is usable too; do not uninitialize its owner's COM state.
        code = getattr(exc, "hresult", getattr(exc, "winerror", None))
        if code not in {-2147417850, 0x80010106}:  # RPC_E_CHANGED_MODE
            raise
    try:
        device = AudioUtilities.GetSpeakers()
        if device is None:
            raise RuntimeError("No default Windows audio output is available.")
        volume = getattr(device, "EndpointVolume", None)
        if volume is None:
            interface = device.Activate(IAudioEndpointVolume._iid_, comtypes.CLSCTX_ALL, None)
            volume = cast(interface, POINTER(IAudioEndpointVolume))
        yield volume
    finally:
        if initialized:
            comtypes.CoUninitialize()


def set_master_volume_percent(percent: int) -> None:
    if type(percent) is not int or not 0 <= percent <= 100:
        raise ValueError("Volume must be an integer between 0 and 100.")
    with _endpoint_volume() as volume:
        volume.SetMute(0, None)
        volume.SetMasterVolumeLevelScalar(percent / 100, None)


def get_master_volume_percent() -> int:
    with _endpoint_volume() as volume:
        return round(volume.GetMasterVolumeLevelScalar() * 100)
