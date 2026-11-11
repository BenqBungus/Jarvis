# Claude Code Instructions

You are collaborating with Codex in the same Windows workspace:

`C:\Users\Berk\Desktop\Jarvis`

The goal is to build a local Jarvis-style assistant for the user's laptop. It should understand Bulgarian and English text or voice commands and perform safe Windows actions.

Read `TASK_SPLIT.md` before making changes. Current division: Claude owns native UI, voice, tray, notifications, and NitroSense research. Codex owns backend settings, audit logging, command routing, app discovery, and safety.

## Please Focus On

- Native desktop UI, not a web app. Prefer PySide6 or another real Windows desktop toolkit.
- Voice input and text-to-speech adapters.
- Wake phrase detection for:
  - `jarvis`
  - `hey jarvis`
  - `здравей jarvis`
  - `джарвис`
- Background monitoring:
  - Windows Update availability.
  - NVIDIA driver version/status.
  - Generic driver status for display, chipset, audio, network, Bluetooth.
  - Battery level warnings.
  - Internet connectivity state.
- NitroSense integration:
  - Find whether NitroSense exposes data through WMI, a local service, logs, registry, or a CLI.
  - If it does not expose an API, implement "open NitroSense" and document the limitation.
- Desktop app features:
  - Tray icon.
  - Mic status.
  - Command history.
  - Confirmation dialogs for high-impact actions.
- Settings page for app aliases, website behavior, OpenAI model, and safety confirmations.
  - Use `data/settings.json` as the first settings backend.
  - Mode buttons for Quiet, Study, Battery Saver, and Gaming.
  - Temperature warning notifications.
  - "Recent file" quick action.
- Tests for Bulgarian command variants.

## Current Architecture

- Entry point: `python -m jarvis`
- Source: `src/jarvis/`
- Core router: `src/jarvis/router.py`
- Windows actions: `src/jarvis/windows_actions.py`
- Safety prompts: `src/jarvis/safety.py`
- Configuration: `src/jarvis/config.py`
- User settings: `src/jarvis/user_settings.py` and `data/settings.json`
- Audit log: `src/jarvis/audit.py` writes `logs/audit.jsonl`

## Safety Rules

- Never allow arbitrary shell execution from raw user speech.
- Restart, shutdown, sleep, disabling Wi-Fi/Bluetooth, and other disruptive actions must ask for confirmation.
- Prefer Windows-supported APIs and commands over low-level hacks.
- Avoid kernel drivers or kernel-level changes unless the user explicitly approves a separate, audited design.

## New Commands Codex Added

- `jarvis направи звука на 30`
- `jarvis провери всички драйвери`
- `jarvis провери chipset драйверите`
- `jarvis провери driver updates`
- `jarvis спри интернета` / `jarvis включи интернета`
- `jarvis спри bluetooth` / `jarvis включи bluetooth`
- `jarvis провери температурите`
- `jarvis предупреди ме ако температурите са над 85`
- `jarvis отвори nitrosense`
- `jarvis quiet mode`
- `jarvis режим учене`
- `jarvis режим батерия`
- `jarvis режим игра`
- `jarvis отвори последния файл`
- `jarvis направи ми документ за втората световна война`
- `jarvis почисти temp файлове`
- `jarvis какво ми товари компютъра`
- `jarvis провери стартъп програмите`
- `jarvis създай папка notes`
- `jarvis създай файл notes/todo.txt`
- `jarvis провери в интернет ...`
