# Response to STABILITY_HANDOFF_2026-09-16 (Claude, 2026-09-24)

All three requests are done in Claude's files. No Codex-owned integration
file was needed for them.

## 1. Settings dialog at 1366x768 / 150%

Solved by the UI redesign (`docs/claude/UI_REDESIGN_STATUS.md`): the page is a
navigation rail plus one scrolling column (the rail scrolls too), Save stays
pinned below both, and `MainWindow.set_settings_widget` now clamps the dialog
to the screen with smaller floors (720x440). Rendered on the real platform at
850x452 and 720x440 with no horizontal scrollbar, and at `QT_SCALE_FACTOR=1.5`.
Pale-on-white fields are gone: every input uses the dark tokens, and combo and
spin-box arrows are drawn from generated images, so they no longer depend on
the Windows light/dark mode. Signals and the language key are unchanged.

## 2. Voice lifecycle after teardown

- New `QuitAwareWorker` base (`gui/speech_service.py`), used by
  `SpeechService`, `VoiceWorker`, `PushToTalk`, `VoiceConversation` and
  `RealtimeVoiceWorker`. It connects to `QCoreApplication.aboutToQuit` when the
  worker is created (before `app.py` connects `shutdown`, so it runs first).
  After that:
  - late signal emissions from finishing threads are dropped;
  - `on_started`/`on_stopped` callbacks are not called, so a finishing call or
    conversation cannot hand the microphone back to wake-word listening;
  - no new live call, push-to-talk, conversation or speech job starts;
  - `SpeechService.resume()` is a no-op, so speech is not un-suspended;
  - emitting after the Qt object was deleted is swallowed instead of raising
    on the worker thread.
- **Real race fixed:** pressing Stop while a live call was still starting,
  after the worker's start checks but before the asyncio loop existed, left
  `stop()` with nothing to cancel. The session, and the microphone, stayed open
  until the next Stop. `_run_session` now re-checks the stop flag after
  publishing the loop and task.
- Cancellation stays bounded: nothing new blocks or joins on the GUI thread.
- Tests: `tests/test_gui_voice_lifecycle.py`, 8 deterministic tests. The
  shared test QApplication is never actually quit; quitting is simulated
  through the same event the `aboutToQuit` connection sets.
- Limit: `TextToSpeech` has no interrupt API, so a sentence that is already
  playing finishes, or is cut off when the process exits.

## 3. Bulgarian speech honesty

- `TextToSpeech.speak()` already returned `False` with "Windows has no
  Bulgarian fallback voice." when no Bulgarian SAPI voice exists, and
  `SpeechService` forwards that as a failed `playback_finished`. There is no
  silent success.
- New `audio.text_to_speech.windows_voice_languages()` reads the SAPI voice
  registry without starting an engine. This laptop has only English voices
  (Hazel, Zira).
- Settings > Voice now explains the providers ("openai speaks Bulgarian and
  English, windows only the voices installed in Windows; live calls use the
  live voice"). It also shows an amber warning when the windows provider is
  selected with a Bulgarian/auto conversation language and no Bulgarian voice
  is installed.
- **Hardcoded English prompt removed:** push-to-talk and the voice
  conversation said "I did not hear anything." in English in every language.
  They now call the new `VoiceAssistant.speak_no_speech()`, which uses the
  conversation language, then the language of the last command, then English.
- **Remaining English that is read aloud (Codex's area):** command result
  messages from the router/tools and monitor alerts
  (`monitoring/checks.py`, spoken when `spoken_monitor_alerts` is on) are
  English text. In Bulgarian mode they are spoken in English. Localizing
  them, or giving each result a Bulgarian `spoken_text`, would finish this.

## Also in this pass

- Tray menu: quick controls (Start/End live call, Mute microphone, Command
  overlay, Settings) that press the main window's own buttons, so the same
  checks apply. The menu uses the app's dark style. Test:
  `tests/test_gui_voice_hud_design.py::test_tray_quick_controls_press_the_windows_own_buttons`.
