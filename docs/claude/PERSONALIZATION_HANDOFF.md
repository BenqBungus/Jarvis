# Personal Jarvis: profiles, personalities, role packs, habits, permission levels

User decision (2026-09-25): build all five, split **60% Claude / 40% Codex**.
This file is Claude's proposal of the split and the contract between the two
halves, so both can work in parallel. Codex: please confirm or amend in your
own handoff note; you own the shared contract/TASK_SPLIT update.

("Premium levels" in the user's message is read as the permission levels from
Claude's idea list: adult / kid / guest. If the user meant paid tiers, that is
a separate design.)

## Update: Claude built X1-X4 too (2026-09-25, user decision)

The user moved Codex to screen/game voice and settings work and asked Claude
to build Codex's 40% as well. All of it is in place and tested:

- X1 `src/jarvis/profiles.py` (`ProfileStore`): migration of the current
  settings into the first profile (it keeps the original `data/` memory files),
  validation, avatars, a salted PBKDF2 adult PIN with a short lockout, switching,
  Windows-account start-up choice (never skipping the PIN). Deleting moves the
  folder to `data/profiles/.deleted`.
- X2 `src/jarvis/permission_levels.py` (`LevelGate`): checked in
  `ToolRegistry.execute` (+ `level_block`, `visible_specs`; `schemas()` and
  `describe()` hide blocked tools), at the top of `CommandRouter.handle` for
  rule-based commands, before confirmations in `_execute_llm_tool_call` and the
  Live-voice executor. `trusted_actions.allow_full_access(False)` for Kid/Guest.
  Blocked results carry `metadata["blocked_by_level"]`.
- X3 `src/jarvis/habits.py` (`HabitLearner`): time-of-day habits from the audit
  log per profile (`AuditLogger.profile_id` now stamps records), merged into
  routines, decisions in `data/profiles/<id>/habits.json`, due routines are
  offered on the HUD and only run on "Run now".
- X4 `src/jarvis/gui/profile_wiring.py` (`ProfileController`, one call in
  `app.py`): memory folder per profile (Guests start clean), gate, full access,
  audit id, conversation language, Gmail credential target per profile
  (`GmailCredentialStore.target`), HUD, editor, Settings changes, habits,
  routines. The persona reaches every text request through
  `settings.profile_provider` in `JarvisSettings.response_language_instruction`
  and every Live call through `RealtimeVoiceConfig.from_settings`.
- Small edits in Codex files, each commented: `tool_registry.py`, `router.py`
  (gate, pre-confirmation check, `open_target` metadata for habits),
  `trusted_actions.py`, `audit.py`, `gmail_auth.py`, `user_settings.py`, `app.py`.
- Tests: `test_profiles.py`, `test_permission_levels.py`, `test_habits.py`,
  `test_gui_profile_wiring.py`. Full suite: 1925 passed, 6 skipped.

## Split

| # | Owner | Work | Weight |
|---|---|---|---|
| C1 | Claude | Personality presets: engine, Live-voice integration, Settings UI with preview | 12 |
| C2 | Claude | Role packs: definitions, voice instructions, Settings UI, HUD pack cards and quick actions | 16 |
| C3 | Claude | Profiles UI: avatars (photo crop or generated), header switcher, profile editor, new-profile onboarding, tray submenu | 18 |
| C4 | Claude | Permission-level UI: badges, kid/guest banners, "why was this blocked" messages, adult-PIN prompt | 6 |
| C5 | Claude | Habit suggestions UI: "Jarvis noticed" cards, accept/dismiss/snooze, spoken phrasing | 8 |
| X1 | Codex | Profile store: CRUD, per-profile folders (memory, history, avatar), Windows-account auto-select, migration, switching | 12 |
| X2 | Codex | Permission-level enforcement: per-level tool rules in router, registry and Realtime schemas; adult PIN; profile id in audit | 12 |
| X3 | Codex | Habit learning backend: time-of-day and sequence patterns per profile, decisions persisted, routines run through the executor with confirmations | 10 |
| X4 | Codex | Integration: `app.py` wiring, chat persona in `ai_client.py`, per-profile memory and Gmail credential target | 6 |

Claude 60 / Codex 40.

**New files and owners** (proposed; please record them in TASK_SPLIT.md):
Claude: `src/jarvis/personality.py`, `src/jarvis/role_packs.py`,
`src/jarvis/gui/profile_editor.py`, `src/jarvis/gui/avatar.py`, tests
`tests/test_personality*.py`, `tests/test_role_packs*.py`,
`tests/test_gui_profile*.py`. Codex: `src/jarvis/profiles.py`,
`src/jarvis/permission_levels.py`, `src/jarvis/habits.py` (or an extended
`automation_suggestions.py`) and their tests.

## Contract

### Profile record (Codex stores and validates; plain JSON dict)

```json
{
  "id": "berk",
  "display_name": "Берк",
  "avatar": "avatar.png",
  "avatar_hue": 190,
  "windows_user": "Berk",
  "language": "bg",
  "personality": {"preset": "jarvis", "humor": 1, "detail": 1, "address_as": "Берк"},
  "role_packs": ["gamer"],
  "permission_level": "adult",
  "learn_habits": true,
  "voice": {"live_voice": "cedar"}
}
```

- `avatar` is a file in the profile folder, or `""` for a generated avatar
  (initials on a gradient using `avatar_hue`).
- `language`: `en` | `bg` | `auto`. `permission_level`: `adult` | `kid` | `guest`.
- `personality` and `role_packs` values are defined by Claude's modules below;
  store them as given and reject unknown top-level keys, not unknown preset ids
  (Claude's code falls back to defaults).

**Until the store exists** Claude's Settings page keeps the current person's
choices in the existing `settings.personalization` dict:
`personalization["personality"]` (the object above),
`personalization["role_packs"]` (list) and the existing
`personalization["address_name"]`. X1's migration should turn these into the
first adult profile.

### X1 `src/jarvis/profiles.py` (Codex)

- `ProfileStore(root=Path("data/profiles"))`
- `list_profiles() -> list[dict]`, `get(profile_id) -> dict | None`, `active() -> dict`
- `create(display_name, **fields) -> dict`, `update(profile_id, changes) -> dict`,
  `delete(profile_id)`. Create/delete are adult-only; never delete the last adult.
- `set_avatar(profile_id, png: bytes) -> Path`. Claude's editor sends a square
  512x512 PNG that is already cropped; store it as-is, max 2 MB.
- `avatar_path(profile_id) -> Path | None`
- `switch(profile_id, pin: str | None = None) -> CommandResult`. Leaving a
  kid/guest profile for an adult one needs the adult PIN or a matching Windows
  user. On startup, auto-select the profile whose `windows_user` matches.
- Per-profile folders for long-term/episodic memory, conversation history and
  Realtime history. Gmail credential target per profile.

### X2 `src/jarvis/permission_levels.py` (Codex)

- `tool_allowed(level: str, spec: ToolSpec) -> tuple[bool, str]`, where the
  string is a short localizable reason.
- `visible_tool_specs(level, registry) -> list[ToolSpec]`. Claude's `realtime.py`
  will build Live-call tool schemas from this when a level is supplied.
- Suggested rules:
  - **Kid:** no power, network, Bluetooth, drivers, temp cleanup, recycle, move,
    end process, Gmail, screen sharing or autonomous tasks. Full access is
    never applied.
  - **Guest:** no memory or history tools, no Gmail, no personal file or
    document analysis; conversation, web and volume are fine.
  - **Adult:** unchanged.
- Enforce it in the router, the text LLM tool path and the Realtime executor.
  A blocked result carries `metadata["blocked_by_level"] = level` so the UI can
  explain it.

### X3 `src/jarvis/habits.py` (Codex)

A suggestion is a dict:

```json
{"id": "h-7f3a", "title": "Gaming evening", "detail": "You open Discord and Steam most days around 20:00.",
 "kind": "routine", "trigger": {"time": "20:00", "days": "mon-sun"},
 "actions": [{"tool": "open_application", "arguments": {"name": "Discord"}}],
 "confidence": 0.8, "evidence": "seen 6 times in 7 days"}
```

- `kind`: `routine` | `alias` | `volume` | `mode`.
- `HabitLearner.suggestions(profile_id) -> list[dict]`, `accept(id)`, `dismiss(id)`,
  `snooze(id, days=7)`.
- Only for profiles with `learn_habits`. Accepted routines run through the
  executor with the normal confirmations, never silently.

### Claude's side, provided for X4 wiring (all delivered 2026-09-25)

Voice and text:

- `personality.PRESETS`, `personality.persona_instructions(personality: dict,
  address_name: str = "") -> str`. It is language-neutral: the conversation
  language policy is added separately. Codex's chat path in `ai_client.py`
  should prepend it too.
- `personality.suggestion_line(suggestion, language) -> str`: how Jarvis offers
  a habit out loud ("I noticed something: ... Want me to set that up?" /
  "Забелязах нещо: ... Да го настроя ли?"). X3: add an optional `"detail_bg"`
  to a suggestion so the Bulgarian line is not half English.
- `role_packs.PACKS`, `role_packs.pack_instructions(pack_ids) -> str`, and
  `role_packs.DEFAULT_PACKS`. The Gamer pack carries the gaming-coach guidance.
- `RealtimeVoiceConfig.from_settings(settings, profile: dict | None = None)`:
  the profile's personality, packs, language and voice win when given.
  `app.py` builds the config on every call start, so passing
  `profile=store.active()` there is all Live voice needs.

HUD (`MainWindow`):

- `set_profile(profile, avatar_path=None)`: header avatar button, level badge
  and banner, the profile's role packs, and Settings' Personality/Role packs
  switch to editing that profile (see SettingsPage below). Nothing profile
  related shows before the first call.
- `set_profiles(profiles, avatar_paths: dict[id, path] | None = None)`: the
  header menu and the tray's "Switch profile" submenu list these.
- Signals `profile_switch_requested(id)` and `profile_editor_requested(id)`
  (`""` = new profile; "Add profile…" only shows for adults).
- `ask_adult_pin(profile_name, error="") -> str | None`: modal PIN prompt for
  `switch()`; the PIN is returned, never stored or logged by the UI.
- `open_profile_editor(profile | None, avatar_path=None) -> ProfileEditorDialog`:
  opens the editor with `can_manage` (adult level) and the Windows user already
  set; connect its signals to the store.
- `set_permission_level(level)`: kid/guest show a badge and a HUD banner,
  lock Settings (button, tray item and dialog). `show_permission_block(message,
  level="")` shows a blocked request apart from errors: call it when a result
  has `metadata["blocked_by_level"]`.
- `show_habit_suggestions(list[dict])`: up to three "Jarvis noticed" cards
  (needs `id`, `title`; `detail`/`evidence` optional). Buttons emit
  `habit_accepted(id)`, `habit_snoozed(id)`, `habit_dismissed(id)` once and
  remove the card.
- Role packs: `set_role_packs(ids)`; quick actions go out as
  `command_submitted(command, "button")` or the named window signal.

Dialogs (`gui/profile_editor.py`, avatars in `gui/avatar.py`):

- `ProfileEditorDialog(profile | None, parent, *, avatar_path=None,
  can_manage=True, windows_user="", default_language="auto")`. On Save it
  emits, in this order: `saved(changes)` (every field for a new profile, only
  changed ones otherwise; `"avatar": ""` means "back to the generated
  avatar"), then `avatar_chosen(png)` for a newly framed photo (512x512 PNG),
  then `adult_pin_chosen(pin)` if an adult set a PIN. `delete_requested(id)`
  after the user confirmed. For a new profile, create it on `saved` and use the
  new id for the `avatar_chosen` that follows.
- `AdultPinDialog.ask(parent, profile_name, error="")`.

Settings (`SettingsPage`):

- `personalization_changed(dict)` after every Save (MainWindow listens through
  `set_settings_widget`).
- `set_active_profile(profile | None)` (MainWindow.set_profile calls it): the
  Personality and Role packs sections then load from and save to the profile,
  and Save emits `profile_changes_requested(profile_id, {"personality": ...,
  "role_packs": [...]})` instead of touching `settings.personalization`.

### X4 wiring sketch (app.py, Codex)

```python
store = ProfileStore()
window.set_profiles(store.list_profiles(), {p["id"]: store.avatar_path(p["id"]) for p in store.list_profiles()})
window.set_profile(store.active(), store.avatar_path(store.active()["id"]))

def switch_profile(profile_id, pin=None):
    result = store.switch(profile_id, pin=pin)
    if not result.ok and result.metadata.get("pin_required"):
        pin = window.ask_adult_pin(store.get(profile_id)["display_name"], error=result.message if pin else "")
        if pin is not None:
            switch_profile(profile_id, pin)
        return
    active = store.active()
    window.set_profile(active, store.avatar_path(active["id"]))

window.profile_switch_requested.connect(switch_profile)

def edit_profile(profile_id):
    profile = store.get(profile_id) if profile_id else None
    dialog = window.open_profile_editor(profile, store.avatar_path(profile_id) if profile_id else None)
    target = {"id": profile_id}
    def on_saved(changes):
        target["id"] = store.update(profile_id, changes)["id"] if profile_id else             store.create(changes.pop("display_name"), **changes)["id"]
    dialog.saved.connect(on_saved)
    dialog.avatar_chosen.connect(lambda png: store.set_avatar(target["id"], png))
    dialog.delete_requested.connect(store.delete)
    # adult_pin_chosen -> the adult PIN setter from X2
    dialog.finished.connect(lambda _code: refresh_profiles())  # set_profiles + set_profile

window.profile_editor_requested.connect(edit_profile)
settings_page.profile_changes_requested.connect(lambda pid, changes: store.update(pid, changes))
window.habit_accepted.connect(learner.accept)   # and snoozed / dismissed
# on_result_ready: if result.metadata.get("blocked_by_level"):
#     window.show_permission_block(result.message, result.metadata["blocked_by_level"])
```

## Order

1. Claude: C1 and C2 on `settings.personalization` (visible immediately). **Done.**
   Codex: X1 and X2.
2. Claude: C3 and C4 against the contract, tested with fake stores. **Done.** Codex: X3.
3. Codex: X4 wiring. Claude: C5 (**done**) and a joint check at the end.

Claude's tests: `tests/test_personality.py`, `test_personality_settings.py`,
`test_role_packs.py`, `test_role_packs_gui.py`, `test_gui_profile_editor.py`,
`test_gui_profile_hud.py`. Full suite 2026-09-25: 1843 passed, 6 skipped, the
2 known `test_ai_client_traces.py` wording failures.
