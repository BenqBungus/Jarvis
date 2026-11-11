# NitroSense Integration Research

Investigated whether NitroSense (Acer's Nitro/Predator laptop control utility) exposes temperature, fan-mode, or update data through a WMI provider, a local service, logs, the registry, or a CLI, so Jarvis could read that data directly instead of only being able to launch the app.

Probed live on the dev machine (an Acer laptop with NitroSense installed) via PowerShell/WMI/registry queries. Findings below; the reusable, read-only parts of this probe are implemented in [`src/jarvis/nitrosense.py`](src/jarvis/nitrosense.py).

## What's installed

- The NitroSense app itself: a UWP app, package `ULICTekInc.NitroSenseforNotebook`.
- A cluster of Acer background services (`Get-Service | Where-Object Name -match 'Acer'`), all running: `AASSvc`, `AcerARTAIMMXDriverService`, `AcerARTAIMMXService`, `AcerCCAgentSvis`, `AcerDeviceEnablingServiceV2`, `AcerDeviceInfoAgentService`, `AcerDIAgentSvis`, `AcerEZSvc`, `AcerGAICameraService`, `AcerLightingService`, `AcerPixyService`, `AcerQAAgentSvis`, `AcerServiceSvc`, and **`ASMSvc`** ("Acer System Monitor Service") — the one most likely to be NitroSense's actual backend.
- `ASMSvc`'s binary is `AcerSystemCentralService.exe`, installed under `C:\WINDOWS\System32\DriverStore\FileRepository\sysmonitorservice.inf_amd64_*\x64\`. Two other executables live in the same folder — `AcerSysHardwareService.exe` and `AcerSysMonitorService.exe` — but neither is separately registered as a Windows service under those names; only `ASMSvc` is a real registered service. They're most likely spawned as child processes by `AcerSystemCentralService.exe`, not independently queryable services.
- Registry: `HKLM:\SOFTWARE\Acer\NitroSense` holds only a GUID value. `HKLM:\SOFTWARE\Acer\XSense` holds a `lastContentPath` pointing at a cached content bundle (`C:\ProgramData\OEM\EZService\content\main-0.483.0-92-prd.zip`). Neither exposes live sensor data — just app bookkeeping.

## The real finding: a WMI provider exists

`root\WMI` (the standard vendor-extension WMI namespace, same one Windows exposes `MSAcpi_ThermalZoneTemperature` through) contains genuine Acer-specific classes:

- `AcerGamingFunction` — methods include `GetGamingFanSpeed`, `GetGamingFanBehavior`, `GetGamingFanTable`, `GetGamingSysInfo`, `GetGamingProfile`, `GetGamingRgbKb`, `GetGamingLED`, `GetCPUOverclockingProfile`, plus a full set of `Set*` counterparts.
- `AcerGenericMethod` — a generic `GetFunction`/`SetFunction`/`GetStorageInformation` interface.
- Also present but not investigated further: `AcerGenericEvent`, `KernelThermalPolicyChange`, `KernelThermalConstraintChange`, `WiFiSensorNotificationEvent`, `WiFi_GenericSensorData`, `AcerBiosConfigurationTool`.

This means the "no API, only open-the-app" fallback originally assumed **isn't quite the full picture** — NitroSense (and PredatorSense on Predator-branded models) is almost certainly a UI shell over exactly this WMI provider.

## Why Jarvis doesn't call it

Every method on both classes shares one calling convention:

```
UInt32 gmInput   [in]
UInt64 gmOutput  [out]
```

A single opaque integer in, a single opaque 64-bit integer out — no structured parameters, no published schema. This is Acer's private protocol: `gmInput` presumably selects a sub-function and packs arguments (which fan zone, which profile slot, etc.) into bit fields, and `gmOutput` packs the answer back the same way. None of this is publicly documented by Acer. Community reverse-engineering of similar Acer/Clevo WMI interfaces exists for some models, but the exact codes are model/firmware-specific and unverified for this hardware.

Calling `Get*` methods with a guessed `gmInput` and trying to decode `gmOutput` byte-by-byte would mean:

- Potentially invoking the wrong sub-function on a **fan-control and profile-switching** interface based on guesswork, not documentation — a real (if not obviously "destructive" in the data-loss sense) safety concern.
- Reporting confidently-labeled but possibly-wrong data if the decoding is subtly off (e.g., mislabeling a fan-table value as a temperature) — worse for a monitoring feature than not showing the data at all.
- Directly conflicting with CLAUDE.md's guardrail: *"Prefer Windows-supported APIs and commands over low-level hacks... avoid kernel drivers or kernel-level changes unless the user explicitly approves a separate, audited design."*

So the decision is: **don't call it.** `SetGamingFanSpeed`/`SetGamingProfile`/etc. are never invoked, and no `gmOutput` value is ever decoded or displayed as if it were a trustworthy reading.

## What Jarvis does instead

- **Temperature/fan monitoring** stays on the paths Codex already built in `windows_actions.py`: `nvidia-smi` for GPU temperature and `Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature` for ACPI thermal zones — both documented, standard interfaces.
- **"Open NitroSense"** (`windows_actions.open_nitrosense()`) remains the way to reach fan curves, RGB, and profile switching — through Acer's own UI, which presumably talks to `AcerGamingFunction` correctly because Acer wrote both sides of the protocol.
- **Presence detection only**: [`src/jarvis/nitrosense.py`](src/jarvis/nitrosense.py) provides `probe()`, returning a `NitroSenseProbe(app_installed, services_running, wmi_classes_present)`. It never calls a `Get*`/`Set*` method — it only checks whether the app is in the Start Menu, whether `ASMSvc` is running, and whether the `AcerGamingFunction`/`AcerGenericMethod` WMI classes exist (`Get-CimClass`, not `Get-CimInstance` or `Invoke-CimMethod`). `NitroSenseProbe.has_low_level_api` reflects that a low-level interface exists, explicitly documented as *"does NOT mean it's safe or supported to call."*

## If someone wants to go further later

Decoding `gmInput`/`gmOutput` for this specific model would need to be its own explicitly-scoped, audited effort — e.g. capturing real NitroSense-to-service traffic (ETW tracing or a WMI method call logger) while using the real NitroSense app, to empirically learn what codes correspond to what, before writing any code that calls `Set*`. That's a different, much larger task than this investigation, and squarely the kind of "separate, audited design" CLAUDE.md says needs explicit approval first.
