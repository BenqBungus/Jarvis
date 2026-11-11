import asyncio
import json
from unittest.mock import Mock

import pytest

from jarvis.realtime import RealtimeVoiceSession
from jarvis.vision.sharing import ScreenSharing


def test_sharing_has_no_countdown_and_survives_long_sessions(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr("jarvis.vision.sharing.time.monotonic", lambda: clock[0])
    sharing = ScreenSharing(Mock())
    sharing.indicator_available = True
    sharing.start()
    sharing.indicator_visible()
    clock[0] += 3600
    sharing.indicator_visible()
    assert sharing.state()["ready"]
    assert "seconds_left" not in sharing.state()
    clock[0] += 3
    assert not sharing.state()["sharing"]


def test_live_capture_is_opt_in_and_stop_during_capture_discards(monkeypatch):
    sharing = ScreenSharing(Mock(), cancelled=lambda: True)
    capture = Mock(return_value=b"frame")
    monkeypatch.setattr(sharing, "_snapshot", capture)
    with pytest.raises(ValueError):
        sharing.frame_for_live()
    capture.assert_not_called()
    sharing.indicator_available = True
    sharing.start()
    sharing.indicator_visible()
    assert sharing.frame_for_live()[1] == b"frame"  # unrelated task cancellation is not Stop sharing
    capture.side_effect = lambda: (sharing.stop(), b"private-frame")[1]
    with pytest.raises(ValueError):
        sharing.frame_for_live()


def test_realtime_streams_without_questions_bounds_context_and_clears_on_stop(monkeypatch):
    async def scenario():
        clock = [100.0]
        monkeypatch.setattr("jarvis.realtime.time.monotonic", lambda: clock[0])
        sharing = ScreenSharing(Mock())
        sharing.indicator_available = True
        sharing.start()
        sharing.indicator_visible()
        frames = iter([b"first", b"first", b"second", b"third"])
        capture = Mock(side_effect=lambda: next(frames))
        monkeypatch.setattr(sharing, "_snapshot", capture)
        original_sleep = asyncio.sleep
        ticks = [0]

        async def tick(_):
            ticks[0] += 1
            if ticks[0] >= 6:
                raise asyncio.CancelledError
            clock[0] += 2
            sharing.indicator_visible()
            if ticks[0] == 4:
                sharing.stop()
            await original_sleep(0)
        monkeypatch.setattr("jarvis.realtime.asyncio.sleep", tick)
        events = []
        class Socket:
            async def send(self, payload):
                events.append(json.loads(payload))
        with pytest.raises(asyncio.CancelledError):
            await RealtimeVoiceSession(screen_sharing=sharing)._send_screen(Socket())
        creates = [e for e in events if e["type"] == "conversation.item.create" and e["item"]["id"].startswith("screen_frame_")]
        deletes = [e for e in events if e["type"] == "conversation.item.delete"]
        assert len(creates) == 3 and len(deletes) == 3
        assert not any(e["type"] == "response.create" for e in events)
        assert not sharing.state()["live"]
        assert capture.call_count == 4
        assert "input_image" in json.dumps(creates)
    asyncio.run(scenario())


def test_capture_error_stops_only_screen_sender(monkeypatch):
    async def scenario():
        sharing = ScreenSharing(Mock())
        sharing.indicator_available = True
        sharing.start()
        sharing.indicator_visible()
        monkeypatch.setattr(sharing, "_snapshot", Mock(side_effect=OSError("Unavailable")))
        callback = Mock()
        async def end(_):
            raise asyncio.CancelledError
        monkeypatch.setattr("jarvis.realtime.asyncio.sleep", end)
        class Socket:
            async def send(self, value):
                assert "input_image" not in value
        with pytest.raises(asyncio.CancelledError):
            await RealtimeVoiceSession(screen_sharing=sharing)._send_screen(Socket(), callback)
        assert not sharing.state()["sharing"]
        assert callback.call_args.args[0] == "tool_error"
    asyncio.run(scenario())


def test_screen_frames_are_not_added_to_voice_memory():
    from jarvis.memory.realtime_history import RealtimeHistory
    history = RealtimeHistory(Mock())
    history.observe({"type": "conversation.item.created", "item": {"id": "screen_frame_example", "role": "user"}})
    assert not history.items


def test_indicator_has_stop_without_countdown(qapp):
    from jarvis.gui.screen_sharing import ScreenSharingIndicator
    sharing = ScreenSharing(Mock())
    indicator = ScreenSharingIndicator(sharing)
    sharing.start()
    indicator.refresh()
    assert indicator.isVisible()
    assert not any(c.isdigit() for c in indicator.label.text())
    sharing.mark_live(sharing.state()["session_id"])
    indicator.refresh()
    assert "LIVE" in indicator.label.text()
    indicator.stop_button.click()
    assert not sharing.state()["sharing"]
    indicator.shutdown()
