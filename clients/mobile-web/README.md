# Jarvis Mobile Companion

A mobile-first PWA that talks to the Jarvis companion server described in
[`../../contracts/companion-v1.json`](../../contracts/companion-v1.json).
There is no real server yet (`"implementation_status": "design_only_no_server"`),
so this app runs against an explicit, clearly-labeled **mock adapter** by
default. It never invents CPU/GPU telemetry or a fake "your laptop did X" —
every piece of mock text says outright that it's a simulation.

This client does not touch `src/jarvis/` (the Windows desktop app/backend),
`contracts/companion-v1.json`, or anything at the repo root — it's fully
self-contained: its own `package.json`, lockfile, and tests live in this
directory.

## Stack

Vite + TypeScript + Preact, `vite-plugin-pwa` for the service worker,
Vitest + `@testing-library/preact` for unit/component tests, Playwright for
device-emulation acceptance tests.

## Local run

```powershell
npm install
npm run dev              # dev server with hot reload, mock mode by default
```

```powershell
npm run build             # production build (tsc typecheck + vite build)
npm run preview           # serve the production build locally
```

```powershell
npm run test               # Vitest: reducers, backoff, adapters, components
npm run test:watch
npm run test:e2e           # Playwright: iphone-webkit, iphone-se-webkit, mobile-chromium
```

`npm run test:e2e` builds and serves the app itself (see `playwright.config.ts`'s
`webServer`) — you don't need `dev`/`preview` running first.

### Switching to a real server, once one exists

Copy `.env.example` to `.env.local` and set:

```
VITE_COMPANION_MODE=transport
VITE_COMPANION_BASE_URL=https://your-real-server
VITE_COMPANION_DEV_TOKEN=<a real paired-device token, once pairing exists>
```

There is no pairing protocol yet (see
[`../CONTRACT_REQUESTS.md`](../CONTRACT_REQUESTS.md)#1), so there is nowhere
real to get a token today. In a dev server (`npm run dev`) only, you can also
override per-tab with `?mode=mock` or `?mode=transport` in the URL; this
override is inert in production builds by design (`select-adapter.ts`) so a
shipped build can never be redirected at a real endpoint by a crafted link.

## Architecture

- `src/contract/types.ts` mirrors `companion-v1.json` field-for-field.
- `src/companion-client/client.ts` is the one interface both adapters
  implement (`mock-adapter.ts`, `transport-adapter.ts`); `select-adapter.ts`
  is the single place that picks between them.
- `src/state/*-reducer.ts`: three independent state machines (connection,
  task lifecycle, mic/push-to-talk gating), composed under one
  `AppStateProvider` (`src/state/app-state.tsx`).
- `src/hooks/useTaskPolling.ts` owns submit/poll-with-backoff/cancel/retry;
  `src/hooks/useOnlineStatus.ts` owns the capabilities fetch, the status
  heartbeat, and reattaching to an in-progress task after a page reload.
- No `localStorage`/`sessionStorage` use in this version — conversation and
  task state live in memory only, and reload-recovery comes from asking the
  backend (`GET /v1/status`) what's active rather than persisting anything
  locally. There's no real pairing/token flow yet to make persistence worth
  the risk; see `CONTRACT_REQUESTS.md`#1.

## What "Mock mode" actually guarantees

Every response the app renders in mock mode is produced by
`src/companion-client/mock-adapter.ts`, entirely in memory, with **zero**
network requests. The task lifecycle is deterministic and chosen by
substring-matching the submitted text (see the adapter's own comments for
the exact triggers: default/`"approve"`/`"fail"`/`"flaky"`), so the same
input always produces the same simulated outcome. The `MockModeBadge`
component renders whenever `client.mode === 'mock'` and nothing else — it
can't disagree with what's actually wired up.

## Acceptance-bar verification

Everything below ran from this environment, which has no physical iPhone
attached. Playwright's `webkit` project is a real WebKit browser engine —
the closest available proxy for iPhone Safari — but it is still emulation on
a desktop OS, not Mobile Safari on real hardware. Re-verify the
hardware-dependent rows on an actual iPhone before shipping.

| Acceptance item | How it was checked | Physical-hardware caveat |
|---|---|---|
| iPhone-sized viewports | Playwright `iphone-webkit`/`iphone-se-webkit` projects (`e2e/iphone-viewports.spec.ts`) | Real WebKit engine, not real Mobile Safari on real hardware |
| Safe-area insets | `e2e/iphone-viewports.spec.ts` confirms the `--safe-*` CSS custom properties are defined and used (`env(safe-area-inset-*)`) | Cannot confirm actual non-zero inset values without real notch/Dynamic Island hardware |
| Keyboard resize | `e2e/keyboard-resize.spec.ts`: confirms `100dvh` (not legacy `100vh`) is used, and a synthetic viewport shrink doesn't break layout | **Approximation only** — no real on-screen keyboard exists in this environment; `visualViewport.resize` from a real iOS keyboard is unverified |
| Offline/reconnect | `e2e/offline-reconnect.spec.ts`, `context.setOffline()` | Fully real browser-level network state; not hardware-dependent |
| Duplicate-submit prevention | `e2e/duplicate-submit.spec.ts` (disabled-composer case + same-tick double-click case), plus Vitest unit coverage | Not hardware-dependent |
| Cancellation | `e2e/cancellation.spec.ts` | Not hardware-dependent |
| Server errors | `e2e/server-error.spec.ts` (`"fail"`/`"flaky"` mock scenarios), plus `transport-adapter.test.ts`'s real-shaped error mapping | Not hardware-dependent |
| `prefers-reduced-motion` | `e2e/reduced-motion.spec.ts`, `page.emulateMedia()` | Fully real media-query emulation; not hardware-dependent |
| Add to Home Screen | Not automated — iOS Safari never fires `beforeinstallprompt`, so there is no programmatic install flow to test; a manual "Add to Home Screen via Share" hint is shown on iOS Safari only | **Unverified** — needs a real iPhone |
| Real permission-prompt UX | `e2e/mic-permission-gating.spec.ts` confirms the button is disabled and wires no click handler under today's real `voice:false` contract | Since voice is off today, there is nothing to test on real hardware yet either |
| Service worker caching (`/v1/*` never cached) | Build-output grep (`dist/sw.js` contains the `NetworkOnly` rule and a precache list of app-shell files only) + interactive smoke check confirming zero real network calls in mock mode | Not hardware-dependent |

Also manually smoke-tested interactively (this environment's Browser tool,
375×812 viewport): submit → queued → running → completed, `"fail"` →
error state with Retry/Dismiss, Cancel mid-task → cancelled, `MockModeBadge`
visible throughout, and `read_network_requests` confirmed **zero** requests
to any `/v1/*` path or any origin other than the app's own dev server across
all three flows.

## Remaining backend integration needs

See [`../CONTRACT_REQUESTS.md`](../CONTRACT_REQUESTS.md) for the full,
field-by-field list. In short: a real pairing/token protocol, a typed
`TaskResource.result` shape, a complete `error.code` enum, and a CORS policy
are all needed before `transport-adapter.ts` can be pointed at a real
server instead of the mock.
