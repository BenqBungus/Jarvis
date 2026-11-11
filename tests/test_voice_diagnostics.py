from __future__ import annotations

from jarvis.audio import diagnostics
from jarvis.audio.output_device import AudioOutputDevice
from jarvis.user_settings import JarvisSettings


class _FakeTts:
    def __init__(self, enabled=True):
        self.enabled = enabled

    def status_summary(self):
        return {
            "enabled": self.enabled,
            "provider": "openai",
            "openai_key_present": True,
            "openai_voice": "cedar",
            "windows_fallback_available": True,
        }


class _FakeStt:
    def __init__(self):
        self.available = True
        self.provider = "openai"
        self.openai_model = "gpt-transcribe"
        self.languages = ("bg-BG", "en-US")


class _FakeRealtimeSession:
    def __init__(self, _config):
        pass

    def readiness(self):
        return {
            "ready": True,
            "missing": [],
            "model": "gpt-realtime-2.1",
            "voice": "cedar",
        }


def test_voice_diagnostics_reports_ready_setup(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(diagnostics, "TextToSpeech", _FakeTts)
    monkeypatch.setattr(diagnostics, "SpeechToText", _FakeStt)
    monkeypatch.setattr(diagnostics, "RealtimeVoiceSession", _FakeRealtimeSession)
    monkeypatch.setattr(
        diagnostics,
        "list_output_devices",
        lambda: [AudioOutputDevice(11, "Microsoft Sound Mapper - Output", "MME", 2)],
    )
    monkeypatch.setattr(diagnostics, "configured_output_device", lambda settings=None: "11")
    monkeypatch.setattr(diagnostics, "resolve_output_device", lambda device=None: 11)

    result = diagnostics.build_voice_diagnostics(JarvisSettings())

    assert result.ok
    assert "Voice Doctor" in result.message
    assert "Realtime: ready" in result.message
    assert "Microsoft Sound Mapper - Output" in result.message
    assert "explicit headset/speaker" in result.message
    assert result.metadata["voice_diagnostics"]["audio_output"]["resolved"] == 11


def test_voice_diagnostics_recommends_explicit_output_when_using_default(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(diagnostics, "TextToSpeech", _FakeTts)
    monkeypatch.setattr(diagnostics, "SpeechToText", _FakeStt)
    monkeypatch.setattr(diagnostics, "RealtimeVoiceSession", _FakeRealtimeSession)
    monkeypatch.setattr(
        diagnostics,
        "list_output_devices",
        lambda: [AudioOutputDevice(17, "SteelSeries Sonar - Gaming", "MME", 8)],
    )
    monkeypatch.setattr(diagnostics, "configured_output_device", lambda settings=None: None)
    monkeypatch.setattr(diagnostics, "resolve_output_device", lambda device=None: None)

    result = diagnostics.build_voice_diagnostics(JarvisSettings())

    assert result.ok
    assert "select your headset explicitly" in result.message
