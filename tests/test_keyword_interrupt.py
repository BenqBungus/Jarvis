from __future__ import annotations

import threading
import time

import pytest

from jarvis.audio.keyword_interrupt import KeywordInterrupt


class Decoder:
    def __init__(self, _rate):
        self.fed = []
        self.resets = 0

    def reset(self):
        self.resets += 1

    def feed(self, pcm):
        self.fed.append(pcm)
        return pcm == b"jarvis"


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.01)
    assert predicate()


def test_keyword_interrupts_once_and_thread_stops():
    hits = []
    with KeywordInterrupt(hits.append, decoder_factory=Decoder) as listener:
        assert listener.available
        listener.feed("microphone", b"ordinary speech", 1)
        listener.feed("microphone", b"jarvis", 1)
        wait_for(lambda: hits == [1])
        listener.feed("microphone", b"jarvis", 1)
        time.sleep(.25)
        assert hits == [1]
    assert not listener.available
    assert not listener._thread.is_alive()
    listener.feed("microphone", b"jarvis", 2)
    assert hits == [1]


@pytest.mark.parametrize("reference_first", [True, False])
def test_assistants_own_name_is_vetoed_even_if_reference_arrives_later(reference_first):
    hits = []
    with KeywordInterrupt(hits.append, decoder_factory=Decoder) as listener:
        channels = ["speaker", "microphone"] if reference_first else ["microphone", "speaker"]
        for channel in channels:
            listener.feed(channel, b"jarvis", 1)
            time.sleep(.03)
        wait_for(lambda: listener._microphone.fed and listener._speaker.fed)
        time.sleep(.25)
        assert hits == []


def test_manual_mute_blocks_detection_and_invalidates_pending_hit_after_unmute():
    hits = []
    with KeywordInterrupt(hits.append, decoder_factory=Decoder) as listener:
        listener.feed("microphone", b"jarvis", 1)
        wait_for(lambda: listener._microphone.fed)
        listener.set_muted(True)
        listener.feed("microphone", b"muted secret", 1)
        listener.set_muted(False)
        time.sleep(.25)
        assert not hits
        assert b"muted secret" not in listener._microphone.fed
        listener.feed("microphone", b"jarvis", 2)
        wait_for(lambda: hits == [2])


def test_old_audio_is_discarded_without_decoding():
    hits = []
    with KeywordInterrupt(hits.append, decoder_factory=Decoder) as listener:
        listener.feed("microphone", b"jarvis", 1, time.monotonic() - 2)
        listener.feed("microphone", b"current audio", 2)
        wait_for(lambda: listener._microphone.fed)
        assert listener._microphone.fed == [b"current audio"]
        assert hits == []


def test_new_reply_invalidates_pending_detection():
    hits = []
    with KeywordInterrupt(hits.append, decoder_factory=Decoder) as listener:
        listener.feed("microphone", b"jarvis", 1)
        wait_for(lambda: listener._microphone.fed)
        listener.feed("speaker", b"new reply", 2)
        wait_for(lambda: listener._speaker.fed)
        time.sleep(.25)
        assert hits == []


def test_backlog_is_bounded_and_overflow_invalidates_old_packets():
    listener = KeywordInterrupt(lambda _: None, decoder_factory=Decoder)
    listener.available = True
    for _ in range(100):
        listener.feed("microphone", b"jarvis", 1)
    assert listener._packets.qsize() == 80
    assert listener._epoch > 0
    assert listener._packets.get_nowait().epoch != listener._epoch


def test_missing_optional_dependency_preserves_call_fallback():
    def missing(_rate):
        raise ImportError("not installed")

    with KeywordInterrupt(lambda _: None, decoder_factory=missing) as listener:
        assert not listener.available
        assert "Interrupt reply or headphones" in listener.error
        listener.feed("microphone", b"jarvis", 1)


def test_decoder_failure_is_reported_without_escaping_worker():
    class Broken(Decoder):
        def feed(self, pcm):
            raise ValueError("bad PCM")

    with KeywordInterrupt(lambda _: None, decoder_factory=Broken) as listener:
        listener.feed("microphone", b"jarvis", 1)
        wait_for(lambda: not listener.available)
        assert "ValueError" in listener.error


def test_stopping_during_pending_hit_does_not_trigger_callback():
    hit = threading.Event()
    with KeywordInterrupt(lambda _: hit.set(), decoder_factory=Decoder) as listener:
        listener.feed("microphone", b"jarvis", 1)
        wait_for(lambda: listener._microphone.fed)
    assert not hit.is_set()
