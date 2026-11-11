# Jarvis Task Split

## Active Split (2026-09-14)

The user requested a division of the 21-item roadmap. This section supersedes all
historical ownership below, including the previous PWA-only Claude assignment.
There is no direct live Claude messaging channel; the user supplies the handoff.
An assignment is not proof that the other agent has received it or started work.

### Codex Write Scope

- All Python source except the exact Claude-owned paths below.
- In particular: router, permissions, tool registry, task/workflow execution,
  memory, browser, vision, documents, project patches/checks/repair, monitoring,
  system actions, integrations and the future companion server.
- GUI integration stays with Codex: `src/jarvis/gui/app.py`, `command_executor.py`,
  `gui_safety.py`, `screen_chat.py`, `screen_sharing.py`, `project_changes.py`,
  `tasks_panel.py`, `activity_center.py`, plus other GUI files not listed below.
- Root dependency manifests, settings schema/persistence, CLI, installer, release
  scripts, shared docs/contracts, and tests outside the Claude test scope below.

### Claude Write Scope

- `src/jarvis/audio/`, `src/jarvis/realtime.py`, `src/jarvis/voice_assistant.py`.
- Exact GUI files under `src/jarvis/gui/`: `voice_worker.py`, `realtime_worker.py`,
  `speech_service.py`, `voice_core.py`, `main_window.py`, `overlay.py`,
  `settings_page.py`, `first_run_wizard.py`, `tray.py`, `splash.py`, `hotkey.py`.
- `clients/mobile-web/` and `clients/CONTRACT_REQUESTS.md` for the PWA.
- Existing `tests/test_audio*.py`, `tests/test_voice*.py`, `tests/test_realtime*.py`,
  `tests/test_speech*.py`, `tests/test_gui_voice*.py`, `tests/test_gui_realtime*.py`,
  `tests/test_gui_first_run_wizard.py`; new voice acceptance tests belong in
  `tests/acceptance_voice/`. Do not edit shared `tests/conftest.py`.
- `docs/claude/` for reports and requests for changes outside this scope.

### Roadmap Owners

Numbers refer to the user's preceding 21-item improvement list.

| Items | Owner | Deliverable |
| --- | --- | --- |
| 1, 2 | Claude | Voice diagnostics, stable playback/input ownership and interruption. |
| 3 | Codex | Conversation/task context and reference resolution; Claude preserves the voice transport contract. |
| 4, 5 | Codex | Observed completion evidence and bounded recovery from failures. |
| 6 | Claude then Codex | Claude authors opt-in voice acceptance scenarios; Codex integrates cross-system checks. |
| 7, 8 | Codex | Browser and Windows UI automation with permissions and verification. |
| 9 | Codex | Screen context and monitor/window selection; coordinate GUI controls via a handoff. |
| 10, 11, 12 | Codex | Sourced research, deeper memory and document workflows. |
| 13, 14, 15, 16, 17 | Codex | More project toolchains, directory patches, undo history, isolated execution and task resumption. |
| 18, 19 | Codex | Real mode behavior and service integrations; Claude may expose approved state in its UI files. |
| 20 | Split | Codex owns authenticated server/pairing/protocol; Claude owns PWA transport/UI/offline states. |
| 21 | Codex then Claude | Codex builds/releases; Claude supplies a clean-machine installation test report. Signing requires user-provided credentials. |

### First Parallel Milestone

Codex: strengthen task completion evidence, failure recovery and context using
deterministic fixtures. Claude: prioritize voice diagnostics and interruption,
then opt-in real conversation acceptance. PWA remains assigned to Claude but comes
after the voice reliability milestone; no need for a second simultaneous UI rewrite.

Preserve public methods/signals/result schemas while work runs concurrently. A
needed cross-owner change goes into `docs/claude/INTEGRATION_REQUESTS.md` (Claude)
or a Codex handoff note, and the owning agent applies it. Never silently rename or
remove a shared interface. Preserve permission checks in Realtime tool dispatch;
the voice transport cannot bypass the command executor or grant approvals.

Neither agent edits the other's paths, resets changes, upgrades root dependencies
or rebuilds/releases while the other is changing source. Freeze relevant source
before full-suite verification and packaging. This checkout has no Git metadata;
directory/file ownership is the isolation boundary, not worktrees.

Paid model tests, microphone capture and personal-screen tests require separate
explicit consent. Start with mocked audio/provider fixtures. Do not enable new
background services, public/LAN listeners, or remote auto-start as a side effect.
The companion contract remains design/mock-only until a real backend is verified.

See `docs/CLAUDE_WORK_HANDOFF.md` and `docs/CLAUDE_MOBILE_HANDOFF.md`.
Codex's latest execution checkpoint is in `docs/TASK_VERIFICATION.md`. It adds
result metadata without changing voice methods or Qt signals; no voice-side edits
are required for those completion checks. Release integration is still pending.

2026-09-15 integration checkpoint: Codex reviewed Claude's reports and completed
the tool-error signal wiring and accurate dependency detail in gui/app.py.
See docs/INTEGRATION_REVIEW_2026-09-15.md for independent focused test results and
the remaining real-audio/backend/release gates. Claude-owned files were not edited.

## Current Ownership And Verified Progress (2026-09-05)

Historical record: the user previously assigned the whole project to Codex.

### Autonomy Iteration

- Implemented `browser/managed.py` and browser tools: isolated Opera GX/Chromium, stable tabs, observed element refs, text reads, scrolling, confirmed click/fill/select/close. Playwright stays on one worker thread. Browser files stay under the workspace; personal profiles are not used.
- Added Tasks UI, progress, cooperative cancellation, queued-command cancellation and immediate per-attempt GUI audit records. Voice exposes the bounded task runner and an out-of-queue cancel tool.
- Adaptive planner now sees structured observations including DOM refs, enforces admin/confirm/blocked permissions, supports alternative-source recovery, and stops repeated failures or uncertain side effects. Structured schemas require nullable unused argument fields and validate scalar argument types.
- Added Realtime recent-context seeding and ordered transcript persistence. Only completed, fully played assistant replies are saved; memory clear cannot resurrect active-session history.
- Live read-only checks: Chromium and configured Opera GX read `https://example.com`. A real model-driven workflow opened the page, observed its heading and returned "Example Domain". No personal pages, microphone or system changes were used in these checks.
- Local browser fixtures cover search form filling/submission, stale/mutated refs, dropdowns, tab switching/closing, restart after closing a context and cross-thread calls. Human voice/microphone and arbitrary retail sites remain unverified.
- Verification for this iteration: full suite with real local browser fixtures enabled: `773 passed, 2 warnings`. After adding the cancellation/voice-memory preference regressions, the affected voice/GUI suites passed `82 passed`. The two warnings are SpeechRecognition's Python audio deprecations, not test failures.
- The Realtime server accepted synthetic historical context without opening a microphone or generating a spoken response. Tasks and Assistant renders were checked at 1360x900 and 1080x760. No installer rebuild or personal microphone listening test was performed.

- Removed unrelated digital portfolio source/ZIP, portfolio page renders, and poster script to the Windows Recycle Bin. Jarvis source, documents, data, settings, and installer files remain in place.
- Realtime now waits for session acknowledgement, enables input transcription, uses callback-driven PCM playback, truncates interrupted audio, and cleans up streaming tasks on disconnect.
- Voice transcripts accumulate as complete turns in the GUI. Session polling no longer erases speaking status or the latest transcript.
- Classic voice waits for playback completion. GUI speech reports success/failure, supports a speaker tone test, and guards microphone ownership across modes.
- Realtime GUI tools use the shared command queue and audit log. Malformed arguments cannot become empty-argument system actions.
- Named output-device selection survives Windows device renumbering. The launcher resolves data paths relative to the project directory.
- Live verification: TTS playback returned success; Realtime accepted the configuration and generated 91,200 PCM samples (3.8 seconds) for the greeting. Human audibility and a full microphone conversation still need verification.
- Source GUI renders checked at 1360x900 and 1080x760. The existing packaged executable has not been rebuilt.
- Verification: full suite `734 passed, 2 warnings`; after adding a disconnect-cleanup regression, all 6 transport tests passed. The warnings come from deprecated Python audio modules imported by SpeechRecognition.

Remaining priorities: real microphone/echo tests, richer memory retrieval, advanced browser interactions (frames/uploads/authentication), native Windows UI automation, third-party integrations, and a rebuilt installer after validation. The browser profile contains cookies for sites visited by Jarvis; do not treat it as disposable without considering saved logins.

## Claude Code Owns

Build the native user experience and voice layer.

- Native desktop app, not a web app. Prefer PySide6.
- Tray icon with status: listening, idle, processing, warning.
- Main window with command input, command history, system status dashboard, and settings.
- Voice input and Bulgarian/English text-to-speech.
- Wake phrases: `джарвис`, `здравей jarvis`, `hey jarvis`, `jarvis`.
- Push-to-talk fallback for noisy rooms.
- Confirmation dialogs for high-impact actions.
- Desktop notifications for high temperature, updates, low battery, and connectivity changes.
- UI controls for Quiet, Study, Battery Saver, and Gaming modes.
- NitroSense research: WMI, service, logs, registry, app package commands, or CLI. If no safe interface exists, keep open-NitroSense fallback and document it.
- Tests for Bulgarian command variants from `README.md`.

Do not change backend safety rules without coordinating with Codex.

### Claude Milestones From The User List

- Real settings UI:
  - Voice mode toggle.
  - Command history view.
  - Alias editor: `отвори даскало` -> a configured website.
  - App path editor for Opera GX, Steam, Discord, games, and custom apps.
  - Confirmation settings screen.
  - OpenAI model and API key status indicator.
- Better voice:
  - Wake word: `Джарвис`.
  - Push-to-talk fallback.
  - Noise threshold controls.
  - Spoken responses.
  - Friendly "I did not hear you clearly" fallback instead of executing uncertain commands.
- System health dashboard:
  - CPU/RAM/GPU usage.
  - CPU/GPU temperature.
  - Battery.
  - Disk space.
  - Windows Update.
  - NVIDIA driver.
  - Startup apps.
  - Top processes.
- Always-on background service UX:
  - Tray app controls for starting/stopping monitors.
  - Notifications for temperature, Windows Update, battery, disk space, internet, and driver updates.
  - Clear UI state when a monitor is running.
- Modes UI:
  - Buttons for Gaming, Study, Battery Saver, and Quiet.
  - UI for editing which apps launch/close in Gaming mode.
  - UI for mode volume profiles.
- NitroSense research:
  - Check for Acer/NitroSense services.
  - Check registry keys.
  - Check logs.
  - Check WMI providers.
  - Check if there is an Acer CLI or app package command surface.
  - Document what is safely possible and what is not.
- Installer:
  - Package as `Jarvis.exe`.
  - Start with Windows option.
  - Desktop shortcut.
  - Setup wizard.

## Codex Owns

Build the reliable backend that UI and voice can call.

- Settings/memory JSON.
- Command audit log.
- Installed app discovery from Start Menu.
- Command router safety and deterministic local actions.
- Backend docs and command examples.
- Keep destructive actions behind confirmation.

### Codex Milestones From The User List

- Command permissions:
  - `safe`: open websites, check temperature, read status.
  - `confirm`: clean temp files, close apps, gaming mode.
  - `admin`: internet/Bluetooth, driver checks/changes, power settings.
  - `blocked`: kernel-level and security-sensitive actions unless the user approves a separate design.
- Skill/plugin architecture:
  - Split backend actions into modules: `system`, `drivers`, `apps`, `web`, `documents`, `monitoring`, `modes`, `nitrosense`.
  - Keep the router as orchestration, not a giant file.
- Real intent parser:
  - Local deterministic rules first for dangerous or obvious commands.
  - OpenAI structured JSON intent only for ambiguous natural language.
  - Never allow the model to return raw shell commands.
- Always-on background service backend:
  - Provide monitor APIs for temperatures, Windows Update, battery, disk space, internet, and driver updates.
  - UI can consume these APIs instead of duplicating system logic.
- Modes backend:
  - Gaming mode: high performance power plan, volume profile, NitroSense open, GPU temp check, close configured apps, launch configured apps.
  - Study mode: low volume, focus assist, open configured browser/docs, optional distracting-site blocker design.
  - Battery mode: battery saver, brightness down, quiet notifications, warn about heavy processes.
- Local memory:
  - Preferred browser.
  - Frequent websites.
  - Games.
  - Preferred volume.
  - Apps to close in Gaming mode.
  - How Jarvis should address the user.
  - Commands that always require confirmation.
- Audit log:
  - Raw command text.
  - Parsed intent.
  - Action executed.
  - Confirmation status.
  - Errors.
- Rollback / undo:
  - Restore previous volume.
  - Restore previous power plan.
  - Re-enable internet after disabling.
  - Reopen closed apps where possible.
- Real document creation:
  - Ask follow-up questions for pages, tone, structure.
  - Search/research when needed.
  - Generate `.docx`.
  - Open the document in Word.
- App launcher database:
  - Scan Start Menu and installed apps.
  - Support commands like `отвори Valorant`, `отвори Minecraft`, `отвори контролния панел`.
  - Avoid hardcoding every app.

### Already Started By Codex

- `data/settings.json` exists for settings/local memory.
- `src/jarvis/audit.py` writes `logs/audit.jsonl` with intent, action, permission, confirmation status, and errors.
- `src/jarvis/user_settings.py` loads settings.
- Start Menu app discovery exists through `open_discovered_app`.
- App launcher database exists through `src/jarvis/app_database.py` and `data/app_index.json`.
- Command permission metadata exists through `src/jarvis/permissions.py`.
- Rollback stack exists through `src/jarvis/rollback.py`.
- Basic modes, temperature checks, driver checks, website opening, file/folder creation, DOCX draft creation, Windows Update checks, and safety confirmations exist.
- Core tool registry exists in `src/jarvis/tool_registry.py` with discoverable tool specs, JSON-schema-style parameter definitions, permissions, categories, and safe execution validation.
- The router exposes `jarvis list tools` / `jarvis покажи tools` for developer inspection and future GUI Tools panel integration.
- Casual conversation fallback exists: safe non-command text is sent to the AI chat path instead of returning "unknown command"; relevant semantic memory hits are included as private chat context when `openai.use_memory_context` is enabled.
- Short-term conversation history exists in `data/conversation_history.jsonl` through `src/jarvis/memory/conversation.py`.
- Structured intent parser exists in `src/jarvis/intent_parser.py`; ambiguous requests can be routed through OpenAI JSON schema output with confidence/clarification fields and then validated against registered tools.
- Long-term memory exists in `src/jarvis/memory/long_term.py` with local SQLite storage, categories, update/edit support, plus commands/tools for `remember`, `search_memory`, `forget_memory`, `update_memory`, `set_memory_category`, and `list_memory_categories`.
- First-pass privacy guard exists in `src/jarvis/privacy.py`; long-term memory writes, memory tool responses, short conversation history, command session timelines, tool argument metadata, and audit/developer traces redact obvious API keys, bearer tokens, access tokens, and password assignments.
- Episodic memory exists in `src/jarvis/memory/episodic.py` with JSONL storage in `data/episodic_memory.jsonl`; commands include `jarvis обобщи разговора`, `jarvis обобщи действията от последните 10 минути`, and `jarvis покажи епизодична памет`.
- Tool registry exposes `summarize_conversation_episode`, `summarize_action_episode`, and `list_episode_summaries`; normal non-dry-run conversation can auto-create episode summaries after enough new turns.
- Local semantic-like memory search exists in `src/jarvis/memory/semantic.py`; commands include `jarvis търси семантично в паметта <query>` and `jarvis намери в паметта <query>`, and the tool registry exposes `semantic_memory_search`.
- Allowlisted personal preference settings exist through `JarvisSettings.set_user_preference()`, router commands like `jarvis наричай ме берк`, `jarvis любимият ми браузър е opera gx`, `jarvis предпочитан звук 30`, `jarvis сложи предпочитания звук`, and tool registry tools `set_user_preference` / `show_user_preferences`.
- Mode-volume preferences and Gaming-mode close/launch app lists saved by the GUI are now read by `WindowsActions.apply_mode()` / `game_mode()` on each command.
- Action history introspection exists through `AuditLogger.recent()` / `summarize_recent()` and commands like `jarvis какво направи през последните 10 минути`.
- Developer trace storage exists in `AuditLogger`: source, latency, result metadata, intent, action/tool, permission, confirmation, and compact latest-trace summaries.
- The router exposes `jarvis покажи последния trace` / `developer trace`; the tool registry exposes `latest_developer_trace`.
- Developer traces can be filtered by source, intent, action/tool, permission, status, `error_type`, `recommended_action`, time window, and limit through `AuditLogger.filtered()`, `summarize_filtered()`, router commands like `jarvis покажи trace action open_url` / `jarvis покажи blocked errors`, and the `filtered_developer_traces` tool.
- Failed command results are enriched through `src/jarvis/error_taxonomy.py` with `error_type`, `error_severity`, `recommended_action`, `retryable`, and `error_message`; latest developer trace summaries surface error type and recommended action.
- Single model-selected tool calls include `llm_tool_trace` metadata with selected tool, arguments, permission, status, confidence, reason, clarification question, and result.
- Low-confidence or underspecified model-selected actions are stopped as `intent=llm.clarification` / `action=ask_clarification` before any tool execution or confirmation prompt.
- Pending LLM clarifications are one-turn resumable: `да` / `yes` executes the saved tool through normal confirmation gates, while `не` / `отмени` / `cancel` records `llm.clarification_cancelled`.
- Missing, blank, or null required arguments for model-selected tools are stopped as `intent=llm.argument_clarification` / `action=ask_tool_argument`; the next user reply fills the argument and resumes through normal validation/safety. Unexpected model arguments are rejected before tool execution.
- OpenAI-backed results include `ai_trace` metadata when available: provider, model, operation, response id, token usage, and tools. Intent parser and workflow planner traces are exposed as `intent_parser_metadata["ai_trace"]` and `workflow_planner_metadata["ai_trace"]`.
- Command session timeline exists in `src/jarvis/session.py`; CLI and GUI execution now attach `session_id` and `state_timeline` metadata to command results and audit records.
- Safe workflow runner exists in `src/jarvis/workflows.py`; workflow results include per-step tool, permission, confirmation flag, latency, arguments, status, message, attempt count, recovery hints, and underlying `result_metadata`.
- First workflow exists: `jarvis намери оферти за <query> и отвори първия`, implemented as `save_deal_candidates` + `open_url`.
- AI workflow planner exists: `JarvisAI.plan_workflow()` requests an OpenAI structured workflow plan, `parse_workflow_plan_json()` validates registered tools plus missing/blank/unexpected arguments, and the router executes validated plans via `WorkflowRunner`.
- Workflow plan preview/approval exists: planned workflows expose preview metadata and require a plan-level confirmation before any important/admin step runs.
- Adaptive workflow mode exists: explicit commands like `jarvis адаптивно ...` ask the model for one next registered tool after seeing previous tool results, with the same confirmation gates.
- Planned/adaptive workflows can retry allowlisted safe information tools once; confirmation/admin tools are never retried automatically.
- Failed planned/adaptive workflow steps expose `workflow_recovery` metadata with failed tool, category, attempts, retry state, and recommended next action.
- Webpage extraction exists in `src/jarvis/browser/page_reader.py`; router commands include `jarvis прочети страницата <url>` and `jarvis прочети първия`.
- Tool registry exposes `extract_webpage`; extracted text is marked as `untrusted_web_content` and localhost/private-network URLs are blocked by default.
- First-pass prompt-injection hardening exists in `src/jarvis/prompt_safety.py`; web/research prompts use explicit untrusted-content boundaries and expose `prompt_injection_guard` metadata.
- Web research exists in `src/jarvis/browser/research.py`; router commands include `jarvis проучи <topic>`, `jarvis сравни <items>`, and `jarvis потърси информация за <topic>`.
- Tool registry exposes `research_web`; it searches, reads safe top sources through `PageReader`, saves numbered candidates, and returns `sources` metadata with `title`, `url`, `snippet`, `excerpt`, `quality_score`, `quality_label`, and `quality_reasons`, plus aggregate `source_quality` and `source_coverage`.
- Safe browser control exists in `src/jarvis/browser/controller.py`; router commands include `jarvis търси в браузъра <query>`, `jarvis потърси <query> и отвори първия`, `jarvis отвори резултата за plasico`, `jarvis прочети резултата за nvidia`, `jarvis какво прочете`, `jarvis сравни тези резултати`, `jarvis какво казват страниците за батерията`, and `jarvis провери playwright`.
- Lightweight browser session memory exists in `src/jarvis/web_context.py`; it stores the latest saved results plus opened/read page records for follow-up commands without requiring the user to repeat URLs.
- Browser session comparison can call `JarvisAI.compare_browser_session_pages()` with untrusted-content boundaries and `ai_trace` metadata, or fall back to local excerpt comparison when AI is unavailable.
- Browser session answers can call `JarvisAI.answer_browser_session_question()` with untrusted-content boundaries and `ai_trace` metadata, or fall back to local excerpt notes when AI is unavailable.
- Tool registry exposes `browser_search`, `browser_open_result`, `browser_open_matching_result`, `browser_search_and_open`, `browser_open_search_page`, `extract_saved_web_result_matching`, `show_browser_session`, `compare_browser_session_pages`, `answer_browser_session_question`, and `browser_automation_status`.
- Screen vision backend exists in `src/jarvis/vision/screen.py`; router commands include `jarvis какво има на екрана`, `jarvis защо ми дава тази грешка`, and `jarvis провери screen vision`.
- Tool registry exposes `screen_describe` as `confirm` permission and `screen_vision_status` as `safe`; screen results are marked `privacy_sensitive`.

### Already Started By Claude

- Voice mode exists through `--voice`.
- Voice diagnostics exist through `--voice-doctor`, the `voice_diagnostics` backend tool, and the GUI **Voice Doctor** button.
- Audio output device selection exists through Settings > Voice > Audio output device plus CLI overrides/tests (`--list-audio-devices`, `--audio-output-device`, `--set-audio-output-device`, `--test-output-tone`, `--test-speaker`).
- Background monitor mode exists through `--monitor`.
- Wake-word matching exists.
- Bulgarian/English speech-to-text and text-to-speech wrappers exist.
- OpenAI text-to-speech can run without `pyttsx3` when `OPENAI_API_KEY` is available; Windows SAPI voices are now fallback/offline only.
- Voice assistant keeps a short active follow-up session after a successful wake-word command; the GUI also has a dedicated `Voice Conversation` button for a hands-free follow-up loop. It gives short spoken acknowledgements such as `Нека помисля.` before explanation/research-style prompts. `спри да слушаш`, `край jarvis`, or `stop listening` ends it early. Classic and Realtime GUI voice paths now show heard/user/assistant transcript snippets in the HUD so the user can see what Jarvis understood.
- Monitoring checks exist for battery, internet, NVIDIA driver, and Windows Update.
- Tests exist and passed locally: `717 passed, 2 warnings`.

### Not Done Yet / Still In Progress

- Production conversation engine with explicit states: idle, listening, thinking, executing tool, speaking, waiting for confirmation.
- Structured LLM intent parser is started: deterministic local rules run first, OpenAI can return JSON intent with confidence/clarification fields for ambiguous requests, and tool calls are validated against the registry.
- Full backend module split into separate tool packages while keeping existing behavior stable.
- Long-term memory database has store/search/forget/update, importance, timestamps, core categories, and local semantic-like search; real embeddings/vector DB, privacy UI, and richer category-specific UX are still pending.
- Short-term conversational context is started, and casual chat can receive relevant semantic memory context; follow-up questions that refer back to tools like CPU/RAM/status still need better intent resolution.
- Full Playwright/Opera GX UI automation is still pending. Safe browser search, numbered result opening, webpage text extraction, and first-pass web research are available as browser/research backend layers.
- Deep research has first-pass source collection, extraction, AI summarization, citations, heuristic source quality scoring, and basic coverage/conflict markers; richer conflict checking and long-form reports are still pending.
- Screen capture and first-pass multimodal screen understanding are started; multi-monitor targeting, OCR-only fallback, UI automation, and visible privacy indicator are still pending.
- OBS, Spotify/media, Home Assistant/smart-device integrations.
- Automation/routine engine for scheduled reminders and event-triggered actions.
- Multi-step workflows and a general registered-tool-only planner are started, but richer planning policies, retries, and tool-result-dependent branching are still pending.
- Tool-result-dependent branching is started through explicit adaptive workflow mode; richer retry policies, branch limits per tool category, and plan recovery UX are still pending.
- Workflow plan confirmation exists in backend; GUI-specific preview dialogs/timelines are still pending.
- Global shortcut and always-on-top overlay.
- Streaming STT/LLM/TTS and barge-in cancellation.
- Privacy mode and offline mode.
- Developer mode with selected model, tool calls, tool results, latency, errors, and concise reasoning summaries.
- Developer trace exists for recent command inspection, but there is not yet a full GUI developer panel or token usage display.
- Broader rollback/undo coverage.
- Full document generation with research and follow-up questions.
- First-run wizard, `.env.example`, secure secret storage guidance, and installer / `Jarvis.exe`.

## Long Prompt Alignment

This section maps the user's full "PROJECT: JARVIS" prompt to the current build.

### Done / Usable Now

- Text command runner through the CLI and native GUI.
- Native PySide6 app with tray icon, Jarvis-style neon HUD dashboard, slim side navigation, command history, mode buttons, settings page, push-to-talk, waveform/radar widgets, and monitoring bridge.
- Voice mode entry point with wake phrase matching and OpenAI/Windows fallback speech components.
- Short active voice follow-up session after a successful wake-word command plus GUI-started voice conversation sessions that do not require repeating the wake word for every follow-up.
- Open websites and arbitrary domains, including Plasico and shopping search shortcuts.
- Open configured apps and discovered Start Menu apps.
- Volume up/down/mute/set by number.
- Windows Update checks/open settings.
- NVIDIA and generic driver info/update checks through supported Windows/NVIDIA paths.
- Internet/Bluetooth enable/disable behind confirmation.
- NitroSense discovery/opening and documented safe limitations.
- Temperature/status checks where Windows/NVIDIA exposes sensors.
- Modes: Quiet, Study, Battery Saver, Gaming.
- Create files/folders in the workspace and draft `.docx` documents.
- Temp cleanup with confirmation.
- Top processes and startup programs.
- Audit log for commands and permission metadata.
- Rollback stack for selected reversible actions.
- Core tool registry foundation for plugin/tool architecture.
- Casual AI conversation for safe non-command text.
- Short local conversation history for follow-up context.
- Structured JSON intent parsing for ambiguous requests.
- User-approved long-term memory commands with categories and update/edit support.
- Episodic conversation and action-history summaries with manual list/search commands and automatic conversation summaries in normal mode.
- Local semantic-like search across long-term and episodic memory with BG/EN alias matching and ranked result metadata.
- Recent action history summaries from the audit log.
- Latest developer trace summaries with source, latency, metadata, permission, and confirmation status.
- Filtered developer traces with `trace_filter`, `trace_filter_count`, and compact `traces` metadata.
- `llm_tool_trace` metadata for single LLM-routed tool calls, including clarification stops and rejected unregistered tools.
- One-turn clarification resume/cancel flow for LLM-routed tools, with `clarification_resolved` metadata.
- One-turn missing-argument fill/resume flow for LLM-routed tools, with `missing_arguments`, `unexpected_arguments`, and argument-related `llm_tool_trace.status` values.
- OpenAI `ai_trace` metadata for chat/web/research/vision/episode summaries, plus intent parser and workflow planner traces.
- Command session metadata: `session_id` and `state_timeline` with states such as `received`, `thinking`, `executing`, `waiting_confirmation`, `confirmation_resolved`, `completed`, and `failed`.
- Safe multi-step workflow execution with per-step metadata, including each step's attempt count, recovery hint, and underlying `result_metadata`.
- OpenAI-planned workflows that are validated against the tool registry before execution, including missing, blank, null, and unexpected tool arguments.
- Plan preview metadata for workflows: `workflow_preview`, `workflow_requires_approval`, `workflow_highest_permission`, `workflow_risky_tools`, `workflow_step_count`, and `workflow_steps`.
- Adaptive workflow metadata: `adaptive_workflow`, `adaptive_goal`, `adaptive_decisions`, and `workflow_steps`.
- Browser/page reading metadata: `url`, `title`, `text_length`, `excerpt`, and `untrusted_web_content`.
- Web research metadata: `query`, `sources`, `source_quality`, `source_coverage`, `candidates`, and `untrusted_web_content`. Each source contains `title`, `url`, `snippet`, `excerpt`, `quality_score`, `quality_label`, and `quality_reasons`.
- Browser search metadata: `query`, `browser_results`, and `candidates`. Each browser result contains `title`, `url`, and `snippet`. Matching/session follow-ups include `match_query`, `ordinal`, `title`, `url`, `browser_session`, `compared_pages`, `source_pages`, `browser_session_ai_compare`, `browser_session_ai_answer`, and `ai_trace` when AI synthesis runs.
- Screen vision metadata: `screenshot_path`, `width`, `height`, `vision_prompt`, and `privacy_sensitive`.

### Partially Done

- LLM brain: OpenAI web-backed answers, casual chat, and conversation-first structured intent routing work. Direct high-impact commands still stay local and confirmation-first. Multi-provider model routing is not implemented yet.
- Tool calling: tool registry and LLM JSON intent parsing exist, and safe/admin model-selected tools execute through the registry with confirmation. The old router still needs gradual migration into registered tool execution.
- Memory: settings/preferences, short conversation history, SQLite long-term memory with categories/update, first-pass secret redaction, JSONL episodic conversation/action summaries, local semantic-like memory search, and memory-aware casual chat exist; real embeddings/vector storage and richer privacy UX are still pending.
- Proactive monitoring: checks exist, but no full background Windows service, scheduler, or notification priority engine.
- Desktop interface: practical GUI exists with a Jarvis-style startup loading animation, spoken Bulgarian greeting, reference-inspired neon HUD layout, slim side navigation, top command bar, animated central core/orb, animated voice waveform, radar/status widgets, Realtime Voice readiness panel with Start/Stop controls, adapted setup/readiness checklist, dashboard-style command cards, and richer conversation bubbles; overlay polish and richer visual states are still pending.
- Realtime voice: `src/jarvis/realtime.py` builds/checks an OpenAI Realtime voice-agent session config (`gpt-realtime-2.1`, 24 kHz PCM, semantic VAD, built-in voice), streams microphone PCM to the Realtime websocket, plays streamed audio output, emits states, and bridges Realtime function calls back through the existing tool registry/confirmation gates. Real microphone/speaker testing is still pending on the user's laptop once dependencies and API key are visible to the process.
- Error handling: many commands return readable messages, command sessions capture failed states, and failed results now have first-pass app-wide error taxonomy metadata; richer GUI developer trace/error views are still pending.
- Security: permissions/audit, first-pass memory secret redaction, and first-pass web prompt-injection boundaries exist, but plugin permission controls, deeper prompt-injection defenses, and secrets storage UX are still pending.

### Not Started

- Multi-monitor targeting and richer screen/OCR understanding.
- UI automation of arbitrary applications.
- Advanced deep research with richer conflict checking, richer source quality scoring, and long-form cited reports.
- Full Playwright browser control of tabs, forms, clicked elements, and page state.
- OBS control via OBS WebSocket.
- Spotify/media official integrations.
- Home Assistant/smart-device integration.
- Global hotkey.
- Polished/tested Realtime barge-in playback truncation and cancellation.
- More polished GUI integration for the Realtime streaming pipeline, including transcript accumulation and explicit device selection.
- GUI indicator/control for the active follow-up voice session.
- Privacy mode and offline Ollama/local model routing.

### Risky / Requires Separate Approval

- Kernel-level control.
- Undocumented NitroSense fan/profile writes.
- Disabling security protections.
- Running unknown downloaded scripts.
- Permanent deletion, formatting drives, credential access, bypassing authentication, CAPTCHAs, paywalls, or access controls.

## Next Work Split From The Long Prompt

### Codex Next

- Continue the Realtime backend:
  - Test the `sounddevice` microphone/speaker stream on the user's real laptop audio devices.
  - Add playback truncation bookkeeping for polished barge-in after `input_audio_buffer.speech_started`.
  - Expand Realtime error handling/reconnect behavior.
  - Add state events for `waiting_confirmation` and richer transcript deltas once the GUI consumes them.
  - Keep Realtime function calls routed through the existing `ToolRegistry`/`CommandRouter` so permissions and confirmations stay enforced.
- Convert the current router into a cleaner tool-orchestrator gradually:
  - Keep deterministic local rules for dangerous/obvious commands.
  - Move more existing local command branches to registered tool execution.
  - Continue expanding developer traces around deterministic local rules as they migrate into registered tool execution.
- Expand workflows:
  - Shopping compare workflow with saved candidates and source links.
  - Gaming setup workflow with confirmation.
  - Study setup workflow.
  - Document research workflow.
  - Expand retry/recovery after failed tool results beyond the current one-retry allowlist.
  - Add branch policies per tool category.
- Add a provider abstraction for LLMs:
  - OpenAI first.
  - Interface ready for Anthropic, Gemini, Ollama later.
- Add memory backend:
  - Expand category-specific UX for preferences, projects, devices, games, websites, and routines.
  - Improve action-history episodes with richer grouping by workflows, tools, and failures.
  - Upgrade local semantic-like search to real embeddings/vector search later.
- Add browser/research backend:
  - Expand extract/cite sources from `extract_webpage` and `research_web`.
  - Save candidates for follow-up commands like `open the first`.
  - Source quality and basic conflict markers are started; add stronger conflict checks and stronger prompt-injection checks for untrusted web/page text.
  - Add a real Playwright session manager after the safe browser controller interface stabilizes.
- Add developer trace:
  - Surface token usage in the GUI developer panel from `ai_trace`.
  - Expand per-step traces for branch/retry/recovery policies.
  - Expand trace filtering UX in the GUI.

### Claude Code Next

- Build the Realtime voice UX shell:
  - Voice mode toggle for classic `--voice` vs Realtime.
  - Mic/output device selectors, mic test, and speaker test.
  - Dependency/API key/model/voice status is started in the Assistant tab's Realtime Voice panel; expand it into a full Settings diagnostics view.
  - Visual states for listening/thinking/speaking/interrupted/waiting confirmation/error.
  - Realtime transcript captions for partial user speech and assistant speech.
  - Confirmation dialogs that can be triggered from Realtime tool calls.
- Make the GUI reflect the new prompt:
  - Tools panel from `router.tools.list_specs()`.
  - Developer mode panel using audit entries:
    - `source`
    - `latency_ms`
    - `metadata`
    - `intent`
    - `action`
    - `permission`
    - `requires_confirmation`
    - `confirmed`
    - `ok/error`
    - `metadata["session_id"]`
    - `metadata["state_timeline"]`
  - Workflow timeline view from `result.metadata["workflow_steps"]`.
  - Show per-step `result_metadata` inside the workflow timeline.
  - Workflow preview dialog from `result.metadata["workflow_preview"]` and approval fields before important/admin workflows.
  - Adaptive agent timeline from `result.metadata["adaptive_decisions"]`, showing each decision reason and subsequent tool result.
  - LLM tool trace panel from `result.metadata["llm_tool_trace"]`, showing status `executed` / `cancelled` / `needs_clarification` / `missing_arguments` / `unexpected_arguments` / `argument_cancelled` / `clarification_cancelled` / `unregistered_tool`, plus confidence, clarification question, missing/unexpected argument lists, and `clarification_resolved`.
  - AI trace fields from `ai_trace`, `intent_parser_metadata["ai_trace"]`, and `workflow_planner_metadata["ai_trace"]`: model, operation, response id, token usage, and tools.
  - Trace filtering UX in the GUI for source, intent, action/tool, permission, ok/failed status, error taxonomy, minutes, and limit using `AuditLogger.filtered()` or `filtered_developer_traces`.
  - Page reader view for `extract_webpage` output with URL/title/excerpt and an "untrusted web content" indicator.
  - Research result view for `research_web` output with numbered sources, open/read buttons, and an "untrusted web content" indicator.
  - Browser results view for `browser_search` / `browser_search_and_open` metadata with numbered Open/Read buttons.
  - Screen vision view for `screen_describe` metadata with screenshot path, prompt, privacy-sensitive badge, and confirmation result.
  - Memory panel for viewing, searching, editing, categorizing, and deleting saved memories.
  - Memory category counts from `list_memory_categories`, plus edit form using `update_memory` / `set_memory_category`.
  - Semantic memory search field calling `semantic_memory_search`, showing kind, score, category/source, created date, and content from `semantic_memory_hits`.
  - Episodic memory view from `list_episode_summaries`, showing source, topics, summary, turn/action counts, created date, and action metadata (`actions`, `sources`, `ok_count`, `failed_count`) when present.
  - Better system dashboard with CPU/RAM/GPU/disk/top processes/startup apps.
  - Settings for preferred browser, mode preferences, gaming apps, voice provider/model/voice.
  - Privacy checkbox for `openai.use_memory_context`, explaining that it controls whether saved memories may be included in OpenAI chat prompts.
  - First-run wizard for API key status, microphone, speaker, voice, wake words, filesystem permissions, browser choice.
- Improve voice UX:
  - Better Bulgarian/English recognition path using the new OpenAI STT settings.
  - Push-to-talk reliability.
  - Noise threshold controls.
  - Clear "I didn't hear that" state.
  - Cancellation phrase handling in the GUI worker.
  - Active-session indicator after a wake-word command, plus a visible way to stop the follow-up listening window.
- Add overlay/global shortcut:
  - Always-on-top mini status window.
  - Configurable Ctrl+Space push-to-talk.
- Continue installer work:
  - `Jarvis.exe`.
  - Start with Windows.
  - Tray startup mode.

## Integration Contract

Claude should call the same router used by the CLI:

```python
from jarvis.ai_client import JarvisAI
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.user_settings import JarvisSettings
from jarvis.windows_actions import WindowsActions

settings = JarvisSettings.load()
router = CommandRouter(
    actions=WindowsActions(dry_run=False),
    safety=SafetyPolicy(auto_confirm=False),
    ai=JarvisAI(dry_run=False),
    settings=settings,
)
result = router.handle("jarvis отвори discord")
```
