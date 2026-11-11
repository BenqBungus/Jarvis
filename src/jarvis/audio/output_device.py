from __future__ import annotations

import logging
import math
import os
import struct
import wave
from dataclasses import dataclass
from pathlib import Path

from ..user_settings import JarvisSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AudioOutputDevice:
    index: int
    name: str
    hostapi: str
    channels: int

    @property
    def label(self) -> str:
        return f"{self.index}: {self.name} ({self.hostapi})"


def list_output_devices() -> list[AudioOutputDevice]:
    try:
        import sounddevice as sd
    except ImportError:
        return []

    try:
        hostapis = sd.query_hostapis()
        devices = sd.query_devices()
    except Exception as exc:  # pragma: no cover - depends on local audio drivers
        logger.warning("Could not query audio output devices: %s", exc)
        return []

    results: list[AudioOutputDevice] = []
    for index, device in enumerate(devices):
        channels = int(device.get("max_output_channels") or 0)
        if channels <= 0:
            continue
        hostapi_index = int(device.get("hostapi") or 0)
        hostapi = str(hostapis[hostapi_index].get("name", "audio")) if hostapi_index < len(hostapis) else "audio"
        results.append(
            AudioOutputDevice(
                index=index,
                name=str(device.get("name", f"Device {index}")),
                hostapi=hostapi,
                channels=channels,
            )
        )
    return results


_HEADPHONE_WORDS = ("headphone", "headset", "earphone", "earbud", "buds", "airpods", "hands-free", "handsfree")
_GENERIC_OUTPUTS = ("sound mapper", "primary sound", "default")


def output_name(device: int | str | None = None) -> str:
    """The name of the endpoint Jarvis plays through ("" when unknown). The
    generic MME/DirectSound mappers resolve to Windows' default output."""
    try:
        import sounddevice as sd

        index = resolve_output_device(device)
        info = sd.query_devices(index, "output") if index is not None else sd.query_devices(kind="output")
        name = str(info.get("name", ""))
        if any(word in name.lower() for word in _GENERIC_OUTPUTS):
            for api in sd.query_hostapis():
                default = int(api.get("default_output_device", -1))
                if "wasapi" in str(api.get("name", "")).lower() and default >= 0:
                    name = str(sd.query_devices(default).get("name", name))
                    break
        return name
    except Exception:  # no audio stack, unplugged device: treat as speakers
        return ""


def output_is_headphones(device: int | str | None = None) -> bool:
    """Best guess from the output's name: Windows calls wired ones
    "Headphones (...)" and Bluetooth ones usually carry Headset/Buds/AirPods."""
    name = output_name(device).lower()
    return any(word in name for word in _HEADPHONE_WORDS)


def configured_output_device(settings: JarvisSettings | None = None) -> int | str | None:
    raw = os.getenv("JARVIS_AUDIO_OUTPUT_DEVICE")
    if raw is None:
        settings = settings or JarvisSettings.load()
        raw = settings.openai.get("audio_output_device")
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text


def resolve_output_device(device: int | str | None = None) -> int | str | None:
    device = configured_output_device() if device is None else device
    if device is None:
        return None
    if isinstance(device, int):
        return device
    text = str(device).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        candidates = list_output_devices()
        prefix, separator, identity = text.partition(":")
        if separator and prefix.strip().isdigit():
            for candidate in candidates:
                if f"{candidate.name} ({candidate.hostapi})".casefold() == identity.strip().casefold():
                    return candidate.index
            raise ValueError("The saved speaker is disconnected. Select an available output in Settings.")
        lowered = text.lower()
        if lowered in {"default", "system default", "none"}:
            return None
        for candidate in candidates:
            if lowered in candidate.label.lower() or lowered in candidate.name.lower():
                return candidate.index
    return text


def play_wav_file(path: str | Path, *, device: int | str | None = None) -> bool:
    try:
        import sounddevice as sd
    except ImportError:
        return False

    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            sample_rate = wav.getframerate()
            frames = wav.readframes(wav.getnframes())
        dtype = _dtype_for_sample_width(sample_width)
        if dtype is None:
            logger.warning("Unsupported WAV sample width for playback: %s", sample_width)
            return False
        with sd.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype=dtype,
            device=resolve_output_device(device),
        ) as output_stream:
            output_stream.write(frames)
        return True
    except Exception as exc:  # pragma: no cover - depends on local audio drivers
        logger.warning("sounddevice WAV playback failed: %s", exc)
        return False


def play_test_tone(*, device: int | str | None = None, frequency: int = 660, duration: float = 0.6) -> bool:
    try:
        import sounddevice as sd
    except ImportError:
        return False

    sample_rate = 24000
    amplitude = 0.22
    frame_count = max(1, int(sample_rate * max(0.1, duration)))
    frames = bytearray()
    for index in range(frame_count):
        sample = int(amplitude * 32767 * math.sin(2 * math.pi * frequency * index / sample_rate))
        packed = struct.pack("<h", sample)
        frames.extend(packed)
        frames.extend(packed)

    try:
        with sd.RawOutputStream(
            samplerate=sample_rate,
            channels=2,
            dtype="int16",
            device=resolve_output_device(device),
        ) as output_stream:
            output_stream.write(bytes(frames))
        return True
    except Exception as exc:  # pragma: no cover - depends on local audio drivers
        logger.warning("sounddevice test tone failed: %s", exc)
        return False


def _dtype_for_sample_width(sample_width: int) -> str | None:
    if sample_width == 1:
        return "uint8"
    if sample_width == 2:
        return "int16"
    if sample_width == 4:
        return "int32"
    return None
