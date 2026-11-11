"""Barge-in on laptop speakers: notice the person talking over Jarvis.

With speakers, Live-call input is gated while Jarvis talks, because there is
no acoustic echo cancellation here. This detector watches the gated
microphone next to Jarvis's own output: it learns how loud Jarvis's voice
comes back into the microphone and reports speech clearly louder than that
echo. It is not echo cancellation: a soft voice under loud playback can be
missed, which is why headphones still give the most natural interruptions.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable


def pcm_rms(pcm: bytes) -> float:
    """RMS of 16-bit little-endian mono PCM."""
    if not pcm or len(pcm) % 2:
        return 0.0
    samples = memoryview(pcm).cast("h")
    return math.sqrt(sum(sample * sample for sample in samples) / len(samples))


class BargeInDetector:
    MARGIN = 2.2  # speech must be this much louder than the expected echo (about 7 dB)
    FLOOR = 350.0  # 16-bit RMS treated as background noise
    NEED = 0.22  # seconds of speech-like audio within WINDOW
    WINDOW = 0.5
    REFERENCE_SPAN = 0.45  # Jarvis's output this recent may still be echoing

    def __init__(self, *, clock: Callable[[], float] = time.monotonic, margin: float | None = None) -> None:
        self._clock = clock
        self.margin = margin or self.MARGIN
        self._lock = threading.Lock()
        self._reference: deque[tuple[float, float]] = deque()  # (time it sounds, rms)
        self._speech: deque[tuple[float, float]] = deque()  # (chunk end, speech seconds)
        self.coupling = 0.9  # echo RMS / output RMS, learned while the person is quiet
        self.noise = self.FLOOR

    def reset(self) -> None:
        with self._lock:
            self._speech.clear()

    def speaker(self, pcm: bytes, sounds_at: float | None = None) -> None:
        """Jarvis's own output, stamped with when it reaches the speaker."""
        level = pcm_rms(pcm)
        with self._lock:
            self._reference.append((self._clock() if sounds_at is None else sounds_at, level))
            horizon = self._clock() - 3.0
            while self._reference and self._reference[0][0] < horizon:
                self._reference.popleft()

    def _reference_level(self, start: float, end: float) -> float:
        return max((level for at, level in self._reference if start - self.REFERENCE_SPAN <= at <= end), default=0.0)

    def microphone(self, pcm: bytes, duration: float) -> bool:
        """One captured chunk that ends now. True once the person has been
        talking over Jarvis for long enough; the detector then starts over."""
        now = self._clock()
        level = pcm_rms(pcm)
        with self._lock:
            reference = self._reference_level(now - duration, now)
            threshold = max(self.noise * 2.5, self.FLOOR, self.coupling * reference * self.margin)
            speech = level > threshold
            if not speech:
                if reference > self.FLOOR * 2:  # echo only: how loud Jarvis comes back
                    self.coupling += 0.08 * (min(3.0, level / reference) - self.coupling)
                    self.coupling = min(3.0, max(0.05, self.coupling))
                elif reference < self.FLOOR:  # nobody talking: the room's noise
                    self.noise += 0.05 * (max(level, 60.0) - self.noise)
            self._speech.append((now, duration if speech else 0.0))
            while self._speech and self._speech[0][0] < now - self.WINDOW:
                self._speech.popleft()
            if sum(seconds for _end, seconds in self._speech) >= self.NEED:
                self._speech.clear()
                return True
            return False
