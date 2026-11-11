# Jarvis Control Layer: Implemented Scope and Remaining Work

This continues the existing project. It is a completed control-layer iteration, not completion of the entire attached Jarvis specification.

## Architecture

The app remains Python + native PySide6. `gui/app.py` wires the existing `CommandRouter`, `ToolRegistry`, `CommandExecutor`, `GuiSafetyPolicy`, audio workers, Realtime session and monitor. Mutating GUI/voice actions remain serialized through the executor; task status/cancellation remain out-of-queue controls. Realtime now exposes 83 tools in the GUI, including the new file and teaching tools. No model or API key was changed.

New components:

- `FileSearchService` in `files.py`: bounded filename search and an allowlisted local document/folder opener. No content indexing, executable launch, remote shares or junction traversal.
- `LocalCommandService` in `local_commands.py`: deterministic commands with no AI dependency. Unknown commands fail locally instead of falling through to cloud parsing. Registered tool permissions remain checked.
- `TeachingService` in the same module: local guides with no action/tool/screen capabilities. It explicitly distinguishes instructions from observations or executed actions.
- `ActivityCenter`: on-demand audit view, recorded reasons and evidence, latest-action-only Undo Center, and read-only repetition suggestions.
- `suggest_repetitions`: groups matching successful safe actions and parameters; excludes failed, dry-run and risky operations. Three matching records are required. It cannot schedule or execute anything.

Existing equivalents are retained rather than replaced with empty renamed classes: monitoring supplies sensor readings; browser modules supply browsing/research; memory modules supply bounded history and local storage; the registry/safety policy provide permission gates; audit and rollback modules provide action records and undo. Full NitroSense automation, thermal policy, generalized action verification and driver compatibility analysis are not implemented by naming these existing pieces.

## What Changed

- Alt+Space opens a text overlay without starting the microphone. Ctrl+Space push-to-talk is preserved. Native hotkeys are registered separately and released on shutdown. A collision leaves the header button available; no competing process is terminated.
- The overlay has Conversation, Local and Teach modes, cancel, history and undo controls. Enter submits; Escape hides. It uses the same action queue and audit as the main app.
- The main voice screen remains System Status, Readiness and the animated core. Small header icons open separate tools; chat/mode/task dashboards were not restored.
- History shows the actual request, source, recorded reason, permission, confirmation, result and recorded verification. Missing reasons/evidence are labeled as missing, not generated after the fact.
- Undo preserves a failed record. The center supplies the reviewed timestamp; a changed stack is rejected. It cannot select an arbitrary old change out of order. Undo still requires confirmation.
- Volume uses the installed pycaw `EndpointVolume` API, with legacy `Activate` compatibility. Each calling thread owns a balanced COM initialization. A successful set is checked with a read-back; a mismatch is not reported as success.
- Gaming no longer has a built-in list of apps to close. Only configured exact process names are accepted; wildcard/system targets are rejected. Existing confirmation remains. Failed mode/launch substeps no longer yield unconditional success. Windows power-plan changes are not reported as NitroSense profile changes.
- Unsolicited monitor speech is off by default. The startup greeting remains short. Existing tray warnings and live dashboard readings remain; the dashboard is not yet entirely on-demand.

## Setup and Examples

Run the source app from the workspace:

```powershell
.\run.ps1 --gui
```

Alt+Space is enabled by default. Settings > Global Hotkey > Command overlay can disable it. While active it replaces the usual Alt+Space window-menu behavior; another launcher may already own it. The keyboard icon in Jarvis opens the same overlay without a shortcut.

Choose Local in the overlay:

```text
звук на 30
отвори NitroSense
отвори калкулатор
отвори Desktop
намери podcast в Desktop
```

The normal text router also accepts the `локално ` prefix. File search defaults to Desktop, Documents, Downloads and Pictures, or accepts an explicit absolute local root through `search_local_files`. It returns at most 25 matches, inspecting at most 12,000 entries or three seconds between filesystem operations, and reports partial results. It does not auto-open ambiguous matches. It does not yet search every drive automatically, rank fuzzy matches, or search dates/sizes/contents.

Choose Teach and enter a topic such as `звук`, `NitroSense Performance`, `Windows Update`, or `файл`. Normal text also accepts `научи ме ...`. These are initial local guides, not screen-aware coaching or an offline general language model. The Realtime model can call the new `teach_task` tool; this is not a session-wide ban on every other voice tool.

Local/Teach apply to the submitted command, not the entire process. They do not send that command to AI or request cloud TTS. They do not terminate an already active Realtime microphone stream, stop all monitoring network probes, or disable the internet. End the live call separately when offline/privacy is intended. Realtime voice still requires network access and API billing.

## Permissions and Limits

- No permanent service, startup entry, installer or administrator helper was installed by this iteration.
- Search reads filenames only from accessible local paths. Opening is limited to folders and common document/media extensions. Scripts, installers, shortcuts, macro-enabled documents, unknown types, UNC/device paths and reparse points are rejected, not silently executed.
- An accepted Windows launch request is recorded as such. It is not proof that a document is visible or an app finished loading. File opener native-window visibility remains unverified.
- Gaming can still close explicitly configured applications after confirmation, potentially losing unsaved work. No Gaming/Valorant launch or app-closing test was performed on the user's session. No NitroSense profile/fan changes were performed.
- The current undo types retain their existing limits. Network/Bluetooth records do not capture a complete per-device state; completed non-reversible operations cannot be undone. Undo stack locking is in-process; simultaneous Jarvis instances are not supported.
- Repetition suggestions cover the last 100 displayed records over seven days. They are computed when the center refreshes, not a background scheduler or automatic routine enrollment.
- There is no new screen-sharing protection for other apps, emails or Windows notifications. Do not rely on this version to conceal those surfaces during streaming.

## Device Checks

- Final full suite: **853 passed, 4 skipped, 2 warnings** in 46.15 seconds. The skipped cases are opt-in browser integration tests. Warnings are SpeechRecognition imports of Python's deprecated `aifc`/`audioop` modules.
- Real Win32 Alt+Space registration succeeded and was released immediately after the check. Synthetic WM_HOTKEY tests verify separation from Ctrl+Space; no global keypress was injected into other applications.
- Real workspace search found `README.md` without content reading and without reaching its bound.
- Read-only NitroSense probe: installed, `AcerGamingFunction` and `AcerGenericMethod` classes present, no running service among the probe's four named candidates. This does not prove no Acer service exists. No undocumented WMI methods were invoked.
- The first real Core Audio check exposed an incompatible old pycaw call. After repair, a worker-thread read and a same-level write/read-back passed without changing the selected level or adding a rollback record.
- Real OpenAI Realtime accepted the 83-tool session, generated Bulgarian speech, recalled a synthetic prior turn, selected the requested arbitrary URL tool and spoke the true idle task status. No website action or personal microphone recording was performed during this API check.
- Native offscreen screenshots were inspected for the main screen at 960/1360/1920 widths, and activity/undo at 640/800 widths. Keyboard submission, cancellation wiring, confirmation gating and empty/error states have automated coverage. Human microphone quality and audible speaker output remain a local listening test.

Repeatable checks:

```powershell
python -m pytest -q --basetemp tmp/control-verification
python tools/render_voice_ui.py
python tools/render_control_center.py
python tools/check_volume_control.py --same-level
python tools/check_realtime_connection.py --conversation
```

The last command makes small paid requests. The volume command skips writing if muted, to preserve that state.

## Changed Files

New source: `src/jarvis/files.py`, `src/jarvis/local_commands.py`, `src/jarvis/automation_suggestions.py`, `src/jarvis/gui/activity_center.py`, `src/jarvis/gui/icons.py`.

Updated source: `src/jarvis/router.py`, `src/jarvis/tool_registry.py`, `src/jarvis/rollback.py`, `src/jarvis/windows_actions.py`, `src/jarvis/volume.py`, `src/jarvis/gui/app.py`, `src/jarvis/gui/command_executor.py`, `src/jarvis/gui/hotkey.py`, `src/jarvis/gui/main_window.py`, `src/jarvis/gui/overlay.py`, `src/jarvis/gui/settings_page.py`.

New tests: `tests/test_local_control_services.py`, `tests/test_gui_control_center.py`, `tests/test_volume_compatibility.py`. Updated tests: `tests/test_gui_hotkey.py`, `tests/test_gui_app.py`.

New diagnostics: `tools/render_control_center.py`, `tools/check_volume_control.py`. Documentation: this report and `README.md`.

## Safe Next Stages

1. Inspect the exact NitroSense version and its accessible UI tree. Implement a scoped `NitroSenseAdapter` only for observed controls with post-action read-back. No coordinate guessing or undocumented EC/WMI writes.
2. Add a sensor-validity-aware thermal policy, first in recommendation-only mode. Before enabling fan writes, require verified actuator capability, bounds, hysteresis, cooldown, manual override, expiry and a tested Auto fallback. High heat must not select Performance automatically.
3. Build user-edited Valorant/Gaming, Podcast and Editing scenarios on those verified capabilities. Do not claim quiet recording or thermal protection while actuator/sensor verification is absent. OBS/Premiere integrations need their own connection and confirmation design.
4. Add persistent offline policy and screen-sharing privacy boundaries across voice, vision, notifications and storage. A Jarvis-only caption mask would not protect other applications.
5. Extend file indexing, screen UI Automation/OCR, driver/OEM comparison and memory retrieval with explicit roots, privacy controls, provenance and measured end-to-end checks. Rebuild the installer only after validating those workflows.

Official references: [Windows hotkey API](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey), [Windows icon font](https://learn.microsoft.com/en-us/windows/apps/design/iconography/segoe-ui-symbol-font), [pycaw public interface](https://andremiras.github.io/pycaw/), [Acer NitroSense overview](https://community.acer.com/en/kb/articles/16481-acer-nitrosense-software).

## Rollback Plan

The pre-edit source snapshot is `data/development-backups/control-layer-before-20260906.zip`. It contains `src`, `tests`, `tools`, `README.md` and `pyproject.toml`, not API keys from the environment or the user's settings/history databases.

Quit Jarvis from the tray before restoring source. Extract the ZIP into a separate folder inside the workspace, review it, then restore the archived files over their corresponding source paths. Keep current `data/` and `logs/`; do not overwrite personal settings, memory or audit records. Newly added modules can remain unreferenced by the restored source. Start `run.ps1 --gui` again. The previous packaged EXE was not rebuilt or replaced. This source rollback does not undo real OS actions performed after the backup.
