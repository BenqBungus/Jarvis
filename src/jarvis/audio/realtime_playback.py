from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass
class _Packet:
    key: tuple[str, int]
    data: bytes
    offset: int = 0


class RealtimePlayback:
    """Bounded PCM queue consumed by PortAudio, never by the WebSocket loop."""

    def __init__(self, sample_rate: int = 24000, *, clock=time.monotonic) -> None:
        self.sample_rate = sample_rate
        self._clock = clock
        self._lock = threading.Lock()
        self._packets: deque[_Packet] = deque()
        self._scheduled: deque[tuple[tuple[str, int], int, int, float]] = deque()
        self._received: dict[tuple[str, int], int] = {}
        self._submitted: dict[tuple[str, int], int] = {}
        self._played: dict[tuple[str, int], int] = {}
        self._queued_bytes = 0
        self.error: str | None = None

    def enqueue(self, item_id: str, content_index: int, pcm: bytes) -> None:
        if not pcm:
            return
        if len(pcm) % 2:
            raise ValueError("Realtime PCM must contain complete 16-bit samples")
        with self._lock:
            self._advance(self._clock())
            for old in list(self._received):
                if old != (item_id, content_index) and self._played.get(old, 0) >= self._received[old]:
                    self._received.pop(old, None)
                    self._submitted.pop(old, None)
                    self._played.pop(old, None)
            if self._queued_bytes + len(pcm) > self.sample_rate * 2 * 120:
                raise RuntimeError("Speaker playback is not keeping up. Check the selected output device.")
            key = (item_id, content_index)
            self._packets.append(_Packet(key, pcm))
            self._received[key] = self._received.get(key, 0) + len(pcm) // 2
            self._queued_bytes += len(pcm)

    def _advance(self, now: float) -> None:
        while self._scheduled:
            key, start, frames, at = self._scheduled[0]
            heard = min(frames, max(0, int((now - at) * self.sample_rate)))
            self._played[key] = max(self._played.get(key, 0), start + heard)
            if heard < frames:
                break
            self._scheduled.popleft()

    def callback(self, outdata, frames, timing, status) -> None:
        output = memoryview(outdata).cast("B")
        output[:] = b"\x00" * len(output)
        try:
            now = self._clock()
            delay = max(0.0, timing.outputBufferDacTime - timing.currentTime)
            with self._lock:
                self._advance(now)
                written = 0
                while self._packets and written < len(output):
                    packet = self._packets[0]
                    count = min(len(output) - written, len(packet.data) - packet.offset)
                    output[written:written + count] = packet.data[packet.offset:packet.offset + count]
                    start = self._submitted.get(packet.key, 0)
                    self._scheduled.append((packet.key, start, count // 2, now + delay + written / 2 / self.sample_rate))
                    self._submitted[packet.key] = start + count // 2
                    packet.offset += count
                    self._queued_bytes -= count
                    written += count
                    if packet.offset == len(packet.data):
                        self._packets.popleft()
        except Exception as exc:
            self.error = f"Speaker callback failed: {exc}"

    @property
    def pending(self) -> bool:
        with self._lock:
            self._advance(self._clock())
            return bool(self._packets or self._scheduled)

    def interrupt(self) -> list[dict]:
        """Drop unplayed audio and describe exactly what the server must forget."""
        with self._lock:
            self._advance(self._clock())
            events = [
                {
                    "type": "conversation.item.truncate",
                    "item_id": key[0],
                    "content_index": key[1],
                    "audio_end_ms": self._played.get(key, 0) * 1000 // self.sample_rate,
                }
                for key, received in self._received.items()
                if key[0] and self._played.get(key, 0) < received
            ]
            self._packets.clear()
            self._scheduled.clear()
            self._received.clear()
            self._submitted.clear()
            self._played.clear()
            self._queued_bytes = 0
            return events
