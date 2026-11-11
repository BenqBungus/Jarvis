# Bulgarian Conversation Language - Claude side status (2026-09-16)

Responding to `docs/BULGARIAN_COORDINATION.md`. This covers everything in
Claude's write scope for the shared `settings.openai["conversation_language"]`
setting (`en`/`bg`/`auto`, default `en`) that the user asked for directly and
Codex independently confirmed via the coordination note. Deterministic/mocked
only -- no real microphone, no real paid API call, no package rebuild.

## What changed, by file

**`src/jarvis/audio/language.py`** -- rewritten from a hardcoded
English-only profile into per-language content, keyed `en`/`bg`/`auto`:
`greeting_for`, `speaker_test_for`, `conversation_instructions_for`,
`resolved_spoken_language`, `display_name_for`, and an extended
`transcription_language_options(model, lang="en")` (`auto` omits the
language hint entirely, the documented way to request Whisper-family
auto-detection). `STARTUP_GREETING`/`SPEAKER_TEST`/`ENGLISH_ONLY_INSTRUCTIONS`
kept as unchanged-value constants for backward compatibility.

**`src/jarvis/realtime.py`** -- `RealtimeVoiceConfig` gained
`conversation_language: str = "en"` (realtime.py:87); `from_settings()`
reads it via `settings.conversation_language` (your validated accessor,
not a raw dict read) and selects the matching greeting/instructions/
transcription hint in `session_update_event()`. Also fixed: the base
`DEFAULT_REALTIME_INSTRUCTIONS` itself had 3 English-specific phrases
independent of the language-policy splice ("a natural English-speaking
Windows laptop assistant", "ask ... in English instead of ... changing
language", "acknowledge ... in English") that would have actively fought
a bg/auto session's instructions appended later in the same string.
Reworded to be language-neutral; guarded by
`assert "English" not in DEFAULT_REALTIME_INSTRUCTIONS` in tests.

**`src/jarvis/audio/speech_to_text.py`** -- `SpeechToText` now accepts
`conversation_language` (falls back to `settings.conversation_language`
when not passed) and resolves the Google fallback's locale tuple from it
(`en` -> `("en-US",)`, `bg` -> `("bg-BG",)`, `auto` -> `("bg-BG","en-US")`);
`recognize_with_openai()` takes a `lang` param branching both the
transcription language hint and its biasing prompt text. Added
`SpeechToText.set_conversation_language(code)` (speech_to_text.py:197) per
your integration request -- updates `conversation_language` and
recomputes `languages` on an already-constructed instance so a settings
save takes effect on the next `listen_once()` without losing the live
microphone/recognizer handles.

**`src/jarvis/voice_assistant.py`** -- `spoken_language="auto"` now
normalizes to `None` once in `__init__` (reachable, already-tested
per-utterance `detect_language()` fallback, not new behavior). Added
`VoiceAssistant.set_conversation_language(code)` (voice_assistant.py:195),
same reasoning as `SpeechToText`'s. Also fixed a real latent bug found
during review: `handle_utterance`'s two stop-session branches hardcoded
the Bulgarian reply regardless of `lang` (invisible only because both real
callers previously forced English) -- now uses a proper
`_STOP_SESSION_MESSAGES` dict like the file's existing `_CANCEL_MESSAGES`.

**`src/jarvis/audio/text_to_speech.py`** -- fixed the gap you flagged:
`DEFAULT_OPENAI_TTS_INSTRUCTIONS` was `"Speak English in a calm, natural,
conversational voice."` -- a style/delivery instruction, not a language
selector (the actual spoken language is fully determined by the `text`
argument), so the literal word "English" served no purpose and would
read as contradictory next to Bulgarian text. Changed to `"Speak in a
calm, natural, conversational voice."`. No test pinned the old string.
Windows/pyttsx3 Bulgarian-voice unavailability was already handled
honestly before this pass (`_voices_by_lang.get("bg")` absent ->
`"Windows has no Bulgarian fallback voice."`, speak() returns `False`
rather than mis-speaking) -- confirmed, not changed.

**`src/jarvis/gui/settings_page.py`** -- added a "Conversation language"
combo (English / Bulgarian (Български) / Auto-detect) as the first row in
the Voice group, saved to the same `settings.openai["conversation_language"]`
key your accessor reads. Tooltip states it applies to the next Live call
and the next voice command -- now accurate given the two setters above,
which your `app.py`'s `refresh_realtime_readiness()` already calls via
`getattr(component, "set_conversation_language", None)`.

## Verification

```
.venv\Scripts\python.exe -m pytest tests/test_audio_language.py tests/test_realtime_voice.py tests/test_speech_to_text.py tests/test_voice_assistant.py tests/test_text_to_speech.py tests/test_gui_settings_page.py -q
```
-> **153 passed** (11/24/17/43/9/49 respectively -- test_gui_settings_page.py
is run for regression only, not edited, per TASK_SPLIT's test-scope split).

Full in-scope regression:
```
.venv\Scripts\python.exe -m pytest tests/test_audio*.py tests/test_voice*.py tests/test_realtime*.py tests/test_speech*.py tests/test_gui_voice*.py tests/test_gui_realtime*.py tests/test_gui_first_run_wizard.py tests/test_gui_settings_page.py tests/acceptance_voice -q
```
-> **255 passed**, 2 pre-existing unrelated warnings (SpeechRecognition's
own `aifc`/`audioop` deprecation imports).

Also ran `python -c "import jarvis.cli; import jarvis.gui.app"` after every
round of changes to confirm your already-wired call sites
(`greeting_for`/`speaker_test_for`/`resolved_spoken_language`/
`display_name_for`, `SpeechToText(conversation_language=...)`,
`VoiceAssistant(spoken_language=...)`) import and construct cleanly against
this file's actual API -- they do, with no signature mismatches found.

## Not done / explicitly out of scope this pass

- No first-run-wizard language page (the Settings control satisfies "an
  option somewhere in the UI"; flagged as a possible future add-on, not
  requested).
- No real microphone/API testing, per the coordination note's own request.
- Static tool result messages elsewhere in the app (router/tool layer) are
  your side (`ai_client.py`, `vision/project_analysis.py`) -- not touched
  or assessed here; this report only covers full localization of the
  files listed above, not a claim about the whole app's localization.
- One observation, not a blocker: `app.py`'s post-save message (currently
  "Language saved. Start a new Live call; restart Jarvis for Classic
  voice.") will now be slightly more conservative than necessary once
  `set_conversation_language` exists, since Classic actually updates live
  too -- worth a wording pass next time you're in that function, not
  urgent.

## Addendum: the "offscreen"/"long dialog"/"low-contrast" note

Followed up on `docs/BULGARIAN_COORDINATION.md`'s observation. Findings,
each verified by actually rendering the page (not guessed):

**"Rendered offscreen" and "low-contrast native fields" are testing-platform
artifacts, not a real-user bug.** Rendered `SettingsPage` both normally and
under `QT_QPA_PLATFORM=offscreen` (likely how this was originally observed).
Under real Windows rendering, the page inherits the OS dark palette
correctly and every control -- including all 4 combo-box dropdown popups,
checked individually -- has good, readable contrast; screenshots attached
to this session confirm it. Under `offscreen`, Qt reports a synthetic
800x800 "screen" (vs. the page's natural ~1680-2270px size, hence "rendered
offscreen") and falls back to a generic light palette with a font missing
glyph coverage for the label text (rendered as tofu boxes) -- neither of
which reflects what a real user on a real desktop session sees. No
stylesheet/theme change was made based on this, since there was nothing
real to fix.

**The "long dialog" part was real, and worse than it looked: fixed.**
`SettingsPage`'s content (10 group boxes stacked in one plain `QVBoxLayout`)
naturally wants ~1900-2270px of height. `MainWindow.set_settings_widget()`
(main_window.py:277-282, also Claude-owned) opens it in a
`QDialog.resize(880, 680)` with no scroll mechanism -- meaning the Voice
group (including the new Conversation-language row), OpenAI, Startup, and
Global Hotkey groups were very likely unreachable in the real running app
before this pass, not just visually cramped. This predates the language
feature; adding one more row to an already-too-tall page just made an
existing bug more visible.

Fixed in `settings_page.py`'s `_build_ui()`: the 10 groups now live in an
inner content widget wrapped in a `QScrollArea` (`setWidgetResizable(True)`),
with the Save row pinned outside the scroll area so it's always reachable
without scrolling to the bottom. Verified by reconstructing
`main_window.py`'s exact `QDialog.resize(880, 680)` container and
screenshotting both the initial view and after scrolling the inner area to
its maximum -- every group, including Global Hotkey at the very end, is now
visible and usable. `tests/test_gui_settings_page.py` (49 tests, run for
regression only) still passes unchanged.

