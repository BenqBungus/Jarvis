from __future__ import annotations

import asyncio

import pytest

from jarvis.audio.realtime_playback import RealtimePlayback
from jarvis.realtime import (
    DEFAULT_REALTIME_MODEL,
    DEFAULT_REALTIME_VOICE,
    REALTIME_SAMPLE_RATE,
    RealtimeVoiceConfig,
    RealtimeVoiceSession,
    _audio_devices_available,
    realtime_tool_schemas,
)
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions
from jarvis.user_settings import JarvisSettings


def test_realtime_config_builds_voice_agent_session_update_event():
    config = RealtimeVoiceConfig()

    event = config.session_update_event()
    session = event["session"]

    assert event["type"] == "session.update"
    assert session["type"] == "realtime"
    assert session["model"] == DEFAULT_REALTIME_MODEL
    assert session["output_modalities"] == ["audio"]
    assert session["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": REALTIME_SAMPLE_RATE}
    assert session["audio"]["input"]["turn_detection"] == {
        "type": "semantic_vad", "create_response": True, "interrupt_response": True,
    }
    assert session["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": REALTIME_SAMPLE_RATE}
    assert session["audio"]["output"]["voice"] == DEFAULT_REALTIME_VOICE
    assert session["audio"]["input"]["transcription"]["languages"] == ["en"]
    assert "Speak and reply only in English" in session["instructions"]
    assert "Speak Bulgarian by default" not in session["instructions"]


def test_legacy_live_transcription_uses_singular_english_hint():
    config = RealtimeVoiceConfig(transcription_model="gpt-4o-transcribe")
    transcription = config.session_update_event()["session"]["audio"]["input"]["transcription"]
    assert transcription == {"model": "gpt-4o-transcribe", "language": "en"}


def test_custom_voice_instructions_still_include_current_language_policy():
    config = RealtimeVoiceConfig(instructions="Use a relaxed tone.")
    instructions = config.session_update_event()["session"]["instructions"]
    assert "Use a relaxed tone." in instructions
    assert "Speak and reply only in English" in instructions


def test_realtime_config_connect_url_includes_required_model_query():
    config = RealtimeVoiceConfig(model="gpt-realtime-test")

    assert config.connect_url() == "wss://api.openai.com/v1/realtime?model=gpt-realtime-test"


def test_realtime_config_connect_url_preserves_existing_query_values():
    config = RealtimeVoiceConfig(
        model="gpt-realtime-test",
        websocket_url="wss://api.openai.com/v1/realtime?foo=bar",
    )

    assert config.connect_url() == "wss://api.openai.com/v1/realtime?foo=bar&model=gpt-realtime-test"


def test_realtime_config_reads_settings_with_tts_voice_fallback():
    settings = JarvisSettings(openai={"text_to_speech_voice": "marin"})

    config = RealtimeVoiceConfig.from_settings(settings)

    assert config.model == DEFAULT_REALTIME_MODEL
    assert config.voice == "marin"


def test_speaker_guard_defaults_on_and_headphones_are_explicit():
    assert RealtimeVoiceConfig.from_settings(JarvisSettings()).speaker_guard
    assert not RealtimeVoiceConfig.from_settings(JarvisSettings(openai={"realtime_speaker_guard": False})).speaker_guard


def test_realtime_config_prefers_explicit_realtime_settings():
    settings = JarvisSettings(
        openai={
            "realtime_model": "gpt-realtime-custom",
            "realtime_voice": "cedar",
            "realtime_instructions": "Talk naturally and use tools safely.",
        }
    )

    config = RealtimeVoiceConfig.from_settings(settings)

    assert config.model == "gpt-realtime-custom"
    assert config.voice == "cedar"
    assert config.instructions == "Talk naturally and use tools safely."


def test_realtime_config_defaults_to_english_conversation_language():
    config = RealtimeVoiceConfig.from_settings(JarvisSettings())
    assert config.conversation_language == "en"
    assert config.greeting == "Hello Berk, how can I help you?"


def test_realtime_config_from_settings_reads_conversation_language():
    settings = JarvisSettings(openai={"conversation_language": "bg"})
    config = RealtimeVoiceConfig.from_settings(settings)
    assert config.conversation_language == "bg"
    assert config.greeting == "Здравей, Берк. Как мога да помогна?"


def test_bulgarian_session_update_event_speaks_only_bulgarian():
    config = RealtimeVoiceConfig(conversation_language="bg")
    session = config.session_update_event()["session"]

    assert "само на български" in session["instructions"]
    assert "English" not in session["instructions"]
    assert session["audio"]["input"]["transcription"]["languages"] == ["bg"]


def test_auto_session_update_event_omits_the_transcription_language_hint():
    config = RealtimeVoiceConfig(conversation_language="auto")
    session = config.session_update_event()["session"]

    assert "English or Bulgarian" in session["instructions"]
    assert "languages" not in session["audio"]["input"]["transcription"]
    assert "language" not in session["audio"]["input"]["transcription"]


def test_default_realtime_instructions_are_language_neutral():
    # Regression guard for the base instructions fighting the per-language
    # policy spliced in later in the same string (see session_update_event).
    from jarvis.realtime import DEFAULT_REALTIME_INSTRUCTIONS

    assert "English" not in DEFAULT_REALTIME_INSTRUCTIONS


def test_voice_guidance_only_names_real_tools(tmp_path, monkeypatch):
    # Role-pack and driver guidance steer the model toward specific registered
    # tools; a renamed or removed tool would silently turn that advice into noise.
    import re

    from jarvis.realtime import _BASE_REALTIME_RULES, DEFAULT_REALTIME_INSTRUCTIONS
    from jarvis.role_packs import PACKS

    monkeypatch.chdir(tmp_path)
    assert "J.A.R.V.I.S." in DEFAULT_REALTIME_INSTRUCTIONS  # the default personality
    assert "never act without the user's request" in DEFAULT_REALTIME_INSTRUCTIONS
    assert "Gaming:" in DEFAULT_REALTIME_INSTRUCTIONS  # the default Gamer pack
    router = CommandRouter(WindowsActions(dry_run=True), SafetyPolicy(auto_confirm=False))
    registered = {spec.name for spec in router.tools.list_specs()}
    expected = {
        "drivers": {"scan_driver_updates", "install_windows_driver_updates", "install_nvidia_driver",
                    "driver_update_status"},
        "gamer": {"list_processes", "research_web", "system_hardware_status", "game_mode"},
        "business": {"gmail_search", "gmail_read", "gmail_summarize", "gmail_advise"},
    }
    sections = {"drivers": _BASE_REALTIME_RULES.split("Drivers:", 1)[1],
                **{pack_id: pack.instructions for pack_id, pack in PACKS.items()}}
    for name, text in sections.items():
        named = set(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", text)) - {"scan_id"}  # a parameter, not a tool
        assert named >= expected.get(name, set()), name
        assert named <= registered, (name, named - registered)


def test_realtime_status_reports_ready_when_key_and_modules_are_available(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr("jarvis.realtime._module_available", lambda _name: True)
    monkeypatch.setattr("jarvis.realtime._audio_devices_available", lambda: True)

    result = RealtimeVoiceSession(RealtimeVoiceConfig()).status_result()

    assert result.ok
    assert "Realtime voice is ready" in result.message
    assert result.metadata["realtime_voice"]["ready"] is True
    assert result.metadata["realtime_voice"]["missing"] == []


def test_realtime_status_reports_missing_requirements(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("jarvis.realtime.ensure_openai_api_key_visible", lambda: False)
    monkeypatch.setattr("jarvis.realtime._module_available", lambda _name: False)

    result = RealtimeVoiceSession(RealtimeVoiceConfig()).status_result()

    assert not result.ok
    assert result.metadata["realtime_voice"]["ready"] is False
    assert result.metadata["realtime_voice"]["missing"] == ["OPENAI_API_KEY", "websockets", "sounddevice"]


def test_audio_devices_available_when_input_and_output_devices_exist(monkeypatch):
    import sys
    import types

    devices = [
        {"max_input_channels": 2, "max_output_channels": 0},
        {"max_input_channels": 0, "max_output_channels": 2},
    ]
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(query_devices=lambda: devices))

    assert _audio_devices_available() is True


def test_audio_devices_unavailable_when_no_input_device_exists(monkeypatch):
    import sys
    import types

    devices = [{"max_input_channels": 0, "max_output_channels": 2}]
    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(query_devices=lambda: devices))

    assert _audio_devices_available() is False


def test_audio_devices_unavailable_when_device_query_raises(monkeypatch):
    import sys
    import types

    def _raise():
        raise OSError("PortAudio not initialized")

    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(query_devices=_raise))

    assert _audio_devices_available() is False


def test_audio_devices_unavailable_when_device_list_is_empty(monkeypatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "sounddevice", types.SimpleNamespace(query_devices=lambda: []))

    assert _audio_devices_available() is False


def test_audio_devices_unavailable_when_sounddevice_is_not_installed(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "sounddevice", None)

    assert _audio_devices_available() is False


def test_realtime_tool_schemas_strip_local_metadata():
    router = CommandRouter(actions=WindowsActions(dry_run=True), safety=SafetyPolicy(auto_confirm=True), ai=None)

    schemas = realtime_tool_schemas(router.tools)
    open_url = next(schema for schema in schemas if schema["name"] == "open_url")

    assert open_url["type"] == "function"
    assert "metadata" not in open_url
    assert open_url["parameters"]["required"] == ["url"]


def test_realtime_tool_executor_uses_router_safety_for_confirm_tools(monkeypatch):
    router = CommandRouter(actions=WindowsActions(dry_run=True), safety=SafetyPolicy(auto_confirm=False), ai=None)
    prompts: list[str] = []
    monkeypatch.setattr(router.safety, "confirm", lambda action, reason: prompts.append(action) or False)

    output = RealtimeVoiceSession.tool_executor_from_router(router)("disable_internet", {})

    assert not output["ok"]
    assert output["confirmed"] is False
    assert output["requires_confirmation"] is True
    assert prompts == ["Run Jarvis tool: disable_internet"]


def test_realtime_tool_executor_runs_safe_tool():
    router = CommandRouter(actions=WindowsActions(dry_run=True), safety=SafetyPolicy(auto_confirm=True), ai=None)

    output = RealtimeVoiceSession.tool_executor_from_router(router)("open_url", {"url": "https://example.com"})

    assert output["ok"]
    assert "Would open https://example.com" in output["message"]
    assert output["metadata"]["tool"] == "open_url"


def test_watch_playback_raises_when_the_output_stream_reports_an_error():
    # The real output path is callback-driven (sd.RawOutputStream(...,
    # callback=...)); there is no .write() call to retry in the live code
    # (the old write-retry helper this test used to exercise had zero
    # production call sites and has been removed). What actually happens on
    # a real output failure: RealtimePlayback.callback() catches the
    # exception into .error; _watch_playback polls it every 0.05s and turns
    # it into a RuntimeError, which RealtimeVoiceWorker._run_thread's own
    # except Exception handler already catches, redacts, and reports as a
    # clean "error" state (see test_gui_realtime_worker.py for that layer).
    async def scenario() -> None:
        session = RealtimeVoiceSession()
        playback = RealtimePlayback()
        playback.error = "Speaker callback failed: output device disconnected"
        with pytest.raises(RuntimeError, match="output device disconnected"):
            await session._watch_playback(playback, None)

    asyncio.run(scenario())


# --- Gmail: session-wide private-content memory suppression (docs/claude/GMAIL_VOICE_STATUS.md) ---


class _RecordingSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, value: str) -> None:
        import json

        self.sent.append(json.loads(value))


def test_a_private_tool_result_marks_the_session_touched():
    import json

    session = RealtimeVoiceSession()
    assert session._session_touched_private_content is False

    def tool_executor(name, arguments):
        return {"ok": True, "message": "wrapped email json", "metadata": {"private_content": True, "tool_category": "gmail"}}

    asyncio.run(session._maybe_execute_tool_call(_RecordingSocket(), {"item": {
        "type": "function_call", "name": "gmail_read", "call_id": "1", "arguments": "{}",
    }}, tool_executor=tool_executor, on_state=None))

    assert session._session_touched_private_content is True


def test_a_non_private_tool_result_leaves_the_session_flag_unset():
    session = RealtimeVoiceSession()

    def tool_executor(name, arguments):
        return {"ok": True, "message": "Volume set to 30%.", "metadata": {}}

    asyncio.run(session._maybe_execute_tool_call(_RecordingSocket(), {"item": {
        "type": "function_call", "name": "set_volume", "call_id": "1", "arguments": "{}",
    }}, tool_executor=tool_executor, on_state=None))

    assert session._session_touched_private_content is False


def test_private_content_flag_is_sticky_across_multiple_tool_calls_in_one_session():
    # A later, harmless tool call must not clear a flag a private call already set --
    # "once private content enters the session" is whole-session, not per-call.
    session = RealtimeVoiceSession()
    session._session_touched_private_content = True

    def tool_executor(name, arguments):
        return {"ok": True, "message": "Volume set to 30%.", "metadata": {}}

    asyncio.run(session._maybe_execute_tool_call(_RecordingSocket(), {"item": {
        "type": "function_call", "name": "set_volume", "call_id": "2", "arguments": "{}",
    }}, tool_executor=tool_executor, on_state=None))

    assert session._session_touched_private_content is True


def test_nested_private_content_metadata_is_detected():
    # contains_private_content() (privacy.py) recurses into nested dicts/lists --
    # a workflow-wrapped gmail step should still trip the flag, not just a bare
    # top-level private_content key.
    session = RealtimeVoiceSession()

    def tool_executor(name, arguments):
        return {"ok": True, "message": "workflow result", "metadata": {
            "steps": [{"tool": "gmail_search", "result": {"private_content": True}}]
        }}

    asyncio.run(session._maybe_execute_tool_call(_RecordingSocket(), {"item": {
        "type": "function_call", "name": "run_workflow", "call_id": "1", "arguments": "{}",
    }}, tool_executor=tool_executor, on_state=None))

    assert session._session_touched_private_content is True
