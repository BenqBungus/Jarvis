# Contract Requests — from clients/mobile-web

Read against `contracts/companion-v1.json` (`contract_version: "0.1-draft"`,
`implementation_status: "design_only_no_server"`) while building the mobile
companion client. These are gaps found by implementing a real transport
adapter and a faithful mock adapter against the contract as written, not
speculative feature requests — each is traceable to a specific field or
missing field below. Nothing here blocked the client build; the mock
adapter's shape is deliberately deterministic so the client works today and
these are exactly the questions that need answers before `transport-adapter.ts`
can be pointed at a real server.

1. **Pairing protocol is undefined.** `transport.pairing` says
   `"desktop-approved; transport details pending"` — there is no token
   format, issuance flow, expiry, or refresh mechanism yet. The client's
   `TransportConfig.token` is currently just a placeholder read from an env
   var (`VITE_COMPANION_DEV_TOKEN`), with nowhere real to get one.

2. **No device-revocation endpoint.** If a phone is lost or a token leaks,
   there's no `DELETE`/revoke call in the contract to invalidate it from the
   desktop side.

3. **`TaskResource.result` is untyped.** The only example shows `result:
   null`. The client currently renders a completed result with
   `String(result)` as a last resort — there's no schema to render it more
   richly (e.g. structured fields, file references) without guessing.

4. **`error.code` enum is incomplete.** Only `desktop_approval_required`
   appears in the example. The client's error-mapping (`errors.ts`) has no
   way to give each real code distinct copy/retry behavior without a full
   list.

5. **`GET /v1/status`'s `state` field isn't enumerated.** Task `states` is a
   closed list; status `state` only ever shows `"idle"` as an example. Is
   there a fixed set (e.g. `idle`/`busy`/`error`) the client should render
   specially?

6. **No documented behavior for exceeding `text_characters: 3000`.** Is
   this enforced server-side with a specific error code, or purely a
   client-side limit? The client currently just truncates before sending
   and has no server-side confirmation this is the intended behavior.

7. **`revision`'s monotonicity isn't confirmed.** The client's poll-backoff
   design (`backoff.ts`, `useTaskPolling.ts`) treats an unchanged `revision`
   as "nothing new to report" and backs off accordingly. This only works if
   `revision` is guaranteed to strictly increase per task and is never
   reused — worth an explicit confirmation.

8. **No rate-limit signal.** Nothing in `error_example` or `security`
   covers a `429`/`Retry-After`-style response for submit or poll traffic.

9. **No CORS policy stated for a browser client.** The brief promises
   "exact-origin CORS rules" eventually; the contract itself is silent on
   what origin(s) a real server will allow, which matters specifically
   because this is a browser-based client, not a native app.

10. **No endpoint to list approved `project_id` grants.** The client always
    sends `project_id: null` today — there's no way to offer a picker for
    "which of my approved projects" without a listing endpoint.

11. **No task-listing endpoint.** After a reload, the client's only way to
    recover an in-flight task is `GET /v1/status`'s `active_task_id` (see
    `useOnlineStatus.ts`'s reconnect-on-load logic) — please confirm that
    field is intended for exactly this purpose, since without it (or a
    `GET /v1/tasks` list) a refreshed page loses track of anything running.

12. **Interim transport for `future_extensions`'s "incremental task
    events."** The contract already flags this as coming later. Is
    polling-with-backoff (what the client does today) the intended
    approach until then, or is SSE/WebSocket close enough to plan the
    client's polling layer to be swapped out rather than extended?
