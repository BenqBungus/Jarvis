from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .processes import background_process_options, powershell_command

# See NITROSENSE_FINDINGS.md for the full investigation. Summary: NitroSense
# is backed by a real WMI provider (namespace root\WMI: classes
# AcerGamingFunction, AcerGenericMethod) exposing fan/temperature/profile
# methods (GetGamingFanSpeed, GetGamingSysInfo, GetGamingFanBehavior, ...).
# But every method uses an opaque UInt32-in/UInt64-out calling convention
# with no published documentation of what the input codes select or how the
# output bits are packed -- that encoding is Acer's private protocol.
#
# This module therefore only ever probes for PRESENCE (is the app
# installed, are its services running, does the WMI class exist). It never
# calls GetGamingFanSpeed/GetGamingSysInfo/SetGaming*/etc. or guesses at
# gmInput codes -- doing so would mean sending undocumented commands to a
# fan-control/profile interface based on guesswork, which conflicts with
# CLAUDE.md's "prefer supported APIs, avoid low-level hacks."
#
# Actual temperature/fan monitoring stays on windows_actions.py's existing,
# documented paths (nvidia-smi + MSAcpi_ThermalZoneTemperature). "Open
# NitroSense" (also in windows_actions.py) remains the integration point
# for anything users need the real app's UI for (fan curves, RGB, profiles).

_NITROSENSE_APP_NAME_PATTERN = "NitroSense"
_RELEVANT_SERVICES = (
    "ASMSvc",
    "AcerSystemCentralService",
    "AcerSysMonitorService",
    "AcerSysHardwareService",
)
_WMI_CLASSES = ("AcerGamingFunction", "AcerGenericMethod")


def _run_powershell_json(script: str, timeout: float = 15.0):
    try:
        completed = subprocess.run(
            powershell_command(script),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
            **background_process_options(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (completed.stdout or "").strip()
    if completed.returncode != 0 or not output:
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def _as_str_tuple(data) -> tuple[str, ...]:
    if not data:
        return ()
    if isinstance(data, str):
        return (data,)
    if isinstance(data, list):
        return tuple(str(item) for item in data)
    return ()


@dataclass(frozen=True)
class NitroSenseProbe:
    app_installed: bool
    services_running: tuple[str, ...]
    wmi_classes_present: tuple[str, ...]

    @property
    def has_low_level_api(self) -> bool:
        """True if the AcerGamingFunction/AcerGenericMethod WMI provider is
        present on this machine. Does NOT mean it's safe or supported to
        call -- see the module docstring and NITROSENSE_FINDINGS.md. This
        flag exists so a settings/about page can say "a low-level interface
        exists but isn't used (undocumented protocol)" instead of the less
        accurate "no API found"."""
        return bool(self.wmi_classes_present)


def probe_app_installed() -> bool:
    data = _run_powershell_json(
        f"$app = Get-StartApps | Where-Object {{ $_.Name -match '{_NITROSENSE_APP_NAME_PATTERN}' }}; "
        "[PSCustomObject]@{ Found = [bool]$app } | ConvertTo-Json -Compress"
    )
    return bool(data and data.get("Found"))


def probe_services_running() -> tuple[str, ...]:
    names_literal = ",".join(f"'{name}'" for name in _RELEVANT_SERVICES)
    data = _run_powershell_json(
        f"Get-Service -Name {names_literal} -ErrorAction SilentlyContinue | "
        "Where-Object { $_.Status -eq 'Running' } | "
        "Select-Object -ExpandProperty Name | ConvertTo-Json -Compress"
    )
    return _as_str_tuple(data)


def probe_wmi_classes_present() -> tuple[str, ...]:
    classes_literal = ",".join(f"'{name}'" for name in _WMI_CLASSES)
    script = f"""
$found = New-Object System.Collections.Generic.List[string]
foreach ($name in @({classes_literal})) {{
    $c = Get-CimClass -Namespace root/WMI -ClassName $name -ErrorAction SilentlyContinue
    if ($null -ne $c) {{ $found.Add($name) }}
}}
$found | ConvertTo-Json -Compress
""".strip()
    data = _run_powershell_json(script)
    return _as_str_tuple(data)


def probe() -> NitroSenseProbe:
    return NitroSenseProbe(
        app_installed=probe_app_installed(),
        services_running=probe_services_running(),
        wmi_classes_present=probe_wmi_classes_present(),
    )
