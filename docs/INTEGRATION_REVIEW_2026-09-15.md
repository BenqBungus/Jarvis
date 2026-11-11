# Integration Review: 2026-09-15

Reviewed the existing checkout, Claude's VOICE_STATUS.md and
INTEGRATION_REQUESTS.md, relevant voice implementations/tests, and the mobile
client README, package scripts and contract requests. There is no direct Claude
session connection: this verifies files and tests, not a currently running agent.

## Claude Deliverables Checked

- TTS initialization no longer leaves enabled=true when both the Windows fallback
  and the API key are unavailable.
- Classic final replies use the configured spoken-language argument.
- Realtime readiness checks the device table, not only whether sounddevice imports.
  Detection is not proof that the configured device/format will successfully open,
  that a key has usable quota, or that sound is audible.
- Tool failures emit a redacted, separate error signal; MainWindow supports
  persistent error feedback.
- Deterministic acceptance scenarios cover greeting, ten alternating turns,
  interruption, tool calls/errors, disconnect/fresh-session reconnect and shutdown.
- The mobile PWA has a mock/transport adapter, task states, cancellation and error
  handling. It is not connected to a real desktop companion server. Pairing,
  revocation and the remaining server contract are unfinished; mobile voice is off.

## Codex Integration Completed

Connected RealtimeVoiceWorker.tool_error_occurred to MainWindow.show_tool_error
in gui/app.py. Added a build_app integration regression, not merely a manually
connected worker/window test. It checks redaction and persistent error styling
through a listening-state update and a session polling tick.

Readiness detail now distinguishes missing websockets from unavailable audio
library/devices without incorrectly insisting that already-installed packages
must be installed again. The existing combined audio flag cannot distinguish a
missing library from a missing/failed device; the UI says so instead of guessing.
Both the main readiness description and the dependency row use the same result.

Claude integration request 1 is implemented. Request 2 is addressed within the
existing public readiness schema; richer device diagnostics remain in Voice Doctor.
No Claude-owned source/tests were edited. No safety confirmation was bypassed.

## Verification This Pass

- Voice, GUI integration/safety/speech and acceptance selection: 246 passed;
  2 existing third-party audio deprecation warnings.
- Execution/file/archive/workflow selection: 196 passed, 1 skipped.
- Mobile client: npm run test, 74 passed across 14 files.
- Mobile client: npm run typecheck, passed.

The first integration run found a test-cleanup error (calling hide on the tray
wrapper instead of its QSystemTrayIcon). Corrected in the Codex-owned test and
reran the affected selection successfully.

No paid API calls, real microphone capture/playback, personal-screen capture,
new background services or remote listeners were used. This was not a full-suite
release verification, new mobile browser E2E run, physical iPhone test or clean-PC
installation test. The distributable ZIP was not rebuilt.

## Readiness Assessment

Approximately 40% of the practical requested final assistant, as a rough engineering
estimate, not a measured acceptance percentage. The earlier 35-40% estimate now
has additional verified voice-component and PWA mock evidence; this does not prove
45% completion or movie-level autonomy. Test counts are not feature percentages.

The current file/execution verification increment and reported voice integration
requests are complete. Codex's broader roadmap is not complete: companion backend,
broader real-world task acceptance, richer coding/undo/context workflows and release
integration remain. Continuous natural conversation, echo/interruption on actual
hardware, live screen assistance and a usable phone-to-desktop connection must be
verified separately before they count as finished user experiences.
