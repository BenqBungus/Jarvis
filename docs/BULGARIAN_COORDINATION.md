# Bulgarian language coordination - 2026-09-16

Codex observes active Claude edits to audio/language.py and realtime.py.
There is no direct Claude session channel. This shared-file note is a handoff,
not proof that Claude has read it. Preserve TASK_SPLIT.md ownership.

Shared setting: settings.openai["conversation_language"], values en / bg / auto,
default en for existing users. This matches Claude's current Realtime config.

Codex is editing: user_settings.py (validated language accessor), ai_client.py
(all answer/analysis/planning prompts), vision/project_analysis.py (remove fixed
English), gui/app.py and cli.py (language integration), Codex-owned tests/docs.
Claude: please do not edit those files concurrently. Continue settings_page.py,
audio/, realtime.py, voice_assistant.py and your other existing voice/UI paths.

Integration request to Claude: provide public set_conversation_language(code)
on SpeechToText and VoiceAssistant for settings saves, or document the intended
setter before integration. Keep constructors backward compatible. SettingsPage
should save the key above and emit existing saved. For running calls, apply a new
language on the next session; do not tear down an active conversation silently.
Please report when the UI/voice increment is ready in docs/claude/.

Bulgarian operation names must still map to the same tool identifiers and safety
checks. Never translate paths, URLs, process selection IDs or JSON schema keys.
No live microphone/API tests or package rebuild while concurrent work continues.

Current integration: Codex passes the language into SpeechToText/VoiceAssistant
constructors, uses your greeting/speaker-test/display helpers, and passes shared
settings to ScreenChat. Settings saves update AI responses immediately and the next
Live config. app.py calls set_conversation_language if your public setters appear;
until then it explicitly tells users to restart for Classic. Your Settings tooltip
currently promises the next Classic command: please align it or provide setters.

Additional voice-side gap observed: audio/text_to_speech.py still has
DEFAULT_OPENAI_TTS_INSTRUCTIONS = "Speak English ...". Ensure Bulgarian TTS does
not retain that conflicting default/custom instruction, and document unavailable
Windows Bulgarian voices honestly. Static tool result messages remain partly
English; do not claim full localization of every status/error this pass.

Latest source checkpoint: Claude has now added both public setters and removed
the English-only TTS default. Codex connected these setters and tests immediate
Classic language updates; an in-flight Live call retains its configuration until
the next call. The notes above describe earlier observations, not remaining gaps.

Codex also added Bulgarian deterministic variants for document analysis/drafting,
file copy/move/rename/archive, recycling, process listing/closing and screen-chat
commands. They dispatch through the existing registry and permission policy.
Paths, filenames and tool protocols remain unchanged. No Claude-owned file was
edited by Codex. The settings selector was visually rendered offscreen; its long
dialog and low-contrast native fields remain UI polish concerns for Claude.

Verification: the focused core/integration regression ran 346 passed / 1 skipped.
An existing monitor callback emitted a deleted Qt signal warning after teardown;
this does not establish a clean full-GUI lifecycle. Live microphone quality,
Bulgarian pronunciation and provider connectivity still need user acceptance.
Some static tool/status/error strings are still English. No release ZIP rebuilt.

Final setter integration check: 109 passed across test_gui_language_integration,
test_ai_language, test_bulgarian_resource_commands, test_audio_language and
test_voice_assistant. Real Classic setters are exercised without microphone
construction; mocked provider tests do not verify actual speech recognition.
