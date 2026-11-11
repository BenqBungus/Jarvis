# Claude Code: Jarvis Mobile Companion

Read TASK_SPLIT.md first. Its active split now also assigns voice/UI work to Claude;
see docs/CLAUDE_WORK_HANDOFF.md. This document describes ONLY the PWA assignment.
For PWA work, stay in the client write scope. Do not rebuild Jarvis from scratch or
change root dependencies, shared contracts or installer. Voice reliability is the
first milestone; the PWA follows it unless the user changes priorities.

## First Deliverable

The user selected PWA on 2026-09-13. Build a mobile-first web/PWA companion in
clients/mobile-web/. A native iOS client is a later option, not this assignment. Keep an isolated
dependency manifest, lockfile and tests inside the client directory.

The first screen is the usable assistant, not a marketing landing page. Include
connection state, conversation, push-to-talk controls with clear unavailable and
permission-denied states, and task progress/cancel. No invented CPU temperatures
or fake successful system actions. Show a visible Mock mode label when using fixtures.

Read contracts/companion-v1.json. Implement a transport adapter and a mock adapter
behind the same client interface; put contract requests in clients/CONTRACT_REQUESTS.md.
The backend is not live yet. Do not invent live routes or write your own system
command executor. API keys for OpenAI must never be embedded in client bundles.

## Architecture and Limits

- The Windows agent owns local files, apps, diagnostics and permission enforcement.
- Phone/browser sends text tasks and shows structured results; it does not gain
  unrestricted iOS filesystem/system privileges.
- The laptop must be online for laptop operations. Show offline honestly.
- Voice transport and phone image uploads are a later protocol extension; local
  UI may be built but disabled until the capabilities response enables them.
- No full desktop stream or confidential screenshot transmission by default.
- Remote transport must eventually use authenticated HTTPS with explicit pairing,
  expiring/revocable device authorization and exact-origin rules. No insecure
  API-token-in-URL design, no wildcard credentialed CORS, no public open port.
- First remote release should keep destructive actions and project execution
  approval on the desktop. Client text cannot grant a project root or full access.

## Acceptance

Test iPhone-sized viewports, keyboard resize, safe areas, offline/reconnect,
duplicate submit prevention, cancellation, server errors and reduced motion.
PWA app-shell caching must not cache keys, transcripts or API responses. Provide
local run instructions and record which checks were simulated and which ran on
an actual iPhone. For native iOS, separately document signing/build/TestFlight
requirements; an Xcode project alone is not an installable tested iPhone app.

Report changed files and remaining backend integration needs in the client folder.
Do not edit or overwrite Codex's concurrent work.
