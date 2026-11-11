# Voice Reliability Status (Claude, first milestone)

Scope: `docs/CLAUDE_WORK_HANDOFF.md` / `TASK_SPLIT.md` "Active Split
(2026-09-14)" — voice reliability first, mobile PWA visual-parity work
paused until this is reported done. Everything below is deterministic and
mocked: no real microphone access, no real paid OpenAI API call, no test
against real hardware or network. See "Not performed this pass" at the
bottom.

## Confirmed problems and fixes

### 1. TTS readiness false positive (real bug)

`TextToSpeech.__init__` (`src/jarvis/audio/text_to_speech.py`), OpenAI
provider path: when `pyttsx3` failed to import, or imported but `.init()`
raised, both branches logged a warning and returned without ever setting
`self.enabled` — it stayed at the constructor default `True`. The
"STARTUP VOICE" readiness row could show ready with no working speech
engine and no `OPENAI_API_KEY`.

**Fix:** both branches now set `self.enabled = bool(os.getenv("OPENAI_API_KEY"))`
before returning (`src/jarvis/audio/text_to_speech.py:161`,
`src/jarvis/audio/text_to_speech.py:179`) — the same expression
`status_summary()` already used, so the row now reports honestly with no
`app.py` change needed.

**Verified:** `.venv\Scripts\python.exe -m pytest tests/test_text_to_speech.py -q` → **9 passed**.

### 2. English-preference gap in the final spoken reply

`VoiceAssistant.dispatch_command` spoke `result.message` with no `lang`
argument (`src/jarvis/voice_assistant.py:294`, before the fix), so the
final reply's spoken language was auto-detected from its own text instead
of forced to the configured `self._spoken_language`, unlike every other
prompt in the class.

**Fix:** `self._speak(result.message, lang)` (`src/jarvis/voice_assistant.py:294`).

**Verified:** `.venv\Scripts\python.exe -m pytest tests/test_voice_assistant.py -q` → **38 passed**.

### 3. Dead code removed; the real output-failure path is now actually tested

`_cancel_active_response()` and `_write_output_audio_safely()` in
`src/jarvis/realtime.py` had zero production call sites (confirmed by a
full-repo grep) and were deleted. The test that exercised
`_write_output_audio_safely` was replaced with tests at the three layers
that actually run when the output stream fails for real:

- `RealtimePlayback.callback()` catches the failure into `.error` instead
  of raising (`tests/test_realtime_playback.py`).
- `RealtimeVoiceSession._watch_playback()` turns a set `.error` into a
  `RuntimeError` (`tests/test_realtime_voice.py`).
- `RealtimeVoiceWorker` ends the call cleanly on that `RuntimeError`:
  reaches `state_changed("error")`, fires `on_stopped`, `running` becomes
  `False`, and the emitted detail is redacted — a fake `sk-...`-shaped
  secret in the exception text never reaches the UI
  (`tests/test_gui_realtime_worker.py`).

This confirms the existing fail-fast design was already safe; it just had
no direct test coverage before.

### 4. Readiness now checks for an actual usable audio device, not just an importable module

`readiness()` (`src/jarvis/realtime.py:271`) previously reported
`audio_stream_available` as `True` whenever the `sounddevice` package was
merely importable, regardless of whether the machine has any working
input/output device.

**Fix:** added `_audio_devices_available()` (`src/jarvis/realtime.py:812`):
after confirming `sounddevice` imports, calls its `query_devices()` — a
pure PortAudio device-table read that opens no stream and captures/plays
nothing — and requires at least one device with `max_input_channels > 0`
and one with `max_output_channels > 0`. Wired into `readiness()` in place
of the bare import check.

**Verified:** `.venv\Scripts\python.exe -m pytest tests/test_realtime_playback.py tests/test_realtime_voice.py tests/test_realtime_transport.py tests/test_gui_realtime_worker.py -q` → **53 passed** (covers fixes #3 and #4 together).

**Near-miss caught during this fix, worth recording:** this change broke
`tests/test_realtime_transport.py::test_server_disconnect_cancels_audio_sender_and_releases_devices`,
whose `sounddevice` fake had no `query_devices` — `run_stream()`'s own
internal readiness gate then failed. Missed initially because only the
file with the new readiness tests was re-run, not the sibling file that
also mocks `sounddevice` and also calls `run_stream()` directly. Fixed by
adding `query_devices` to that fake. Lesson applied for the rest of this
pass: after any change to a shared function like `readiness()`, do a full
in-scope regression run rather than trusting "the tests I think are
affected" (see the final regression run below, which exists specifically
because of this).

There is a small, known, one-directional side effect of this fix: the
`"sounddevice"` entry in `readiness()["missing"]` (and `app.py`'s
"install websockets and sounddevice" detail text) no longer distinguishes
"not installed" from "installed but no usable device found." Filed in
`docs/claude/INTEGRATION_REQUESTS.md` (item 2) as a cosmetic, non-blocking
follow-up since it's display text in `app.py`.

### 5. Real cross-component mic-lock contention test

The shared `threading.Lock()` design (classic voice acquires per ~1s
audio chunk; Realtime holds it for the whole call via a 0.1s-poll acquire)
was already implemented and unit-tested per side, but only against
isolated fakes — nothing proved a real `VoiceWorker` and a real
`RealtimeVoiceWorker` actually cooperate under `app.py`'s real
coordination shape (`on_started`/`on_stopped` pause/resume).

**Added:** `tests/test_gui_voice_realtime_mic_lock.py` — both real worker
classes, one real lock, a shared activity tracker (not each side's own
counter) recording `max_concurrent`. Starts `VoiceWorker` listening,
starts `RealtimeVoiceWorker` mid-listen, asserts `voice_worker` actually
pauses and resumes and the tracker never observed more than one side
active at once.

**Verified:** `.venv\Scripts\python.exe -m pytest tests/test_gui_voice_realtime_mic_lock.py tests/test_gui_voice_worker.py tests/test_gui_realtime_worker.py -q` → **31 passed**. Confirmed stable across 5 consecutive runs during development (no flakiness observed).

### 6. Tool errors during a call were invisible / looked routine

`RealtimeVoiceWorker._on_realtime_state`'s `"tool_error"` branch only
emitted `detail_changed`; since the live state stayed
`listening`/`thinking`/`speaking` (not `"error"`), `MainWindow` rendered a
genuine backend failure as ordinary status text that auto-clears after
~9 seconds, indistinguishable from something that worked.

**Fix:** added `tool_error_occurred = Signal(str)`
(`src/jarvis/gui/realtime_worker.py:34`), emitted alongside (not instead
of) `detail_changed` in the `tool_error` branch
(`src/jarvis/gui/realtime_worker.py:180-191`) — today's behavior is
unchanged until the new signal is connected. Added
`MainWindow.show_tool_error(message)`
(`src/jarvis/gui/main_window.py:355`), which calls
`self.show_feedback(message, error=True)` — the same persistent,
error-styled feedback regular command failures already get.

**This needs a one-line `app.py` change Claude cannot make** — filed as
item 1 in `docs/claude/INTEGRATION_REQUESTS.md`.

**Verified:** `.venv\Scripts\python.exe -m pytest tests/test_gui_realtime_worker.py tests/test_gui_realtime_tool_error_display.py -q` → **13 passed**.

### 7. `tests/acceptance_voice/` — full 6-scenario deterministic scaffold

New directory, one scenario per module, each driving the public surface
(`RealtimeVoiceSession.run_stream()` / `RealtimeVoiceWorker`) through a
scripted end-to-end sequence rather than one isolated mechanism:

- `test_greeting.py` — greeting sent exactly once with the right
  instructions/tool_choice; no greeting when configured empty; a second
  independent session doesn't replay it.
- `test_ten_alternating_turns.py` — ten consecutive user/assistant turns
  on one continuous stream with no stuck `_response_busy`, no duplicate
  `response.create`, correct per-turn speaker attribution.
- `test_interruption.py` — automatic barge-in truncates the right item,
  reaches `"interrupted"`, and a late audio delta for the
  now-interrupted item/response is never enqueued into playback.
- `test_tool_request.py` — successful tool round-trip; a raising tool
  executor reports a failed result rather than crashing; invalid JSON
  arguments are rejected before the executor runs; connects to fix #6's
  signal end-to-end. (Calls `_respond_to_tools`/`_maybe_execute_tool_call`
  directly rather than through a full `run_stream()` scenario — see that
  file's docstring: `_receive_events`'s own `finally` block cancels any
  still-pending tool task once the event stream ends, which would make a
  full-stream scripted race inherently flaky, not a meaningful signal.)
- `test_disconnect_reconnect.py` — a dropped connection propagates as a
  clean, catchable `ConnectionError`; a fresh session afterward reconnects
  normally with no leftover state from the previous, failed call.
- `test_shutdown.py` — `RealtimeVoiceWorker.stop()` called mid-call (a
  still-open connection, not one that already ended on its own) ends the
  background thread cleanly with no `"error"` state and no escaping
  exception, and releases the shared mic lock for a waiting classic-voice
  side.

**Verified:** `.venv\Scripts\python.exe -m pytest tests/acceptance_voice -q` → **15 passed**.

## Final full in-scope regression

```
.venv\Scripts\python.exe -m pytest tests/test_audio*.py tests/test_voice*.py tests/test_realtime*.py tests/test_speech*.py tests/test_gui_voice*.py tests/test_gui_realtime*.py tests/test_gui_first_run_wizard.py tests/acceptance_voice -q
```

**Result: 176 passed, 2 warnings** (the 2 warnings are pre-existing
`DeprecationWarning`s from the third-party `speech_recognition` package
importing stdlib `aifc`/`audioop` — unrelated to any change in this pass).

## Not performed this pass

- No real microphone was opened; no real speaker output was played.
- No real OpenAI API call was made (no Realtime API cost incurred).
- No live latency measurement of any kind.
- No test ran against real audio hardware or a real network connection.
- The 6 acceptance scenarios above are deterministic/mocked only. Running
  them against real hardware and a live API is a separate, later step
  that needs the user's explicit consent first, per the handoff doc.

## Observed, not fixed this pass (filed for awareness, not action)

- **Automatic barge-in asymmetry:** server-VAD-triggered interruption
  truncates local playback and tells the server what was actually heard,
  but never explicitly sends `response.cancel` — only the manual
  button/keyword interrupt does. It relies entirely on the session's own
  `interrupt_response: true` config. No stale audio can play either way
  (a separate item/response-id filter drops any further deltas for a
  truncated turn regardless of this), so this is a possible-wasted-
  server-generation robustness question, not a correctness bug.
  `tests/acceptance_voice/test_interruption.py` deliberately does not
  assert on `response.cancel` presence for this path, leaving it open
  rather than locking in either behavior.
- **Mic keeps streaming during a pending safety-confirmation dialog** in
  Realtime mode. Verified safe as-is: there is no coupling between voice
  input and `GuiSafetyPolicy`'s confirm queue, so a spoken "yes" cannot
  resolve a pending dialog. But there is also no mute-while-pending
  behavior, and adding one would need a new signal from `gui_safety.py`,
  which is Codex's file — flagged as a possible future enhancement, not
  implemented.
