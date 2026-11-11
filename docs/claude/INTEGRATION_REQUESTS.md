# Integration Requests (Claude -> Codex)

Changes below need to land in files outside Claude's write scope
(`src/jarvis/gui/app.py` is Codex's). Everything else needed for each item
is already implemented and tested on Claude's side; these are the only
remaining steps.

Status (2026-09-23): #1 applied (`app.py:441`). #3 still open. #4-#6 are new
with the "Aurora" UI redesign (see `docs/claude/UI_REDESIGN_STATUS.md`);
none of them is blocking -- everything works without them.

Status (2026-09-24): #7-#9 added after the user asked for Jarvis to edit
files directly "like Codex/Claude" and to give gaming advice. #7 is a test
environment finding worth fixing first; #8 and #9 are backend features in
Codex's scope that the voice side is ready to use.

**Update 2026-09-25:** by the user's decision ("work together, even in the same
files") Claude applied #4 (Screen Chat, Game Chat, Activity Center, Gmail, Project
changes and the sharing indicator now use the Aurora kit in `gui/aurora.py`; logic
untouched) and #5 (`app.styleHints().setColorScheme(Qt.ColorScheme.Dark)` in
`app.py`), and restyled the confirmation box in `gui_safety.py` (same buttons and
default, new texts "Allow"/"Cancel"). All Codex tests pass unchanged. #3 is done too:
`app.py` polls `router.screen_sharing.state()` twice a second into
`MainWindow.set_screen_sharing_active` (which ignores repeats).

**#10 (2026-09-24) is a notice, not a request:** by the user's explicit
decision Claude built driver updates end to end, including small edits in two
Codex-owned files. Please read it before touching `router.py` or `app.py`.

## 1. Wire `tool_error_occurred` so tool failures show as a persistent error (needed)

**Where:** `src/jarvis/gui/app.py:397`, immediately after the existing line:

```python
realtime_worker.detail_changed.connect(window.set_realtime_detail)
```

**Add:**

```python
realtime_worker.tool_error_occurred.connect(window.show_tool_error)
```

**Why:** `RealtimeVoiceWorker._on_realtime_state`'s `"tool_error"` branch
(`src/jarvis/gui/realtime_worker.py:180-191`) already emits both
`detail_changed` (unchanged, so today's behavior keeps working even before
this is wired) and a new `tool_error_occurred` signal carrying the same
redacted message. Right now only `detail_changed` is connected in `app.py`,
so a genuine tool failure (e.g. "Screen streaming was rejected: quota
exceeded") is rendered through `MainWindow.set_realtime_detail` — the same
path as routine status text — and disappears after the normal ~9s
auto-clear, indistinguishable from something that just worked.

`MainWindow.show_tool_error(message)` already exists
(`src/jarvis/gui/main_window.py:355`) and calls
`self.show_feedback(message, error=True)` — the same persistent,
error-styled, "stays until superseded" feedback regular command failures
already get. No new UI state or auto-clear tier is introduced.

**Verified independently of `app.py`:**
- `tests/test_gui_realtime_tool_error_display.py` — the worker's dual-emit,
  `MainWindow.show_tool_error` directly, and the full signal-to-window
  chain end to end.
- `tests/acceptance_voice/test_tool_request.py::test_a_worker_level_tool_error_still_reaches_the_ui_as_a_distinct_error`
  — connects a real `RealtimeVoiceWorker` to a real `MainWindow` the same
  way `app.py` would, so once the one-line connection above is added, no
  further testing on Claude's side should be needed.

## 2. Cosmetic: readiness detail text no longer distinguishes two causes (low priority, not blocking)

**Where:** `src/jarvis/gui/app.py:258-262`:

```python
"realtime_deps": (
    bool(realtime_status["websocket_available"] and realtime_status["audio_stream_available"]),
    "websockets + sounddevice ready"
    if realtime_status["websocket_available"] and realtime_status["audio_stream_available"]
    else "install websockets and sounddevice",
),
```

**Why:** Before Claude's readiness fix, `audio_stream_available` (the
`"sounddevice"` entry in `readiness()["missing"]`,
`src/jarvis/realtime.py:271-293`) only checked whether the `sounddevice`
package was importable. It now also calls the new
`_audio_devices_available()` (`src/jarvis/realtime.py:812`), which returns
`False` when sounddevice is installed but PortAudio reports no usable
input or output device — a real and previously-invisible failure mode this
fix was specifically meant to surface (see `VOICE_STATUS.md`). The
`app.py` text above still says "install websockets and sounddevice" for
both cases, which is now sometimes wrong advice (the package is already
installed; the machine has no working mic/speaker device).

**Suggested wording split** (not required immediately — flagging so it's
not lost): something like "sounddevice not installed" vs. "no working
microphone/speaker device found" using
`realtime_status["websocket_available"]` and `realtime_status["audio_stream_available"]`
as two independently-reported booleans rather than one combined flag. Left
as a suggestion since it touches only display text and Claude does not
have write access to `app.py` to prototype the exact copy.

## 3. Wire `set_screen_sharing_active` so the top-bar toggle reflects real state (needed)

**Where:** `src/jarvis/gui/app.py:581`, immediately after the existing line:

```python
session_poll_timer.timeout.connect(lambda: window.set_session_active(assistant.session_active()))
```

**Add:**

```python
session_poll_timer.timeout.connect(lambda: window.set_screen_sharing_active(router.screen_sharing.state()["sharing"]))
```

**Why:** Realtime screen sharing used to be reachable only through a buried
Settings → "Audio" dropdown entry, with no visible status anywhere once
active. `MainWindow` now has a proper top-bar toggle button + status dot
(`screen_sharing_requested` signal unchanged, so `app.py`'s existing
`toggle_screen_sharing()` wiring at `app.py:238-244` keeps working exactly
as-is) and a new `set_screen_sharing_active(bool)` setter — the only missing
piece is reflecting the real backend state onto it.

`router.screen_sharing` (`src/jarvis/vision/sharing.py`) is a plain object
with no Qt signal, so polling is the only option — this reuses the
already-running 1-second `session_poll_timer` rather than adding a new one,
the same reasoning already written at that timer's own definition.

**Important — read-only, do not call `indicator_visible()` here:**
`ScreenSharing.state()` (`vision/sharing.py`) auto-stops sharing if
`indicator_visible()` hasn't been called in the last 2 seconds — that's the
heartbeat the existing `ScreenSharingIndicator`'s own 250ms timer keeps
alive while its floating on-screen widget is actually visible. The line
above only *reads* `state()["sharing"]`; it must never call
`indicator_visible()` itself, or the new poll would keep sharing "alive"
independent of whether the real privacy indicator is showing, defeating its
purpose. The old buried menu entry ("Start or stop Realtime screen sharing")
has been removed from the Settings dialog — this was a move, not a
duplication.

**Verified independently of `app.py`:** `tests/test_gui_main_window.py` —
click-before-confirmation doesn't move the checked state, `set_screen_sharing_active(True/False)`
updates the button/tooltip/dot correctly, and the initial unchecked/neutral
state before any interaction.

**Disclosure:** those four tests (`test_screen_share_button_click_does_not_move_checked_state_before_confirmation`,
`test_set_screen_sharing_active_true_updates_button_and_dot`,
`test_set_screen_sharing_active_false_updates_button_and_dot`,
`test_screen_share_button_starts_unchecked_with_the_neutral_dot_color`,
`tests/test_gui_main_window.py:66-110`) were added by Claude to a
Codex-owned test file in the screen-share round. They still pass unchanged
after the redesign. Keep them, or move them to a Claude-owned file (e.g.
`tests/test_gui_voice_screen_share.py`) -- your call; Claude won't touch that
file again.

## 4. Optional: move Codex's own-palette dialogs onto the Aurora tokens (cosmetic)

**Where:** `screen_chat.py:50-54`, `project_changes.py:33-39`,
`activity_center.py:27-38` (all Codex-owned). They set their own complete
palettes, so they now look like a slightly different app next to the
redesigned windows. `GmailSettingsDialog` and the safety `QMessageBox` set
nothing themselves and already inherit the new look.

**Simplest:** replace each dialog's stylesheet with the shared base plus only
what is unique to it (tabs):

```python
from .voice_core import BASE_STYLE
self.setStyleSheet(BASE_STYLE + """
QTabWidget::pane { border: none; }
QTabBar::tab { background: transparent; color: #A2AEBB; padding: 8px 16px; border-bottom: 2px solid #1B2430; }
QTabBar::tab:selected { color: #E7EDF3; border-bottom-color: #22D3EE; }
""")
```

Primary actions can opt into the gradient with
`button.setProperty("variant", "primary")` (set it before `setStyleSheet`,
or re-polish). If you prefer to keep the per-dialog sheets, exact
old -> new values:

| Role | ScreenChat / ProjectChanges | ActivityCenter | Aurora |
|---|---|---|---|
| Window background | `#101719` | `#091317` | `#07090D` |
| Text | `#e4edef` | `#d3e5e8` | `#E7EDF3` |
| Secondary / status text | `#b9c8c9` | -- | `#A2AEBB` |
| Input / list background | `#182225` | `#101f25` | `#111821` (inputs), `#0B0F14` (lists) |
| Input / list border | `#3b5158` | `#32515b` | `#243041` |
| Focus | `#73cbc0` | -- | `#22D3EE` |
| Button background | `#20383d` | `#162a30` | `#121923` |
| Button hover | -- | `#254851` | `#172130` |
| Button text | `#b9f1e9` | (text) | `#E7EDF3` |
| Button border | `#48706f` | `#32515b` | `#243041` |
| Disabled text | `#738182` | `#64808a` | `#6C7886` |
| Disabled border / background | `#344448` | `#102027` | `#1B2430` / `#0E1319` |
| Selection | -- | `#296274` | `rgba(34, 211, 238, 40)` |
| Selected tab accent | -- | `#4fc4d3` / `#bceff4` | `#22D3EE` / `#67E8F9` |
| Corner radius | `4px` | `4px` | `8px` (inputs, buttons), `10px` (lists) |

`ScreenSharingIndicator` should keep its amber: it is a privacy signal and is
meant to stand out from the app.

## 5. Optional: dark native title bars and controls (one line, `app.py`)

**Where:** `src/jarvis/gui/app.py:179`, right after
`app = QApplication.instance() or QApplication(sys.argv)`.

**Add:**

```python
app.styleHints().setColorScheme(Qt.ColorScheme.Dark)
```

**Why:** on a Windows account in Light mode, native title bars and the few
native-drawn controls (e.g. checkbox indicators in Codex's dialogs) come out
light around the dark UI. This is app-global,
so it is yours to add. (`Qt` needs `from PySide6.QtCore import Qt` if
`app.py` doesn't import it yet.) Combo-box and spin-box arrows no longer
depend on it: they are drawn from small generated images.

## 6. Optional: use `SettingsPage.add_account_action()` for the Gmail button

**Where:** `src/jarvis/gui/app.py:300`:

```python
settings_page.layout().insertWidget(0, gmail_button)
```

**Replace with:**

```python
settings_page.add_account_action(gmail_button)
```

**Why:** the redesigned Settings page has a navigation rail with an
"Integrations" area; `add_account_action()` puts the button there, styled like
the other entries. The current `insertWidget(0, ...)` line keeps working --
the page's outer layout routes a button inserted at index 0 to the same
place -- so this is only about making the intent explicit. The same applies
to the Game Chat button, and the `Ctrl+Alt+Space | Game Chat` checkbox you
insert at index 1 is routed into the Global Hotkey card (any QCheckBox whose
text names a key combination); the direct call is
`settings_page.add_hotkey_option(game_hotkey_toggle)`. Optionally give it
the monochrome glyph the rail uses:
`gmail_button.setIcon(glyph_icon("mail", QStyle.StandardPixmap.SP_FileDialogContentsView, settings_page.style()))`
(`from .voice_core import glyph_icon`).

## 7. Test environment: pytest's temp folder is now a "private" path (worth fixing first)

**Finding (2026-09-24, this machine):** pytest puts `tmp_path` under
`C:\Users\Berk\AppData\Local\Temp\pytest-of-Berk\...`. The private-path guard
(`ProjectWorkspace`, recycling, edit proposals) now rejects AppData, so with
the default temp folder:

- 12 tests fail: `test_collaborative_assistance.py` x9 ("Edit proposal
  rejected (ValueError)") and `test_screen_ocr_access.py` recycling x3
  ("Private configuration and system folders need separate review.").
- The full suite **hangs forever** at
  `test_screen_chat.py::test_selected_project_reaches_ai_and_clear_revokes_access`:
  `ProjectWorkspace(tmp_path)` raises, and `screen_chat.py:297` opens a modal
  `QMessageBox.warning` that the test does not patch (it only patches
  `QMessageBox.question`). An earlier full run sat there for 1.5 hours at ~1
  CPU core.

With a non-private temp folder the picture is clean:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.venv\Scripts\python.exe -m pytest -q tests --basetemp=data\diagnostics\pytest-tmp
```

-> **1737 passed, 6 skipped, 2 failed** in 1:39 (latest run, including
Claude's new HUD/persona tests). The two failures are
`test_ai_client_traces.py::test_research_summary_wraps_web_excerpts_as_untrusted`
and `::test_browser_session_compare_wraps_page_excerpts_as_untrusted`: they
still expect the old `UNTRUSTED_WEB_CONTENT_POLICY` wording ("search results,
and other retrieved web content"), which now reads "search results, emails
(including headers), and other retrieved content".

**Suggested fixes (all Codex-owned files):**
1. Make the default temp location non-private, e.g. `addopts = "--basetemp=data/diagnostics/pytest-tmp"`
   in the pytest config, or a fixture that points those tests at a
   workspace-local folder. **Use a different folder per agent**: pytest wipes
   the whole basetemp at start, so two runs sharing one folder break each
   other (2026-09-24: a locked leftover folder from `test_gui_app.py` turned
   the next run into 1464 setup errors). Claude now uses
   `data/diagnostics/pytest-tmp-claude`.
2. Patch `QMessageBox.warning` in the Screen Chat project tests (or turn that
   rejection into a non-modal status message), so a rejected folder can never
   block the suite again.
3. Update the two wording assertions in `test_ai_client_traces.py`.

## 8. Feature: edit a file in place, reviewed and undoable ("like Codex/Claude")

**User request (2026-09-24):** Jarvis should change a file directly, the way
Codex and Claude do, not only save a revised copy.

**Today:** `file_editing.py` stops at a reviewed diff plus `save_file_edit`
to a NEW file ("original unchanged, no overwrite"). In-place, undoable edits
exist only for projects in the Screen Chat patch flow (`project_changes.py`).

**Proposed tools** (same `EDIT_TYPES`, 64000-byte limit, `content_path_allowed`,
credential checks and five-minute proposal expiry as `FileEditing` today):

- `apply_file_edit(proposal_id)` - `CONFIRM`, preauthorized by the existing
  Full access setting like other local file changes. Re-check the proposal
  (`preview().ok`, exact id), re-read the source and require the stored
  sha256 digest (stale -> refuse, ask for a new proposal). Journal the original
  bytes, the new sha256 and the file identity (`st_dev`/`st_ino`) under
  `data/` before writing; replace atomically through a same-directory
  temporary file (`os.replace`), keeping the BOM/line endings already encoded
  in `_pending["bytes"]`. Metadata: `path`, `undo_id`, `diff`, `executed: False`.
- `undo_file_edit(undo_id)` - `CONFIRM`. Restore the original bytes only if
  the file still has the applied hash and identity; refuse on a later edit,
  never overwrite the user's newer work. One-step history per file is enough
  to start (the project patch journal already works this way).
- `preview_file_edit` wording: offer "apply to the original (undoable)" next
  to "save an edited copy".

**Voice side:** once these tools exist Claude will add to the Realtime
instructions: apply only after the user has heard/seen the diff and agreed,
report the result honestly, and mention that it can be undone. No other voice
change is needed; tool dispatch already goes through the registry and the
normal confirmation gate.

## 9. Feature: `game_context` for the gaming coach (safe, read-only)

**User request (2026-09-24):** gaming advice. The Realtime instructions now
make Jarvis act as a gaming coach using existing tools (`list_processes`,
`system_hardware_status`, `system_temperatures`, `top_processes`,
`research_web`, `game_mode`, `nvidia_driver_info`, screen sharing). What is
missing is a cheap, reliable way to know *which* game is running.

**Proposed tool:** `game_context()` - `SAFE`, category `gaming`, no arguments:

- foreground process executable name, and whether it looks like a game
  (install path under a Steam `steamapps\common`, Epic, Riot, Battle.net,
  EA or Xbox library, or an app-index entry marked as a game);
- the window title **only** when it is a detected game (other titles can name
  private documents or chats), plus a fullscreen flag;
- current GPU utilization/temperature and CPU/RAM from the existing monitors,
  and the active Jarvis mode.

Claude will then add one sentence to the gaming guidance ("call game_context
first when the game is unclear") and a test that the named tool is registered
(`tests/test_realtime_voice.py::test_jarvis_persona_and_gaming_coach_only_name_real_tools`
already guards every tool the guidance names).

## 10. Notice: driver updates built by Claude inside Codex's area (user decision)

The user asked for "update this driver" to actually install, and chose
(2026-09-24) that Claude builds it end to end now rather than via a handoff,
using Windows Update plus NVIDIA's own signed Game Ready installer. Design
and verification: `docs/claude/DRIVER_UPDATES.md`.

**Touched outside Claude's usual scope:**

| File | Change |
|---|---|
| `src/jarvis/driver_updates.py` | New module (Claude-owned for now): scan, install, status tools. |
| `src/jarvis/router.py` | One import plus a 5-line block after `discard_file_edit` that creates `self.driver_updates` and registers its four tools. |
| `src/jarvis/gui/app.py` | 12 lines after `bridge.alert_received.connect(on_alert)`: a second `MonitorBridge` that carries the finished result to a tray toast and the HUD feedback line. |
| `tests/test_driver_updates.py` | New, 15 tests; everything system-facing is faked. |

**Tools:** `scan_driver_updates` (SAFE, read-only), `install_windows_driver_updates`
and `install_nvidia_driver` (ADMIN + `requires_confirmation`, so both the Realtime
dispatcher and `_execute_llm_tool_call` show your confirmation dialog, whose
"Arguments" line names the exact drivers/version), `driver_update_status` (SAFE).
Installs run on a background thread and elevate through one UAC prompt; the
existing `check_driver_updates` tool is unchanged.

**Please:** keep these blocks when you edit around them; if you would rather
own `driver_updates.py`, say so in a handoff and Claude will stop editing it.
The full suite with the non-private temp folder (#7) is still clean apart from
the two known `test_ai_client_traces.py` wording failures.
