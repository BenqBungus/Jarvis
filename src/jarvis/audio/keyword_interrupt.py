"""Local keyword spotting on the existing PCM stream, never a second microphone."""
from __future__ import annotations

from dataclasses import dataclass
import queue
import threading
import time
from typing import Callable


class KeywordDecoder:
    def __init__(self, sample_rate: int = 24000) -> None:
        from pocketsphinx import Decoder

        self.decoder = Decoder(keyphrase="jarvis", kws_threshold=1e-20,
                               samprate=sample_rate, nfft=1024, loglevel="ERROR")
        self.decoder.start_utt()

    def reset(self) -> None:
        self.decoder.end_utt()
        self.decoder.start_utt()

    def feed(self, pcm: bytes) -> bool:
        self.decoder.process_raw(pcm, False, False)
        hypothesis = self.decoder.hyp()
        if hypothesis and "jarvis" in hypothesis.hypstr.split():
            self.reset()
            return True
        return False


@dataclass(frozen=True)
class _Packet:
    channel: str
    pcm: bytes
    timestamp: float
    reply: int
    epoch: int


class KeywordInterrupt:
    """Bounded worker with a speaker-reference veto and explicit mute epochs.

    The reference veto reduces self-triggers; it is not acoustic echo cancellation.
    A user repeating the name at the same time as the assistant may be rejected.
    """
    def __init__(self, on_keyword: Callable[[int], None], sample_rate=24000, *, decoder_factory=KeywordDecoder):
        self._on_keyword = on_keyword
        self._sample_rate = sample_rate
        self._factory = decoder_factory
        self._packets: queue.Queue[_Packet] = queue.Queue(maxsize=80)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._epoch = 0
        self._muted = False
        self._thread = None
        self.available = False
        self.error = ""

    def __enter__(self):
        try:
            self._microphone = self._factory(self._sample_rate)
            self._speaker = self._factory(self._sample_rate)
            self.available = True
            self._thread = threading.Thread(target=self._run, daemon=True, name="jarvis-keyword-interrupt")
            self._thread.start()
        except Exception as exc:
            self.available = False
            self.error = f"Local Jarvis interruption unavailable: {type(exc).__name__}. Use Interrupt reply or headphones."
        return self

    def __exit__(self, *_args):
        self.available = False
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def set_muted(self, muted: bool) -> None:
        with self._lock:
            if self._muted != muted:
                self._epoch += 1
            self._muted = muted

    def feed(self, channel: str, pcm: bytes, reply: int, timestamp: float | None = None) -> None:
        if not self.available or self._stop.is_set():
            return
        with self._lock:
            if self._muted and channel == "microphone":
                return
            packet = _Packet(channel, pcm, time.monotonic() if timestamp is None else timestamp, reply, self._epoch)
            try:
                self._packets.put_nowait(packet)
            except queue.Full:
                # Invalidate delayed recognition rather than interrupt a later reply.
                self._epoch += 1

    def _run(self) -> None:
        epoch, reply = -1, -1
        echo_until, cooldown_until = 0.0, 0.0
        pending: tuple[_Packet, float] | None = None
        try:
            while not self._stop.is_set():
                # Mic blocks are larger than speaker blocks. Give the reference
                # decoder time to veto a word arriving in the same audio interval.
                if pending and time.monotonic() >= pending[1]:
                    hit = pending[0]
                    pending = None
                    with self._lock:
                        valid = not self._muted and hit.epoch == self._epoch
                    if (valid and not self._stop.is_set() and hit.reply == reply
                            and hit.timestamp > max(echo_until, cooldown_until)):
                        cooldown_until = hit.timestamp + 1.0
                        self._on_keyword(hit.reply)
                try:
                    packet = self._packets.get(timeout=0.05)
                except queue.Empty:
                    continue
                with self._lock:
                    valid = packet.epoch == self._epoch and not (self._muted and packet.channel == "microphone")
                if not valid or time.monotonic() - packet.timestamp > 0.4:
                    continue
                if packet.epoch != epoch or packet.reply != reply:
                    self._microphone.reset()
                    self._speaker.reset()
                    epoch, reply = packet.epoch, packet.reply
                if packet.channel == "speaker":
                    if self._speaker.feed(packet.pcm):
                        echo_until = packet.timestamp + 1.0
                elif self._microphone.feed(packet.pcm):
                    if pending is None:
                        pending = (packet, time.monotonic() + 0.15)
        except Exception as exc:
            self.available = False
            self.error = f"Local Jarvis interruption stopped: {type(exc).__name__}. Use Interrupt reply or headphones."
