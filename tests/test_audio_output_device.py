from __future__ import annotations

import sys
from types import SimpleNamespace

from jarvis.audio import output_device


class _FakeSoundDevice:
    streams: list[object] = []

    @staticmethod
    def query_hostapis():
        return [{"name": "MME"}, {"name": "WASAPI"}]

    @staticmethod
    def query_devices():
        return [
            {"name": "Mic", "hostapi": 0, "max_output_channels": 0},
            {"name": "Speakers", "hostapi": 0, "max_output_channels": 2},
            {"name": "SteelSeries Sonar - Gaming", "hostapi": 1, "max_output_channels": 8},
        ]

    class RawOutputStream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.written = b""
            _FakeSoundDevice.streams.append(self)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def write(self, data: bytes) -> None:
            self.written += data


def test_list_output_devices_filters_inputs_and_formats_labels(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSoundDevice)

    devices = output_device.list_output_devices()

    assert [device.index for device in devices] == [1, 2]
    assert devices[1].label == "2: SteelSeries Sonar - Gaming (WASAPI)"


def test_resolve_output_device_accepts_index_prefix(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSoundDevice)

    assert output_device.resolve_output_device("2: SteelSeries Sonar - Gaming (WASAPI)") == 2


def test_resolve_output_device_accepts_substring(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSoundDevice)

    assert output_device.resolve_output_device("sonar") == 2


def test_configured_output_device_reads_environment(monkeypatch):
    monkeypatch.setenv("JARVIS_AUDIO_OUTPUT_DEVICE", "2")

    assert output_device.configured_output_device() == 2


def test_play_test_tone_uses_resolved_output_device(monkeypatch):
    _FakeSoundDevice.streams = []
    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSoundDevice)

    assert output_device.play_test_tone(device="2: SteelSeries Sonar - Gaming (WASAPI)") is True

    stream = _FakeSoundDevice.streams[0]
    assert stream.kwargs["device"] == 2
    assert stream.kwargs["channels"] == 2
    assert len(stream.written) > 0


def test_saved_device_label_survives_windows_device_renumbering(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSoundDevice)
    assert output_device.resolve_output_device("17: SteelSeries Sonar - Gaming (WASAPI)") == 2


def test_disconnected_named_speaker_does_not_route_to_another_device(monkeypatch):
    import pytest
    monkeypatch.setitem(sys.modules, "sounddevice", _FakeSoundDevice)
    with pytest.raises(ValueError, match="disconnected"):
        output_device.resolve_output_device("2: Old Headphones (WASAPI)")
