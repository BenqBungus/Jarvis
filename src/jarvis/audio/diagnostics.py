from __future__ import annotations

import os
from typing import Any

from ..config import ensure_openai_api_key_visible
from ..models import CommandResult
from ..realtime import RealtimeVoiceConfig, RealtimeVoiceSession
from ..user_settings import JarvisSettings
from .output_device import configured_output_device, list_output_devices, resolve_output_device
from .speech_to_text import SpeechToText
from .text_to_speech import TextToSpeech


def build_voice_diagnostics(settings: JarvisSettings | None = None) -> CommandResult:
    settings = settings or JarvisSettings.load()
    ensure_openai_api_key_visible()

    tts = TextToSpeech(enabled=True)
    tts_status = tts.status_summary()
    stt_status = _speech_to_text_status(settings)
    realtime_config = RealtimeVoiceConfig.from_settings(settings)
    realtime_status = RealtimeVoiceSession(realtime_config).readiness()
    devices = list_output_devices()
    configured_output = configured_output_device(settings)
    output_error = ""
    try:
        resolved_output = resolve_output_device(configured_output)
    except ValueError as exc:
        resolved_output = None
        output_error = str(exc)

    recommendations = _recommendations(
        tts_status=tts_status,
        stt_status=stt_status,
        realtime_status=realtime_status,
        devices=devices,
        configured_output=configured_output,
        resolved_output=resolved_output,
    )
    if output_error:
        recommendations.insert(0, output_error)

    message = "\n".join(
        [
            "Voice Doctor",
            f"- OpenAI key: {'visible' if os.getenv('OPENAI_API_KEY') else 'missing'}",
            f"- TTS: {_format_tts_status(tts_status)}",
            f"- STT: {_format_stt_status(stt_status)}",
            f"- Realtime: {_format_realtime_status(realtime_status)}",
            f"- Output: {_format_output_status(configured_output, resolved_output, devices)}",
            "- Recommendation: " + ("; ".join(recommendations) if recommendations else "voice setup looks ready"),
        ]
    )

    ok = bool(tts_status.get("enabled")) and bool(stt_status.get("available")) and bool(devices) and not output_error
    return CommandResult(
        ok,
        message,
        intent="diagnostic.voice",
        action="voice_doctor",
        metadata={
            "voice_diagnostics": {
                "tts": tts_status,
                "stt": stt_status,
                "realtime": realtime_status,
                "audio_output": {
                    "configured": configured_output,
                    "resolved": resolved_output,
                    "error": output_error,
                    "devices": [device.__dict__ | {"label": device.label} for device in devices],
                },
                "recommendations": recommendations,
            }
        },
    )


def _speech_to_text_status(settings: JarvisSettings) -> dict[str, Any]:
    openai_settings = settings.openai
    try:
        stt = SpeechToText()
    except Exception as exc:  # pragma: no cover - depends on local audio stack
        return {
            "available": False,
            "error": str(exc),
            "provider": str(openai_settings.get("speech_to_text_provider", "")),
            "model": str(openai_settings.get("speech_to_text_model", "")),
        }
    return {
        "available": bool(stt.available),
        "provider": stt.provider,
        "model": stt.openai_model,
        "languages": list(stt.languages),
    }


def _format_tts_status(status: dict[str, Any]) -> str:
    if not status.get("enabled"):
        return "not available"
    provider = status.get("provider", "voice")
    voice = status.get("openai_voice", "")
    fallback = "with Windows fallback" if status.get("windows_fallback_available") else "no Windows fallback"
    return f"{provider} {voice} ({fallback})".strip()


def _format_stt_status(status: dict[str, Any]) -> str:
    if not status.get("available"):
        detail = status.get("error")
        return f"not available ({detail})" if detail else "not available"
    return f"{status.get('provider', 'speech')} {status.get('model', '')}".strip()


def _format_realtime_status(status: dict[str, Any]) -> str:
    if status.get("ready"):
        return f"ready ({status.get('model')} / {status.get('voice')})"
    missing = ", ".join(str(item) for item in status.get("missing", []))
    return f"not ready ({missing or 'unknown issue'})"


def _format_output_status(configured: object, resolved: object, devices: list[Any]) -> str:
    if not devices:
        return "no output devices detected"
    resolved_label = _device_label(resolved, devices)
    if configured:
        suffix = f": {resolved_label}" if resolved_label else ""
        return f"configured {configured} -> resolved {resolved}{suffix}"
    default_label = _device_label(resolved, devices)
    return f"system default{f' -> {default_label}' if default_label else ''}"


def _recommendations(
    *,
    tts_status: dict[str, Any],
    stt_status: dict[str, Any],
    realtime_status: dict[str, Any],
    devices: list[Any],
    configured_output: object,
    resolved_output: object,
) -> list[str]:
    recommendations: list[str] = []
    resolved_label = _device_label(resolved_output, devices)
    if tts_status.get("provider") == "openai" and not tts_status.get("openai_key_present"):
        recommendations.append("add a valid OPENAI_API_KEY for OpenAI voice")
    if not tts_status.get("enabled"):
        recommendations.append("install voice dependencies or switch TTS provider")
    if not stt_status.get("available"):
        recommendations.append("check microphone permission/device and voice dependencies")
    if not realtime_status.get("ready"):
        missing = ", ".join(str(item) for item in realtime_status.get("missing", []))
        recommendations.append(f"Realtime needs {missing}" if missing else "check Realtime configuration")
    if not devices:
        recommendations.append("install sounddevice voice dependencies")
    elif configured_output and resolved_output is None:
        recommendations.append("choose a valid audio output device in Settings")
    elif resolved_label and _looks_like_mapper_output(resolved_label):
        recommendations.append("test and save an explicit headset/speaker instead of the Windows mapper output")
    elif not configured_output:
        recommendations.append("if you hear nothing, select your headset explicitly in Settings")
    return recommendations


def _device_label(device: object, devices: list[Any]) -> str:
    if device is None:
        return ""
    try:
        device_index = int(str(device).split(":", 1)[0].strip())
    except (TypeError, ValueError):
        device_index = None
    for candidate in devices:
        if device_index is not None and getattr(candidate, "index", None) == device_index:
            return str(getattr(candidate, "label", "") or getattr(candidate, "name", ""))
    return ""


def _looks_like_mapper_output(label: str) -> bool:
    lowered = label.lower()
    return "mapper" in lowered or "primary sound driver" in lowered
