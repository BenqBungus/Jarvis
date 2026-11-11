"""Check the real local keyword model on cached synthetic audio, without a mic."""
from pathlib import Path
import argparse
import wave
import time
from array import array

from jarvis.audio.keyword_interrupt import KeywordDecoder, KeywordInterrupt
from jarvis.config import ensure_openai_api_key_visible


ROOT = Path(__file__).resolve().parents[1] / "data/diagnostics/keyword-interrupt"
CASES = [
    ("jarvis", "Jarvis.", "marin", True),
    ("hey-jarvis", "Hey Jarvis.", "cedar", True),
    ("jarvis-question", "Jarvis, could you explain that differently?", "marin", True),
    ("ordinary-speech", "Here is how your computer manages memory and runs applications.", "cedar", False),
]


def check(generate=False):
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, text, voice, expected in CASES:
        path = ROOT / (name + ".wav")
        if not path.exists():
            if not generate:
                raise RuntimeError("Missing fixture; run with --generate to synthesize paid test audio.")
            from openai import OpenAI
            ensure_openai_api_key_visible()
            with OpenAI(timeout=30) as client:
                pcm = client.audio.speech.create(model="gpt-4o-mini-tts", voice=voice,
                    input=text, response_format="pcm").content
            with wave.open(str(path), "wb") as output:
                output.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
                output.writeframes(pcm)
        with wave.open(str(path), "rb") as source:
            decoder = KeywordDecoder(source.getframerate())
            pcm = source.readframes(source.getnframes()) + bytes(48000)
        hits = [offset / 48000 for offset in range(0, len(pcm), 4800) if decoder.feed(pcm[offset:offset + 4800])]
        print(f"{name}: detected={bool(hits)}, expected={expected}, detection_seconds={hits}", flush=True)
        if bool(hits) != expected:
            raise RuntimeError(f"Keyword check failed: {name}")
    print("Synthetic keyword checks passed. Room echo and the user's accent still require a listening test.")


def check_stream():
    def samples(name):
        with wave.open(str(ROOT / (name + ".wav")), "rb") as source:
            return array("h", source.readframes(source.getnframes()))

    speech, keyword = samples("ordinary-speech"), samples("jarvis")
    cases = [("user-over-reply", speech, keyword, True),
             ("assistant-name-echo", keyword, [], False),
             ("ordinary-echo", speech, [], False)]
    for name, reference, user, expected in cases:
        length = max(len(reference), len(user) + 14400) + 24000
        output = array("h", reference)
        output.extend([0] * (length - len(output)))
        microphone = array("h", [0] * length)
        for index in range(length):
            echo = output[index - 2400] * .25 if index >= 2400 else 0
            voice = user[index - 14400] if 14400 <= index < len(user) + 14400 else 0
            microphone[index] = max(-32768, min(32767, int(echo + voice)))
        hits = []
        started = time.monotonic()
        with KeywordInterrupt(lambda reply: hits.append(time.monotonic() - started)) as listener:
            if not listener.available:
                raise RuntimeError(listener.error)
            # Match the app's 20 ms output / 100 ms microphone callback sizes.
            for offset in range(0, length, 480):
                time.sleep(max(0, started + offset / 24000 - time.monotonic()))
                listener.feed("speaker", output[offset:offset + 480].tobytes(), 1)
                if offset % 2400 == 1920:
                    listener.feed("microphone", microphone[offset - 1920:offset + 480].tobytes(), 1)
            time.sleep(.3)
            if not listener.available:
                raise RuntimeError(listener.error)
        print(f"stream {name}: hits={hits}, expected={expected}", flush=True)
        if bool(hits) != expected:
            raise RuntimeError(f"Stream keyword check failed: {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generate", action="store_true", help="Make paid TTS requests only for missing fixtures.")
    parser.add_argument("--stream", action="store_true", help="Replay synthetic echo/mixed speech through the worker, without devices.")
    args = parser.parse_args()
    check(args.generate)
    if args.stream:
        check_stream()
