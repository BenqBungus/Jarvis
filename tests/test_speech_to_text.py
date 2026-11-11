from __future__ import annotations

from jarvis.audio.speech_to_text import RecognizedSpeech, recognize_with_fallback, recognize_with_openai


class _FakeUnknownValueError(Exception):
    pass


class _FakeRequestError(Exception):
    pass


class _FakeSrModule:
    UnknownValueError = _FakeUnknownValueError
    RequestError = _FakeRequestError


class _FakeRecognizer:
    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses

    def recognize_google(self, audio, language: str):
        response = self._responses.get(language)
        if response is None:
            raise _FakeUnknownValueError()
        if response == "__error__":
            raise _FakeRequestError("network down")
        return response


def test_returns_first_matching_language():
    recognizer = _FakeRecognizer({"bg-BG": "здравей jarvis"})
    result = recognize_with_fallback(object(), recognizer, _FakeSrModule, ("bg-BG", "en-US"))
    assert result == RecognizedSpeech("здравей jarvis", "bg-BG")


def test_falls_back_to_next_language_when_first_is_unrecognized():
    recognizer = _FakeRecognizer({"en-US": "hey jarvis"})
    result = recognize_with_fallback(object(), recognizer, _FakeSrModule, ("bg-BG", "en-US"))
    assert result == RecognizedSpeech("hey jarvis", "en-US")


def test_continues_past_request_error_to_next_language():
    recognizer = _FakeRecognizer({"bg-BG": "__error__", "en-US": "hey jarvis"})
    result = recognize_with_fallback(object(), recognizer, _FakeSrModule, ("bg-BG", "en-US"))
    assert result == RecognizedSpeech("hey jarvis", "en-US")


def test_returns_none_when_nothing_recognized_in_any_language():
    recognizer = _FakeRecognizer({})
    result = recognize_with_fallback(object(), recognizer, _FakeSrModule, ("bg-BG", "en-US"))
    assert result is None


def test_speech_to_text_reports_unavailable_without_dependency(monkeypatch):
    import sys

    from jarvis.audio.speech_to_text import SpeechToText

    # Force the `import speech_recognition` inside SpeechToText.__init__ to
    # fail regardless of whether the package happens to be installed in the
    # environment running the tests (None in sys.modules forces ImportError).
    monkeypatch.setitem(sys.modules, "speech_recognition", None)
    stt = SpeechToText()
    assert stt.available is False
    assert stt.listen_once() is None


class _FakeAudio:
    def get_wav_data(self) -> bytes:
        return b"RIFFfake"


class _FakeTranscription:
    text = "здравей jarvis отвори facebook"


class _FakeTranscriptions:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeTranscription()


class _FakeAudioApi:
    def __init__(self) -> None:
        self.transcriptions = _FakeTranscriptions()


class _FakeOpenAIClient:
    def __init__(self) -> None:
        self.audio = _FakeAudioApi()


def test_openai_transcription_returns_recognized_speech():
    client = _FakeOpenAIClient()
    result = recognize_with_openai(_FakeAudio(), model="gpt-transcribe", client=client)
    assert result == RecognizedSpeech("здравей jarvis отвори facebook", "bg-BG")
    assert client.audio.transcriptions.calls[0]["model"] == "gpt-transcribe"
    assert client.audio.transcriptions.calls[0]["extra_body"] == {"languages": ["en"]}
    assert "language" not in client.audio.transcriptions.calls[0]
    assert "conversation is in English" in client.audio.transcriptions.calls[0]["prompt"]


def test_default_google_recognition_uses_only_english():
    recognizer = _FakeRecognizer({"bg-BG": "wrong language", "en-US": "hello Jarvis"})
    result = recognize_with_fallback(object(), recognizer, _FakeSrModule)
    assert result == RecognizedSpeech("hello Jarvis", "en-US")


def test_legacy_file_transcription_uses_english_language_parameter():
    client = _FakeOpenAIClient()
    recognize_with_openai(_FakeAudio(), model="whisper-1", client=client)
    assert client.audio.transcriptions.calls[0]["language"] == "en"
    assert "extra_body" not in client.audio.transcriptions.calls[0]


def test_openai_transcription_for_bulgarian():
    client = _FakeOpenAIClient()
    recognize_with_openai(_FakeAudio(), model="gpt-transcribe", client=client, lang="bg")
    call = client.audio.transcriptions.calls[0]
    assert call["extra_body"] == {"languages": ["bg"]}
    assert "conversation is in Bulgarian" in call["prompt"]


def test_openai_transcription_for_auto_omits_the_language_hint_entirely():
    client = _FakeOpenAIClient()
    recognize_with_openai(_FakeAudio(), model="gpt-transcribe", client=client, lang="auto")
    call = client.audio.transcriptions.calls[0]
    assert "extra_body" not in call
    assert "language" not in call
    assert "may be in English or Bulgarian" in call["prompt"]


def _speech_to_text_with_no_hardware(monkeypatch, **kwargs):
    import sys

    from jarvis.audio.speech_to_text import SpeechToText

    # Same trick as test_speech_to_text_reports_unavailable_without_dependency:
    # forces the early-return path in __init__ so this is safe to construct
    # without real speech_recognition/microphone hardware. conversation_language
    # and languages are resolved before that early return, so they're still
    # observable afterward.
    monkeypatch.setitem(sys.modules, "speech_recognition", None)
    return SpeechToText(**kwargs)


def test_conversation_language_defaults_to_english_google_locale(monkeypatch):
    stt = _speech_to_text_with_no_hardware(monkeypatch)
    assert stt.conversation_language == "en"
    assert stt.languages == ("en-US",)


def test_conversation_language_bulgarian_selects_bulgarian_google_locale(monkeypatch):
    stt = _speech_to_text_with_no_hardware(monkeypatch, conversation_language="bg")
    assert stt.conversation_language == "bg"
    assert stt.languages == ("bg-BG",)


def test_conversation_language_auto_tries_bulgarian_then_english(monkeypatch):
    stt = _speech_to_text_with_no_hardware(monkeypatch, conversation_language="auto")
    assert stt.languages == ("bg-BG", "en-US")


def test_explicit_languages_override_wins_over_conversation_language(monkeypatch):
    stt = _speech_to_text_with_no_hardware(monkeypatch, conversation_language="bg", languages=("en-US",))
    assert stt.languages == ("en-US",)


def test_conversation_language_read_from_settings_when_not_passed_explicitly(monkeypatch):
    from jarvis.user_settings import JarvisSettings

    monkeypatch.setattr(
        "jarvis.audio.speech_to_text.JarvisSettings.load",
        classmethod(lambda cls: JarvisSettings(openai={"conversation_language": "bg"})),
    )
    stt = _speech_to_text_with_no_hardware(monkeypatch)
    assert stt.conversation_language == "bg"
    assert stt.languages == ("bg-BG",)


def test_set_conversation_language_updates_an_already_constructed_instance(monkeypatch):
    # Lets a settings save take effect on the next listen_once() without
    # tearing down and reconstructing SpeechToText (which would lose the
    # live microphone/recognizer handles).
    stt = _speech_to_text_with_no_hardware(monkeypatch)
    assert stt.conversation_language == "en"

    stt.set_conversation_language("bg")

    assert stt.conversation_language == "bg"
    assert stt.languages == ("bg-BG",)


def test_set_conversation_language_to_auto_tries_bulgarian_then_english(monkeypatch):
    stt = _speech_to_text_with_no_hardware(monkeypatch, conversation_language="bg")
    stt.set_conversation_language("auto")
    assert stt.languages == ("bg-BG", "en-US")
