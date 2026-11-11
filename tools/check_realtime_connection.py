"""Verify session configuration and generated speech without opening a microphone."""
from __future__ import annotations

import asyncio
import argparse
import base64
import json
import os
import wave
from pathlib import Path
from dataclasses import replace

import websockets

from jarvis.config import ensure_openai_api_key_visible
from jarvis.privacy import redact_sensitive_text
from jarvis.realtime import RealtimeVoiceConfig, RealtimeVoiceSession, _websocket_header_kwargs, _realtime_error_message, realtime_tool_schemas


async def receive_response(ws):
    chunks, transcripts = [], []
    while True:
        event = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
        if event["type"] == "error":
            raise RuntimeError(_realtime_error_message(event))
        if event["type"] == "response.output_audio.delta":
            chunks.append(base64.b64decode(event["delta"]))
        if event["type"] == "response.output_audio_transcript.done":
            transcripts.append(event.get("transcript", ""))
        if event["type"] == "response.done":
            if event["response"].get("status") != "completed":
                raise RuntimeError(str(event["response"].get("status_details")))
            return b"".join(chunks), " ".join(transcripts), event["response"].get("output", [])


async def send_user_text(ws, text):
    await ws.send(json.dumps({"type": "conversation.item.create", "item": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}],
    }}))
    await ws.send(json.dumps({"type": "response.create"}))


async def check(conversation: bool = False, audio_greeting: bool = False) -> None:
    ensure_openai_api_key_visible()
    config = RealtimeVoiceConfig.from_settings()
    if conversation:
        from jarvis.audit import AuditLogger
        from jarvis.gui.command_executor import CommandExecutor
        from jarvis.router import CommandRouter
        from jarvis.safety import SafetyPolicy
        from jarvis.windows_actions import WindowsActions

        router = CommandRouter(actions=WindowsActions(dry_run=True), safety=SafetyPolicy(auto_confirm=False), ai=None)
        # Match the GUI's extra read-only task-status schema without starting an action worker.
        executor = CommandExecutor(router, AuditLogger(Path("data/diagnostics/realtime-check-audit.jsonl")), dry_run=True)
        config = replace(config, tools=realtime_tool_schemas(router.tools))
    headers = {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]}
    session = RealtimeVoiceSession(config)
    async with websockets.connect(config.connect_url(), **_websocket_header_kwargs(headers, websockets.connect)) as ws:
        await ws.send(json.dumps(config.session_update_event()))
        await session._wait_for_session(ws)
        print("Session configuration accepted.")
        await ws.send(json.dumps({"type": "response.create", "response": {
            "instructions": "Say exactly: " + config.greeting, "tool_choice": "none",
        }}))
        pcm, transcript, _ = await receive_response(ws)
        print("Startup greeting: " + transcript)
        if audio_greeting:
            from openai import OpenAI

            def synthesize_greeting():
                with OpenAI(timeout=25) as client:
                    return client.audio.speech.create(model="gpt-4o-mini-tts", voice="marin",
                        input="Hello Jarvis!", response_format="pcm").content

            synthetic_pcm = await asyncio.to_thread(synthesize_greeting)
            # Feed a known English phrase at microphone speed. Semantic VAD,
            # not a manual response.create, must trigger the spoken answer.
            padded = synthetic_pcm + bytes(4800 * 20)
            for offset in range(0, len(padded), 4800):
                await ws.send(json.dumps({"type": "input_audio_buffer.append",
                    "audio": base64.b64encode(padded[offset:offset + 4800]).decode("ascii")}))
                await asyncio.sleep(0.1)
            reply, transcript, output = await receive_response(ws)
            if not reply or not any(reply) or any(item.get("type") == "function_call" for item in output):
                raise RuntimeError("The spoken greeting did not get a spoken conversational reply.")
            print("Reply to synthetic English audio: " + transcript)
        if conversation:
            for text in ("Hi! I enjoy drawing with a pencil. How are you? Reply briefly.",
                         "What did I say I enjoy doing? Reply in one sentence."):
                await send_user_text(ws, text)
                reply, transcript, calls = await receive_response(ws)
                if not reply or not any(reply) or any(item.get("type") == "function_call" for item in calls):
                    raise RuntimeError("Casual conversation did not return spoken audio.")
                print("Spoken turn: " + transcript)
            if not any(word in transcript.lower() for word in ("draw", "pencil")):
                raise RuntimeError("Follow-up did not recall the synthetic conversation context.")
            await send_user_text(ws, "Open https://example.org/jarvis-voice-check with open_url.")
            _, _, output = await receive_response(ws)
            calls = [item for item in output if item.get("type") == "function_call"]
            if len(calls) != 1 or calls[0].get("name") != "open_url":
                raise RuntimeError("Expected one open_url tool call for the arbitrary URL.")
            arguments = json.loads(calls[0]["arguments"])
            if arguments != {"url": "https://example.org/jarvis-voice-check"}:
                raise RuntimeError("Tool URL did not match the requested URL.")
            await ws.send(json.dumps({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": calls[0]["call_id"],
                "output": json.dumps({"ok": False, "message": "Diagnostic only. No website was opened."}),
            }}))
            await send_user_text(ws, "How is the task going? Check its current status with get_active_task_status.")
            _, _, output = await receive_response(ws)
            calls = [item for item in output if item.get("type") == "function_call"]
            if len(calls) != 1 or calls[0].get("name") != "get_active_task_status" or json.loads(calls[0]["arguments"]) != {}:
                raise RuntimeError("Expected the GUI's argument-free task-status tool.")
            await session._maybe_execute_tool_call(ws, {"item": calls[0]},
                                                  tool_executor=executor.submit_tool_blocking, on_state=None)
            reply, transcript, _ = await receive_response(ws)
            if not reply or not any(reply):
                raise RuntimeError("Task-status output did not receive a spoken response.")
            print("Spoken task status: " + transcript)
            print(f"Conversation, arbitrary URL intent and read-only GUI task status verified with {len(config.tools)} tools. No computer actions executed.")
    if not pcm or not any(pcm):
        raise RuntimeError("No non-silent PCM speech returned.")
    target = Path(__file__).resolve().parents[1] / "data" / "diagnostics" / "realtime-greeting.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(target), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(config.sample_rate)
        wav.writeframes(pcm)
    print(f"Speech received: {len(pcm) // 2} samples, {len(pcm) / 2 / config.sample_rate:.2f}s")
    print(target)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--conversation", action="store_true", help="Also make paid synthetic conversation and tool-intent checks; no microphone or actions.")
    parser.add_argument("--audio-greeting", action="store_true", help="Also synthesize a paid English greeting and verify audio input + semantic VAD; no microphone.")
    args = parser.parse_args()
    try:
        asyncio.run(asyncio.wait_for(check(args.conversation, args.audio_greeting), timeout=100))
    except Exception as exc:
        print(redact_sensitive_text(str(exc)).text)
        raise SystemExit(1)
