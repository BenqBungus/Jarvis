# UI Redesign "Aurora" — Status (2026-09-23)

The user asked for a full rewrite of the desktop UI: modern and stylish.
Every surface Claude owns now shares one dark design system; public APIs,
signals, widget attributes and texts that tests or `app.py` rely on are
unchanged.

## What changed

| File | Change |
|---|---|
| `src/jarvis/gui/voice_core.py` | The design system: `AURORA` color tokens, per-role font lists (`FONT_BODY`, `FONT_SEMIBOLD`, `FONT_DISPLAY`, `FONT_MONO`), the neutral global `BASE_STYLE`, `card_rules(scope)`, crisp glyph icons (`glyph_icon`, Segoe Fluent Icons -> MDL2 Assets -> Codex's `control_icon()` fallback, 2x pixmaps), `LogoMark`, `apply_window_corners()` (Windows 11 DWM rounded corners + hairline border for frameless windows), the cached ambient `HudSurface` (now takes optional `glows`), and the new voice orb `JarvisCoreWidget` (~1.0 ms/frame, was ~2.3 ms). Combo and spin-box arrows are small generated chevron PNGs (1x/2x/3x) written once to `%TEMP%\jarvis-ui` because only `.py` files ship; if that folder isn't writable the native arrows are used. |
| `src/jarvis/gui/main_window.py` | New layout: brand + status pill + clock + grouped ghost toolbar (screen-share toggle with status dot), `SYSTEM STATUS` and `READINESS` cards, the orb as the centerpiece, state caption, transcript line, pill-shaped control dock (mute / gradient call button / interrupt / cancel), voice profile line. Settings dialog shell with title, subtitle, "Audio tools" menu and Close. |
| `src/jarvis/gui/settings_page.py` | Navigation rail (icon entries that scroll to each section and follow the scroll position) beside one column of section cards; sections reordered by importance (Voice, OpenAI, Safety, Browser, Website aliases, App aliases, Gaming, Mode volumes, Temperature, Startup, Global hotkey). Rows are "title + hint on the left, control on the right"; checkboxes are drawn as switches (`_ToggleSwitch` is still a `QCheckBox`). Save is the primary button, `Ctrl+S` saves, "Saved." clears after 4 s. Long audio-device names no longer force a ~650 px minimum width. New additive API `add_account_action(widget)`; `app.py`'s existing `layout().insertWidget(0, gmail_button)` is routed to the same "Accounts" area. |
| `src/jarvis/gui/overlay.py` | Command palette look: state dot + state label, segmented mode switch (the hidden `mode` combo stays the source of truth), large input with a leading sparkle, round gradient send button, result area with ok/error/pending tones, key hints footer. Opaque frameless window, rounded by DWM on Windows 11. |
| `src/jarvis/gui/splash.py` | 560x380 card: the real voice orb (thinking -> ready), `J.A.R.V.I.S` wordmark, tagline, sentence-case stage, percent, gradient progress bar. `_bar`, `_status`, `_progress`, `finish()` semantics unchanged. |
| `src/jarvis/gui/first_run_wizard.py` | Still ClassicStyle with exactly 8 pages; stepper side rail that follows the current page, larger page titles, Next/Finish as primary buttons, "Save key" beside the key field, wake phrases shown as chips, permission rows tinted by result (the ✓/✗ text contract is unchanged). |
| `src/jarvis/gui/tray.py` | Tray icons are the orb mark tinted per state (idle = brand gradient, listening green, processing violet, unclear amber, warning coral), drawn natively at 16/20/24/32/48/64 px. API and menu texts unchanged. |
| `tests/test_gui_voice_hud_design.py` | New, 24 tests (20 on 2026-09-23, 4 for the HUD upgrade: load chart, header verdict, orb boot sweep, overlay sweep): every stylesheet parses (Qt parse warnings captured) and keeps its scoped selectors; the global sheet stays neutral; glyph icons fall back without icon fonts; arrow PNGs are valid at every density; the orb center is bright in all 6 states (sampled from `window.grab()`); settings navigation scrolls and follows scrolling; the Gmail insert lands in the rail; switches are still checkboxes and click anywhere; status lines only take space with text; overlay switch mirrors the combo; splash stage text; wizard stepper follows pages; tray icon sizes. |

## HUD upgrade (2026-09-24)

The user asked for the design to be "even cooler", in the spirit of Tony
Stark's J.A.R.V.I.S.:

- **Orb HUD layers** (`voice_core.JarvisCoreWidget`): a slowly turning
  instrument dial (120 ticks, cached path), a segmented "arc reactor" ring
  that counter-rotates (faster while thinking), four reticle marks, and a
  72-bar radial voice spectrum whose height follows the real audio level
  (the per-bar wave only shapes it). The rings sweep in over 1.4 s the first
  time the orb is shown; the sphere itself is always drawn in full. Cost:
  1.2 ms/frame idle, 2.0 ms speaking at a sustained level (1030x552), still
  below the original ~2.3 ms.
- **Holo dot matrix** behind the orb (`HudSurface(pattern=True)`): one path
  fill plus a radial alpha mask, rendered once per window size.
- **Live load chart** in SYSTEM STATUS: CPU/GPU/RAM traces fed only by the
  monitor readings already sent to `update_dashboard` (last 48 points).
- **Header verdict**: "ALL SYSTEMS NOMINAL" / "N CHECK(S) NEED(S) ATTENTION"
  / "STANDING BY", summarising the readiness checks with a tooltip.
- **Overlay**: a light sweep runs along the top edge while a typed command is
  pending or the voice state is "processing".
- **Voice persona** (`realtime.py`): Jarvis now speaks as a composed, witty,
  proactive chief of staff and acts as an expert gaming coach, using only
  registered tools (a test fails if a named tool disappears).

## Verification

- Full suite (2026-09-24), run with a non-private temp folder
  (`--basetemp=data\diagnostics\pytest-tmp`, see `INTEGRATION_REQUESTS.md`
  #7): **1737 passed, 6 skipped, 2 failed** after the HUD upgrade (1732 before
  its 5 new tests); the two failures are Codex test wording drift in
  `test_ai_client_traces.py`. The "12 pre-existing failures"
  reported below, and a full-suite hang in `test_screen_chat.py`, turned out
  to come from pytest's default temp folder living under AppData, which the
  private-path guard now rejects — not from the UI.
- Checkpoint suite with the same temp folder, after the HUD upgrade:
  **393 passed, 0 failed**.
- Earlier (2026-09-23, default temp folder): checkpoint suite (Codex GUI tests + Claude voice/realtime/wizard tests +
  `tests/acceptance_voice/`): **328 passed, 12 failed**. The 12 failures are
  pre-existing and unrelated to the UI (Codex backend:
  `test_collaborative_assistance.py` x9 "Edit proposal rejected (ValueError)",
  `test_screen_ocr_access.py` recycling x3 "Private configuration and system
  folders need separate review.") — identical before the redesign started.
- `tests/test_gui_voice_hud_design.py`: 20 passed. Sanity-checked that the
  parse test really catches a broken sheet and that the orb threshold is far
  above the background (centers 133-246 vs background <= 40).
- `tools/render_voice_ui.py` and `tools/render_control_center.py`: pass.
- `jarvis.package_check` (run from a throwaway project subfolder, then
  deleted): `"ok": true`, including `app_start_stop` with the new UI.
- Real-platform renders (windows11 style, real fonts, never shown on
  screen): main window at 900x660 / 1360x850 / 1920x1080 and speaking;
  Settings (top, Safety, Gaming, Global hotkey, a 830x500 small-screen case);
  Codex's Gmail dialog, the safety confirm box and Screen Chat parented to
  the new window; overlay (empty / result / error); splash (loading / ready);
  all 8 wizard pages; tray icons at 16-64 px on dark and light taskbars; the
  main window, Settings and overlay again at `QT_SCALE_FACTOR=1.5`.

## Known limits

- Rounded corners on the overlay and splash come from DWM, so they only show
  on screen on Windows 11 (Windows 10 gets a hairline border instead).
- Native title bars follow the Windows app mode until `app.py` sets a dark
  color scheme (`INTEGRATION_REQUESTS.md` #5).
- Screen Chat, Activity Center and Project Changes keep their own palettes
  until Codex adopts the tokens (`INTEGRATION_REQUESTS.md` #4).
- The standalone `_ApiKeyPage` (as `package_check` renders it) is unstyled,
  as before; inside the wizard it uses the new style.

## Personal Jarvis (2026-09-25)

- HUD: a personal column right of the orb from 1250 px width (on narrower
  windows it tops the status column) with role pack cards (quick-action chips,
  Gamer "Game ready / Running hot" line, Student 25/5 focus timer), "Jarvis
  noticed" habit cards and the Kid/Guest banner; header avatar button with the
  profile menu and a KID MODE / GUEST badge.
- Settings: Personality (preset cards, humor, detail, "Call me", live preview)
  and Role packs sections.
- New dialogs: profile editor with photo framing or generated initials,
  adult-PIN prompt. Contract and wiring: `PERSONALIZATION_HANDOFF.md`.
- The rollback below predates this work: restoring the backup also removes it.

## Secondary windows in the Aurora style (2026-09-25, evening)

- New kit `src/jarvis/gui/aurora.py`: `dialog_rules()`/`style_dialog()`, a
  header with a glyph badge (`DialogHeader`, `badge_pixmap`), pill tabs,
  segmented controls, cards, chips, a composer bar and round send/call buttons.
- Applied (user decision: work in Codex's files too; logic untouched):
  Screen Chat, Game Chat (+ `PanelVoiceControls`), Activity & Undo (rows drawn by
  a delegate: status dot, action, time), Gmail, Project changes, the
  screen-sharing indicator (amber pill with a pulsing dot), the confirmation box
  (shield badge, action as title, "Allow"/"Cancel", Cancel stays default).
- Dark native title bars for every window (`setColorScheme(Dark)` in `app.py`).
- HUD: SYSTEM STATUS rows carry thin level meters (cyan / amber / coral).
- Tray and profile menus have glyph icons.
- Tests: `tests/test_gui_voice_aurora_kit.py`; all Codex dialog tests pass as-is.

## Rollback

There is no git history here; the pre-redesign files are in
`docs/claude/ui_backup_2026-09-23/`. Restore all seven together (the new
`main_window.py` imports `LogoMark` from the new `voice_core.py`):

```powershell
$backup = "docs\claude\ui_backup_2026-09-23"
foreach ($name in "voice_core", "main_window", "settings_page", "overlay", "splash", "first_run_wizard", "tray") {
    Copy-Item "$backup\$name.py.bak" "src\jarvis\gui\$name.py" -Force
}
Remove-Item "tests\test_gui_voice_hud_design.py"
```

The generated arrow images in `%TEMP%\jarvis-ui` can be deleted at any time.
