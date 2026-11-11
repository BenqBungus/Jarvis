from __future__ import annotations

import ctypes
import sys
from types import SimpleNamespace

import pytest

from jarvis.volume import get_master_volume_percent, set_master_volume_percent


@pytest.fixture
def audio(monkeypatch):
    events = []
    endpoint = SimpleNamespace(GetMasterVolumeLevelScalar=lambda: .37,
        SetMute=lambda *args: events.append(("mute", args)),
        SetMasterVolumeLevelScalar=lambda *args: events.append(("set", args)))
    com = SimpleNamespace(CoInitialize=lambda: events.append("init"), CoUninitialize=lambda: events.append("uninit"), CLSCTX_ALL=1)
    utilities = SimpleNamespace(GetSpeakers=lambda: SimpleNamespace(EndpointVolume=endpoint))
    interface = type("Interface", (ctypes.Structure,), {"_iid_": "interface"})
    monkeypatch.setitem(sys.modules, "comtypes", com)
    monkeypatch.setitem(sys.modules, "pycaw.pycaw", SimpleNamespace(AudioUtilities=utilities, IAudioEndpointVolume=interface))
    return endpoint, com, utilities, events


def test_new_pycaw_endpoint_volume_and_worker_com_lifetime(audio):
    endpoint, com, utilities, events = audio
    assert get_master_volume_percent() == 37
    set_master_volume_percent(30)
    assert events == ["init", "uninit", "init", ("mute", (0, None)), ("set", (.3, None)), "uninit"]


def test_legacy_activate_is_still_supported(audio, monkeypatch):
    endpoint, com, utilities, events = audio
    utilities.GetSpeakers = lambda: SimpleNamespace(Activate=lambda *args: "legacy-interface")
    monkeypatch.setattr(ctypes, "cast", lambda pointer, kind: endpoint)
    assert get_master_volume_percent() == 37
    assert events == ["init", "uninit"]


def test_missing_device_releases_com(audio):
    endpoint, com, utilities, events = audio
    utilities.GetSpeakers = lambda: None
    with pytest.raises(RuntimeError, match="No default"):
        get_master_volume_percent()
    assert events == ["init", "uninit"]


def test_existing_mta_apartment_is_not_uninitialized_by_us(audio):
    endpoint, com, utilities, events = audio
    error = OSError("Already MTA")
    error.winerror = -2147417850

    def already_initialized():
        raise error

    com.CoInitialize = already_initialized
    assert get_master_volume_percent() == 37
    assert not events


@pytest.mark.parametrize("value", [-1, 101, True, 3.4, "30"])
def test_invalid_percent_never_opens_audio_device(audio, value):
    with pytest.raises(ValueError):
        set_master_volume_percent(value)
    assert not audio[-1]
