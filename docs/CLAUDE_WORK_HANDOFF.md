# Claude Code: Voice Reliability and Companion UI

Continue the existing Jarvis project; do not recreate it. Read TASK_SPLIT.md and
respect the exact active write scope. Codex owns execution/safety/context/backend
and release integration. You own the listed audio/Realtime/voice UI modules and
the mobile PWA. No cross-owner edits without a recorded handoff.

## First Milestone: Reliable Voice

1. Diagnose the current pipeline before changing it. Add or improve checks for
   microphone selection, speaker selection, device disconnects, permission failures,
   missing dependencies and API readiness. Never show "ready" solely because an
   import succeeds. Keep API credentials out of reports and UI logs.
2. Verify one microphone owner at a time across classic voice and Realtime. Handle
   reconnect, stop/start and shutdown without overlapping streams or stopped-stream
   writes. Preserve the configured English conversation preference.
3. Improve "Jarvis"/"stop" interruption: stop queued speaker audio, update server
   playback state as appropriate, return to listening and avoid replaying a stale
   answer. Measure latency in the test report instead of promising instantaneous
   interruption. Do not interpret ordinary spoken commands as approvals.
4. Make listening/thinking/speaking/error states and the recognized utterance
   visible in the existing minimal UI. Preserve system status/readiness and the
   user's orb-centered design. Avoid another unrelated dashboard redesign.
5. Write deterministic audio/provider fixtures first. Then prepare opt-in real
   microphone/conversation acceptance scenarios: greeting, ten alternating turns,
   interruption, tool request, disconnect/reconnect and app shutdown. Real API use
   incurs cost; microphone/personal-screen access needs explicit consent. Clearly
   mark scenarios not performed and do not report simulated voice as a live test.

## Integration Boundaries

- Keep current public methods and Qt signals compatible. Do not change the tool
  registry, permissions, dispatcher, memory schema or shared settings persistence.
- Report required wiring/settings/dependency changes in
  docs/claude/INTEGRATION_REQUESTS.md, including the expected interface and tests.
  Codex applies changes to gui/app.py, root dependencies and backend files.
- Preserve out-of-queue cancellation, audit events, completed-turn history and
  tool result semantics. Do not bypass safety because the request came by voice.
- Run focused tests only while Codex is modifying other modules. Before a release,
  agree on a source freeze so Codex can run all tests and rebuild one package.
- Report changed files, exact test commands/results, remaining issues and any
  measured live latency in docs/claude/VOICE_STATUS.md. Never include credentials.

## Second Milestone: PWA

Follow docs/CLAUDE_MOBILE_HANDOFF.md and contracts/companion-v1.json. Build in
clients/mobile-web/ with isolated dependencies. Codex owns the authenticated
Windows server and pairing; do not implement a competing server or command router.
Until the backend is verified, label mocks and unavailable features honestly.

## Release Acceptance

After Codex provides a frozen standalone ZIP, prepare/run a clean-machine checklist
covering extraction, first-run setup, launch without Python installed, device
selection, voice errors, shutdown and removal. Actual tests on another machine
must be distinguished from this laptop's package smoke checks. Do not buy signing
certificates, publish builds or enable remote access on the user's behalf.
