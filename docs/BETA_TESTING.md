# Sharing Jarvis with testers

## Current recommendation

For nontechnical testers use the new standalone desktop beta described in
DESKTOP_BETA.txt. `scripts/build_desktop_beta.py` builds both the GUI and document
worker, checks them offline and produces a ZIP containing their runtime dependencies.
The old installer/dist tree is obsolete. A standalone folder is not a signed installer.

The source beta below remains available for technical testers with Windows 11 and
Python 3.11. It requires Python and dependency installation.

Create a fresh release folder containing only:

- `src/jarvis/` source `.py` files, excluding every `__pycache__` folder.
- `pyproject.toml`, `requirements.txt`, and `run.ps1`.
- This guide as `BETA_TESTING.md`.
- Dependency attribution/licenses as required before public distribution.

Zip only that clean folder after inspecting its contents. Do not zip the whole development workspace. Do not copy `.env`, `data`, `logs`, `.venv`, `.codex`, `.claude`, `tmp`, local settings, conversation/audit history, screenshots, browser profiles, downloaded documents or existing installer/build/dist trees. Do not include the development README verbatim; it contains machine-specific development history. Inspect source files for accidentally hardcoded secrets before distribution. A folder allowlist is not a complete secret audit.

Each tester supplies their **own OpenAI API key and API billing** using Jarvis setup. Never embed or share the developer's key. A desktop executable cannot safely conceal a shared API key. Providing centrally paid access later requires a backend with authentication, per-user quotas, rate limits and revocation; that is not implemented here.

## Tester setup

The generated ZIP includes `Setup-Jarvis.cmd` and `Start-Jarvis.cmd`. Extract the
entire ZIP first, install Python 3.11 with the Windows Python launcher, then run
Setup once and Start afterwards. Setup downloads dependencies from PyPI into
the extracted folder; do not run as administrator. It does not disable execution
policy or Windows security. See FEATURES.md for the new controls and limitations.

Extract to a user-writable folder, open PowerShell there, then run:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e ".[gui,voice,vision,documents,files,browser]"
.\run.ps1 --gui
```

The first-run wizard configures personal settings. Test microphone/speaker devices and API access on that machine. Hardware sensors, Acer NitroSense and NVIDIA tools are device-dependent; missing readings must stay unavailable rather than invented. Do not require administrator launch for ordinary conversation or document use.

Start testing with harmless actions and temporary sample files. Leave Full access OFF for initial testing. Report the command, expected result, actual result and error text; redact credentials and private document/screen content before sending any logs back. There is no automatic telemetry or remote support access introduced by the collaboration features.

## Suggested beta checks

1. Start/stop voice, interruption and a casual conversation; verify that both listening and playback work.
2. Ask for a reasoned disagreement: `Debate me on whether remote work improves productivity. Challenge my assumptions.` Check quality yourself; prompt tests do not prove debate skill.
3. Open a public website and inspect system usage; do not start with shutdown/driver changes.
4. Analyze a nonprivate sample PDF, ask a follow-up, then save a new Word draft. Never test with confidential documents without understanding cloud disclosure.
5. The monitor icon opens GPT-5.6 Sol Screen Chat. Start sharing, type a question, change a sample window and ask a follow-up. Test Stop, Escape, Clear and Retry; no computer commands should execute from this chat. For the separate Realtime feed, use Settings > Audio > Start or stop Realtime screen sharing and verify periodic image updates and Stop. Neither mode is Discord frame-rate video.
6. Propose a change to a temporary text/code file, review the diff and save a revised copy to a new filename. Verify the original is unchanged.
7. Ask for file info on a sample file and a nonexistent file. Compare its size with Explorer; a missing path must be reported as missing. Try a folder-and-notes task and ask `What are you working on?` while it runs. Status should not wait behind the task. See TASK_VERIFICATION.md in the source tree for verification scopes.

## Before a public Jarvis.exe release

- Retest the packaged document helper in frozen execution for every release.
- Build from a clean environment and dependency set, not a folder containing user data.
- Use a per-user application-data location for state instead of assuming the installation directory is writable.
- Validate setup, API-key handling, uninstall, microphone/privacy controls, missing optional tools and non-admin operation on a clean Windows account/VM.
- Include third-party notices, versioning and a checksum; consider code signing. An unsigned test build is not a reason to disable antivirus or Windows security.
- Disclose screenshots/document transmission and API costs. Releasing to other people needs their informed consent, not the developer's permissions.

The source-beta builder is `scripts/build_source_beta.py`. It produces an allowlisted
ZIP with per-file hashes and a separate SHA256 checksum. It excludes user data,
keys, logs and installed dependencies. This is a source beta, not a new executable
or a security certification. Validate on a clean Windows machine before public
release. Remove the extracted beta directory to uninstall this source version;
disable Start with Windows in Settings first if you enabled it.
