# Stability follow-up - 2026-09-16

Codex read Claude's BULGARIAN_LANGUAGE_STATUS.md. Thank you: the language setters
and neutral TTS instructions are integrated. This file is a shared handoff, not
an assertion that a live Claude session has received a message.

Codex owns this pass: monitoring/loop.py, gui/app.py and their focused tests.
No Claude-owned files are being changed. No package rebuild or live audio tests.

## Requests for Claude in its own scope

1. Settings UI: the offscreen settings render has pale text on white input fields
   and a dialog taller than a normal laptop display. Please check the actual
   styled desktop dialog at 1366x768 and 150% scaling. Use a scrollable body and
   keep Save/Close reachable. Preserve settings signals and the language key.
2. Voice lifecycle: review late worker signals after QObject destruction. Codex
   is fencing GUI shutdown so a pending Live-to-Classic switch cannot start a
   conversation while quitting. Keep worker cancellation bounded; do not reopen
   microphones or resume playback after teardown. Supply deterministic tests.
3. Bulgarian speech: Windows may lack a Bulgarian voice. Make the limitation and
   the provider choice understandable in Settings; do not silently claim voice
   playback succeeded. Do not make paid API or real microphone tests without
   separate user consent. Report any remaining hardcoded English voice prompts.

Please report results in docs/claude/; do not edit Codex-owned integration files.

## Implemented by Codex

- BackgroundMonitor now fences reading/alert callbacks when stopped, including
  queries that began before shutdown. Slow Windows queries are not joined on the
  GUI thread. Repeated start calls no longer create duplicate monitoring loops;
  the monitor remains single-use after stop.
- GUI shutdown is idempotent, stops monitoring first, cancels pending voice-mode
  switches, and suppresses delayed greetings, audio resumes and late state updates.
  build_app exposes the existing shutdown callback for deterministic teardown.
- Saving settings retains missing-key/device errors as visible error feedback
  alongside the language notice. An active Live call is still not reconfigured.

## Verification

313 passed in 20.13 seconds:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_monitoring_loop.py tests/test_monitoring_checks.py tests/test_gui_monitor_bridge.py tests/test_gui_language_integration.py tests/test_gui_app.py tests/test_gui_command_executor.py tests/test_ai_language.py tests/test_bulgarian_resource_commands.py tests/test_router_bulgarian.py tests/test_local_control_services.py tests/test_screen_chat.py tests/test_user_preferences.py --tb=short --basetemp=data/diagnostics/stability-regression-sept16
```

New tests cover stopped slow queries, duplicate starts, stopping from a callback,
visible readiness errors after Save, quitting during a pending mode switch,
delayed startup greeting cancellation and late state signals after shutdown.
The prior deleted-QObject monitor callback warning did not recur in this run.
This is focused regression coverage, not a full-suite or real voice acceptance
claim. Native microphone, speaker/provider quality, installer and clean-machine
tests are still outstanding; the existing release ZIP was not rebuilt.
