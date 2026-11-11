# Driver updates (2026-09-24)

"Jarvis, update my drivers" now really installs updates: Windows Update driver
offers for every device, and NVIDIA's newest Game Ready driver straight from
NVIDIA. Built by Claude at the user's request (see `INTEGRATION_REQUESTS.md`
#10 for the files touched in Codex's area).

## How it is used

In a live call or typed command, for example:

- "провери за нови драйвери" / "check for driver updates" -> `scan_driver_updates`
- "инсталирай драйвера на мишката" -> `install_windows_driver_updates` with the
  exact title(s) from that scan
- "обнови драйвера на видеокартата" -> `install_nvidia_driver` with the exact
  version from that scan
- "как върви обновяването?" -> `driver_update_status`

The Realtime instructions tell the voice model to read the findings back, ask
which ones to install, warn about the administrator prompt, the NVIDIA
download size and a possible restart, and never claim success before the
status says so.

## What the scan does (read-only, ~15 s here)

1. Windows Update search for driver offers (`Type='Driver'`).
2. Every device Windows knows, **including unplugged ones** (an external
   monitor, a mouse, a USB adapter), matched on all hardware and compatible
   IDs; drivers of unplugged devices are read from their PnP properties.
3. For each offer: the driver it would replace and flags:
   - `older_than_installed`: older date, or older version from the same vendor
     (Windows Update sometimes offers stale drivers). **Never installed.**
   - `needs_license`: would need a license accepted for the user. Not installed.
   - `not_connected`: for a remembered device that is unplugged right now.
   - `no_matching_device`: Jarvis found no device for it.
4. NVIDIA: the installed version (the Windows driver version's last five
   digits, e.g. `32.0.16.1088` -> 610.88) against NVIDIA's public driver lookup
   (product list + `DriverManualLookup`, Game Ready, WHQL, DCH).

The first real scan of this laptop found: the Lenovo T22i-10 monitor INF and
the ASUS TUF GAMING M3 mouse driver 1.0.62 -> 1.0.72 (both devices unplugged),
Acer Service Software Component 1.0.274 -> 1.0.275, a 2017 Realtek USB network
driver 10.19.705 correctly refused as older than the installed 11.19.602, and
NVIDIA 610.88 -> 617.14 (released 2026-09-22, 990.85 MB).

## Installing

Both install tools are `ADMIN` with confirmation: the app's confirmation dialog
names the exact drivers or version, then Windows shows one administrator
(UAC) prompt. The work continues in the background.

- **Windows Update:** a fixed PowerShell script, run elevated, attempts a
  restore point, finds the chosen updates again by their GUIDs (driver titles
  never reach the script), downloads and installs them with the Windows Update
  Agent, and reports each result code and whether a restart is needed.
- **NVIDIA:** HTTPS download only from `*.download.nvidia.com` (redirects
  re-checked, 2 GB cap), Authenticode signature must be `Valid` and from
  `O=NVIDIA Corporation`, then an elevated restore-point attempt and NVIDIA's
  silent install (`-s -noreboot`, NVIDIA's express components). Afterwards the
  installed version is read back; only a matching version counts as success,
  and only then is the installer deleted. Needs 4 GB free and, on battery, at
  least 30%.
- Jarvis never restarts the computer. A finished install shows a tray
  notification and the HUD feedback line.

## Verification

- `tests/test_driver_updates.py` (15 tests, all system access faked): scan
  flags on data shaped like the real scan, dry run, NVIDIA host allowlist,
  refusals (stale/unknown/older offers, wrong or expired scan, wrong version,
  low battery/disk, second concurrent job), elevated script contents (GUIDs
  only, quoted paths, no restart), Windows Update results and failures,
  declined UAC, signature failure, unverified NVIDIA version, progress
  reporting, and the router's ADMIN gate showing the driver names.
- `tests/test_realtime_voice.py`: every tool named in the voice guidance exists.
- On this laptop, without any UAC prompt or install: the real scan; the
  ShellExecuteEx path with the non-elevating "open" verb (exit code read back);
  both administrator scripts run unelevated against targets that cannot
  install anything (they fail cleanly and write their status file); the
  signature check on a Microsoft binary.

## Not yet verified (needs the user)

The UAC prompt itself and a real install. NVIDIA's silent switches are the
documented `-s -noreboot`; if a future package ignores them the result will
say the version was not confirmed and keep the installer for a manual run.

## Undo

A restore point is attempted before every install (Windows allows one per 24
hours by default; the result says whether it was created). A single driver
can also be rolled back in Device Manager > the device > Driver > Roll Back
Driver. Older NVIDIA drivers remain available on NVIDIA's site.
