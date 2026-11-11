"""Voice input/output adapters. Both submodules import their third-party
dependency lazily, so importing this package never requires SpeechRecognition
or pyttsx3 to be installed -- only actually using the classes does."""

from .speech_to_text import RecognizedSpeech, SpeechToText
from .text_to_speech import TextToSpeech

__all__ = ["RecognizedSpeech", "SpeechToText", "TextToSpeech"]
