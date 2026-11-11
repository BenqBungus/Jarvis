from __future__ import annotations

import argparse
import asyncio
import logging

from .audit import AuditLogger
from .config import ensure_openai_api_key_visible
from .ai_client import JarvisAI
from .monitoring.loop import BackgroundMonitor
from .router import CommandRouter
from .safety import SafetyPolicy
from .session import CommandSession
from .user_settings import JarvisSettings
from .windows_actions import WindowsActions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local Jarvis assistant for Windows.")
    parser.add_argument("command", nargs="*", help="Run one command and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without executing them.")
    parser.add_argument("--yes", action="store_true", help="Auto-confirm high-impact actions.")
    parser.add_argument(
        "--voice", action="store_true", help="Listen on the microphone instead of reading typed commands."
    )
    parser.add_argument(
        "--realtime-voice",
        action="store_true",
        help="Check/start the OpenAI Realtime voice-agent pipeline.",
    )
    parser.add_argument("--no-tts", action="store_true", help="Disable spoken responses.")
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Run background monitors (Windows Update, NVIDIA driver, battery, internet).",
    )
    parser.add_argument(
        "--list-voices", action="store_true", help="List installed text-to-speech voices and exit."
    )
    parser.add_argument(
        "--list-openai-voices", action="store_true", help="List built-in OpenAI text-to-speech voices and exit."
    )
    parser.add_argument(
        "--list-audio-devices", action="store_true", help="List output devices Jarvis can use for voice playback."
    )
    parser.add_argument(
        "--test-speaker", action="store_true", help="Play a short Jarvis voice test and exit."
    )
    parser.add_argument(
        "--test-output-tone", action="store_true", help="Play a short tone through Jarvis's selected output device."
    )
    parser.add_argument(
        "--voice-doctor", action="store_true", help="Diagnose Jarvis microphone, speaker, TTS, and Realtime setup."
    )
    parser.add_argument(
        "--audio-output-device",
        help="Temporarily choose the output device for --test-speaker / --voice-doctor, e.g. 17 or \"SteelSeries\".",
    )
    parser.add_argument(
        "--set-audio-output-device",
        help="Save Jarvis's output device in data/settings.json. Use 'default' to clear it.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the native PySide6 desktop app (tray icon, window, voice) instead of the text REPL.",
    )
    return parser


def _make_tts(enabled: bool):
    from .audio.text_to_speech import TextToSpeech

    return TextToSpeech(enabled=enabled)


def _list_voices() -> None:
    tts = _make_tts(enabled=True)
    if not tts.enabled:
        print("Text-to-speech is not available. Install extras with: pip install -e .[voice]")
        return
    voices = tts.describe_voices()
    if not voices:
        print("No voices reported by the speech engine.")
        return
    for voice in voices:
        print(voice)


def _list_audio_devices() -> None:
    from .audio.output_device import configured_output_device, list_output_devices

    configured = configured_output_device()
    print(f"Configured output: {configured or 'System default'}")
    devices = list_output_devices()
    if not devices:
        print("No sounddevice output devices found. Install voice dependencies with: pip install -e .[voice]")
        return
    for device in devices:
        marker = "*" if configured and str(configured).split(":", 1)[0] == str(device.index) else " "
        print(f"{marker} {device.label} | channels={device.channels}")


def _test_speaker() -> None:
    from .audio.language import speaker_test_for, resolved_spoken_language
    language = JarvisSettings.load().conversation_language
    tts = _make_tts(enabled=True)
    print(tts.status_summary())
    spoken = tts.speak(speaker_test_for(language), lang=resolved_spoken_language(language))
    print(f"speaker_test={spoken}")


def _test_output_tone() -> None:
    from .audio.output_device import configured_output_device, play_test_tone

    configured = configured_output_device()
    print(f"Configured output: {configured or 'System default'}")
    print(f"tone_test={play_test_tone()}")


def _voice_doctor() -> None:
    from .audio.diagnostics import build_voice_diagnostics

    print(build_voice_diagnostics().message)


def _set_audio_output_device(value: str) -> None:
    settings = JarvisSettings.load()
    cleaned = str(value).strip()
    settings.openai["audio_output_device"] = "" if cleaned.lower() in {"default", "system default", "none"} else cleaned
    settings.save()
    print(f"Saved audio_output_device={settings.openai['audio_output_device'] or 'System default'}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    ensure_openai_api_key_visible()
    args = build_parser().parse_args()

    if args.audio_output_device:
        import os

        os.environ["JARVIS_AUDIO_OUTPUT_DEVICE"] = args.audio_output_device

    if args.list_voices:
        _list_voices()
        return

    if args.list_openai_voices:
        tts = _make_tts(enabled=False)
        for voice in tts.describe_openai_voices():
            print(voice)
        return

    if args.list_audio_devices:
        _list_audio_devices()
        return

    if args.test_speaker:
        _test_speaker()
        return

    if args.test_output_tone:
        _test_output_tone()
        return

    if args.voice_doctor:
        _voice_doctor()
        return

    if args.set_audio_output_device:
        _set_audio_output_device(args.set_audio_output_device)
        return

    if args.gui:
        # Branches before SafetyPolicy is ever constructed: a --gui process
        # may have no terminal at all (e.g. launched via pythonw or a Start
        # Menu shortcut), so SafetyPolicy.confirm()'s input() call must never
        # exist in this path. GuiSafetyPolicy (shown as an on-screen dialog)
        # is what the GUI app builds instead -- see jarvis.gui.app.
        from .gui.app import main as gui_main

        raise SystemExit(gui_main(dry_run=args.dry_run))

    safety = SafetyPolicy(auto_confirm=args.yes)
    settings = JarvisSettings.load()
    actions = WindowsActions(dry_run=args.dry_run)
    ai = JarvisAI(dry_run=args.dry_run, settings=settings)
    router = CommandRouter(actions=actions, safety=safety, ai=ai, settings=settings)
    audit = AuditLogger()

    if args.command:
        try:
            text = " ".join(args.command)
            result = CommandSession(router=router, audit=audit, dry_run=args.dry_run).execute(text, source="cli")
            print(result.message)
        finally:
            router.browser.close()
        return

    if args.realtime_voice:
        try:
            _run_realtime_voice(settings, router)
        finally:
            router.browser.close()
        return

    # Only built when actually needed, so plain text-mode runs never require
    # the voice extras (pyttsx3/SpeechRecognition/PyAudio) to be installed.
    shared_tts = None
    if args.voice or args.monitor:
        shared_tts = _make_tts(enabled=not args.no_tts)

    monitor = None
    if args.monitor:
        def notify(message: str) -> None:
            print(f"[monitor] {message}")
            if shared_tts is not None:
                shared_tts.speak(message)

        monitor = BackgroundMonitor(notify=notify, settings=settings)
        monitor.start()

    try:
        if args.voice:
            _run_voice_loop(router, tts=shared_tts)
        else:
            _run_text_loop(router, audit=audit, dry_run=args.dry_run)
    finally:
        if monitor is not None:
            monitor.stop()
        router.browser.close()


def _run_text_loop(router: CommandRouter, audit: AuditLogger | None = None, dry_run: bool = False) -> None:
    print("Jarvis is ready. Type a command, or 'exit' to quit.")
    while True:
        try:
            text = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return

        if text.lower() in {"exit", "quit", "изход", "край"}:
            print("Goodbye.")
            return

        if not text:
            continue

        result = CommandSession(router=router, audit=audit, dry_run=dry_run).execute(text, source="cli_repl")
        print(result.message)


def _run_voice_loop(router: CommandRouter, tts) -> None:
    from .audio.speech_to_text import SpeechToText
    from .voice_assistant import VoiceAssistant
    from .gmail import gmail_spoken_result

    language = router.settings.conversation_language
    stt = SpeechToText(conversation_language=language)
    if not stt.available:
        print("Voice input is not available (missing SpeechRecognition/PyAudio, or no microphone).")
        print("Install extras with: pip install -e .[voice]")
        print("Falling back to typed commands.")
        _run_text_loop(router)
        return

    assistant = VoiceAssistant(router=router, stt=stt, tts=tts, spoken_language=language,
                               dispatch=lambda text: gmail_spoken_result(router.handle(text)))
    assistant.run_forever()


def _run_realtime_voice(settings: JarvisSettings, router: CommandRouter) -> None:
    from dataclasses import replace
    from .realtime import RealtimeVoiceConfig, RealtimeVoiceSession, realtime_tool_schemas

    config = RealtimeVoiceConfig.from_settings(settings)
    config = replace(config, tools=realtime_tool_schemas(router.tools))
    session = RealtimeVoiceSession(config, memory=router.conversation_memory
                                    if settings.openai.get("use_memory_context", True) else None)
    result = session.status_result()
    print(result.message)
    if not result.ok:
        event = session.config.session_update_event()
        session_config = event["session"]
        print(
            "Realtime config: "
            f"model={session_config['model']}, "
            f"voice={session_config['audio']['output']['voice']}, "
            f"sample_rate={session_config['audio']['input']['format']['rate']}, "
            f"turn_detection={session_config['audio']['input']['turn_detection']['type']}, "
            f"tools={len(session_config.get('tools', []))}"
        )
        return

    def show_state(state: str, event: dict) -> None:
        if state in {"connecting", "listening", "thinking", "speaking", "interrupted", "tool_call", "error"}:
            detail = ""
            if state == "tool_call":
                detail = f" {event.get('name', '')}"
            if state == "error":
                detail = f" {event.get('error', event)}"
            print(f"[realtime] {state}{detail}")

    print("Starting realtime voice. Press Ctrl+C to stop.")
    try:
        asyncio.run(
            session.run_stream(
                tool_executor=RealtimeVoiceSession.tool_executor_from_router(router),
                on_state=show_state,
            )
        )
    except KeyboardInterrupt:
        print("\nRealtime voice stopped.")
