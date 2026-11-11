from __future__ import annotations

from .conversation import ConversationMemory


class RealtimeHistory:
    """Commit ordered completed voice turns at session end, never unheard replies."""

    def __init__(self, memory: ConversationMemory) -> None:
        self.memory = memory
        self.generation = memory.generation
        self.items: dict[str, dict] = {}
        self.interrupted: set[str] = set()
        self.completed: set[str] = set()
        self.heard: set[str] = set()
        self.interrupted_responses: set[str] = set()

    def observe(self, event: dict) -> None:
        kind = event.get("type")
        item = event.get("item", {})
        if str(item.get("id", "")).startswith("screen_"):
            return
        if kind in {"conversation.item.added", "conversation.item.created"} and item.get("role") in {"user", "assistant"}:
            self.items.setdefault(item["id"], {"role": item["role"], "text": ""})
        elif kind == "conversation.item.input_audio_transcription.completed":
            key = event.get("item_id")
            if key:
                self.items.setdefault(key, {"role": "user"})["text"] = event.get("transcript", "")
        elif kind == "response.output_audio_transcript.done":
            key = event.get("item_id")
            if key:
                self.items.setdefault(key, {"role": "assistant"})["text"] = event.get("transcript", "")
        elif kind == "response.done":
            response = event.get("response", {})
            keys = {item.get("id") for item in response.get("output", []) if item.get("type") == "message"}
            if response.get("status") == "completed" and response.get("id") not in self.interrupted_responses:
                self.completed.update(keys)
            else:
                self.interrupted.update(keys)

    def interrupt(self, item_ids) -> None:
        self.interrupted.update(item_ids)

    def interrupt_response(self, response_id: str) -> None:
        self.interrupted_responses.add(response_id)

    def playback_drained(self) -> None:
        self.heard.update(self.completed - self.interrupted)

    def commit(self) -> None:
        turns = [(item["role"], item.get("text", "")) for key, item in self.items.items()
                 if item["role"] == "user" or (key in self.heard and key not in self.interrupted)]
        self.memory.add_turns(turns, expected_generation=self.generation)
        self.items.clear()
