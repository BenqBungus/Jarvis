from __future__ import annotations

from jarvis.audio import text_to_speech
from jarvis.audio.text_to_speech import OPENAI_TTS_VOICES, TextToSpeech


def test_disabled_tts_is_a_safe_noop():
    tts = TextToSpeech(enabled=False)
    assert tts.enabled is False
    assert tts.speak("hello") is False
    assert tts.describe_voices() == []


def test_disabled_tts_ignores_empty_text():
    tts = TextToSpeech(enabled=False)
    assert tts.speak("") is False
    assert tts.speak("   ") is False


def test_enabled_tts_degrades_gracefully_without_pyttsx3(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "pyttsx3", None)
    tts = TextToSpeech(enabled=True, provider="windows")
    assert tts.enabled is False
    assert tts.speak("test") is False


def test_openai_tts_does_not_require_pyttsx3_when_key_is_available(monkeypatch):
    import sys

    calls = []

    def fake_speak_with_openai(text, model, voice, instructions, client=None, on_error=None):
        calls.append((text, model, voice, instructions))
        return True

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "pyttsx3", None)
    monkeypatch.setattr(text_to_speech, "speak_with_openai", fake_speak_with_openai)
    tts = TextToSpeech(enabled=True, provider="openai", openai_model="tts-test", openai_voice="cedar")

    assert tts.enabled is True
    assert tts.speak("hello") is True
    assert calls[0][0] == "hello"
    assert calls[0][1] == "tts-test"
    assert calls[0][2] == "cedar"


def test_openai_tts_is_disabled_when_key_and_pyttsx3_are_both_missing(monkeypatch):
    import sys

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "pyttsx3", None)

    tts = TextToSpeech(enabled=True, provider="openai")

    assert tts.enabled is False
    assert tts.speak("hello") is False


def test_openai_tts_is_disabled_when_key_is_missing_and_pyttsx3_init_fails(monkeypatch):
    import sys
    import types

    def _broken_init():
        raise RuntimeError("SAPI5 init failed")

    fake_pyttsx3 = types.SimpleNamespace(init=_broken_init)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setitem(sys.modules, "pyttsx3", fake_pyttsx3)

    tts = TextToSpeech(enabled=True, provider="openai")

    assert tts.enabled is False
    assert tts.speak("hello") is False


def test_openai_tts_falls_back_to_windows_engine_when_openai_playback_fails(monkeypatch):
    import sys

    class _FakeEngine:
        def __init__(self):
            self.spoken: list[str] = []

        def getProperty(self, name):
            if name == "voices":
                return []
            return None

        def setProperty(self, *_args):
            pass

        def say(self, text):
            self.spoken.append(text)

        def runAndWait(self):
            pass

    fake_engine = _FakeEngine()
    fake_pyttsx3 = type("FakePyttsx3", (), {"init": staticmethod(lambda: fake_engine)})
    monkeypatch.setenv("OPENAI_API_KEY", "invalid-test-key")
    monkeypatch.setitem(sys.modules, "pyttsx3", fake_pyttsx3)
    monkeypatch.setattr(text_to_speech, "speak_with_openai", lambda *args, **kwargs: False)

    tts = TextToSpeech(enabled=True, provider="openai")

    assert tts.speak("hello") is True
    assert fake_engine.spoken == ["hello"]


def test_openai_voice_list_includes_current_best_quality_defaults():
    tts = TextToSpeech(enabled=False)
    voices = tts.describe_openai_voices()

    assert "cedar" in OPENAI_TTS_VOICES
    assert "marin" in OPENAI_TTS_VOICES
    assert any(line.startswith("cedar | OpenAI") for line in voices)


def test_status_summary_reports_openai_voice_configuration(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(text_to_speech, "ensure_openai_api_key_visible", lambda: False)
    tts = TextToSpeech(enabled=False, provider="openai", openai_model="gpt-4o-mini-tts", openai_voice="cedar")

    status = tts.status_summary()

    assert status["enabled"] is False
    assert status["provider"] == "openai"
    assert status["openai_key_present"] is False
    assert status["openai_model"] == "gpt-4o-mini-tts"
    assert status["openai_voice"] == "cedar"
