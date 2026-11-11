# Jarvis Project Instructions

Build a local Windows assistant that can accept Bulgarian and English commands and perform safe laptop actions.

Read `TASK_SPLIT.md` before coordinating with Claude Code.

## Priorities

1. Keep all system actions explicit, auditable, and reversible where possible.
2. Use normal Windows interfaces first: PowerShell, Settings URI handlers, WMI/CIM, registry reads where safe, and installed app launch commands.
3. Require confirmation for destructive or disruptive commands such as restart, shutdown, sleep, disabling adapters, disabling Bluetooth, or changing security-sensitive settings.
4. Keep command parsing simple and testable before adding LLM-based interpretation.
5. Prefer modules under `src/jarvis/` over large scripts.

## Suggested Split With Claude Code

Codex can own:

- Core command router and safety model.
- Windows actions for apps, websites, volume, updates, NVIDIA status.
- Driver, network, Bluetooth, file/folder, and AI question routing.
- Modes, temp warnings, recent files, DOCX drafts, temp cleanup, top processes, startup apps.
- Documentation and project structure.

Claude Code can own:

- Native desktop UI, not a web app.
- Voice input and text-to-speech adapters.
- Wake phrase experiments: "Hey Jarvis", "Здравей Jarvis".
- Background monitor loop for Windows Update and driver checks.
- Tests for Bulgarian command variants.
- NitroSense research and integration if Acer exposes an API, WMI provider, service, log, or registry source.
- Notification UX for high temperature and update monitors.

## Guardrails

- Do not add raw arbitrary shell execution from user speech.
- Do not run permanent background services without documenting install/uninstall commands.
- Do not disable internet, Bluetooth, firewall, or security services without a confirmation prompt and a clear explanation.
- Keep secrets out of the repo.
- Do not create files outside the Jarvis workspace unless the user explicitly approves a broader filesystem scope.
- Temp cleanup, closing apps, and mode changes that affect the session must require confirmation where disruptive.
