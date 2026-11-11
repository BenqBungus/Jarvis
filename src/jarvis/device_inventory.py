"""Read-only Windows inventory without serial numbers or guessed update status."""
from __future__ import annotations

from datetime import datetime, timezone
import re

from .models import CommandResult
from .monitoring.checks import _run_powershell_json


_DEVICE_SCRIPT = r"""
$result = @{}
$queries = @(
    @{Key='system'; Class='Win32_ComputerSystem'; Fields=@('Manufacturer','Model','SystemType','TotalPhysicalMemory')},
    @{Key='cpu'; Class='Win32_Processor'; Fields=@('Name','NumberOfCores','NumberOfLogicalProcessors')},
    @{Key='gpu'; Class='Win32_VideoController'; Fields=@('Name','DriverVersion')},
    @{Key='board'; Class='Win32_BaseBoard'; Fields=@('Manufacturer','Product')},
    @{Key='bios'; Class='Win32_BIOS'; Fields=@('Manufacturer','SMBIOSBIOSVersion')},
    @{Key='os'; Class='Win32_OperatingSystem'; Fields=@('Caption','Version','BuildNumber','OSArchitecture')}
)
foreach ($query in $queries) {
    try {
        $result[$query.Key] = @(Get-CimInstance -ClassName $query.Class -Property $query.Fields -ErrorAction Stop |
            Select-Object -Property $query.Fields -First 16)
    } catch { $result[$query.Key] = @() }
}
ConvertTo-Json -InputObject $result -Depth 5 -Compress
""".strip()

_DRIVER_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$fields = @('DeviceName','DeviceClass','DriverVersion','DriverDate','Manufacturer','DriverProviderName','InfName','IsSigned')
$drivers = @(Get-CimInstance Win32_PnPSignedDriver -Property $fields -ErrorAction Stop |
    Select-Object DeviceName,DeviceClass,DriverVersion,Manufacturer,DriverProviderName,InfName,IsSigned,
        @{Name='DriverDate';Expression={if ($null -ne $_.DriverDate) {$_.DriverDate.ToString('yyyy-MM-dd')} else {$null}}})
ConvertTo-Json -InputObject @{Drivers=@($drivers | Select-Object -First 1000); Total=$drivers.Count} -Depth 4 -Compress
""".strip()

_DEVICE_FIELDS = {
    "system": ("Manufacturer", "Model", "SystemType", "TotalPhysicalMemory"),
    "cpu": ("Name", "NumberOfCores", "NumberOfLogicalProcessors"),
    "gpu": ("Name", "DriverVersion"), "board": ("Manufacturer", "Product"),
    "bios": ("Manufacturer", "SMBIOSBIOSVersion"), "os": ("Caption", "Version", "BuildNumber", "OSArchitecture"),
}
_DRIVER_FIELDS = ("DeviceName", "DeviceClass", "DriverVersion", "DriverDate", "Manufacturer", "DriverProviderName", "InfName", "IsSigned")
DRIVER_CATEGORIES = {"all", "display", "nvidia", "chipset", "audio", "network", "bluetooth"}


def _clean(row, fields):
    result = {}
    for field in fields:
        value = row.get(field)
        if isinstance(value, str):
            value = " ".join(value.split())[:300]
        if value is None or type(value) in (str, int, bool):
            result[field] = value
        else:
            result[field] = None
    return result


def _text(row, field):
    value = row.get(field)
    return str(value) if value is not None and value != "" else "unavailable"


def device_info() -> CommandResult:
    raw = _run_powershell_json(_DEVICE_SCRIPT, timeout=15)
    if not isinstance(raw, dict):
        return CommandResult(False, "Windows hardware inventory could not be read. No settings were changed.")
    sections, missing = {}, []
    for key, fields in _DEVICE_FIELDS.items():
        rows = raw.get(key)
        sections[key] = [_clean(row, fields) for row in rows[:16] if isinstance(row, dict)] if isinstance(rows, list) else []
        sections[key] = [row for row in sections[key] if any(value is not None and value != "" for value in row.values())]
        if not sections[key] or any(value is None or value == "" for row in sections[key] for value in row.values()):
            missing.append(key)
    system = next(iter(sections["system"]), {})
    lines = [f"Laptop manufacturer: {_text(system, 'Manufacturer')}; model: {_text(system, 'Model')}"]
    memory = system.get("TotalPhysicalMemory")
    if type(memory) is int and memory > 0:
        lines.append(f"Windows physical memory: {memory / 1024**3:.1f} GiB")
    for row in sections["cpu"]:
        lines.append(f"CPU: {_text(row, 'Name')} | {_text(row, 'NumberOfCores')} cores / {_text(row, 'NumberOfLogicalProcessors')} logical processors")
    for row in sections["gpu"]:
        lines.append(f"GPU: {_text(row, 'Name')} | Windows driver version: {_text(row, 'DriverVersion')}")
    for row in sections["board"]:
        lines.append(f"Motherboard: {_text(row, 'Manufacturer')} {_text(row, 'Product')}")
    for row in sections["bios"]:
        lines.append(f"BIOS: {_text(row, 'SMBIOSBIOSVersion')} ({_text(row, 'Manufacturer')}); read only")
    for row in sections["os"]:
        lines.append(f"Windows: {_text(row, 'Caption')} | {_text(row, 'Version')} | build {_text(row, 'BuildNumber')} | {_text(row, 'OSArchitecture')}")
    if missing:
        lines.append("Incomplete or unavailable sections: " + ", ".join(missing))
    return CommandResult(any(sections.values()), "\n".join(lines), metadata={
        "hardware": sections, "partial": bool(missing), "missing_sections": missing,
        "observed_at": datetime.now(timezone.utc).isoformat(), "source": "Windows CIM",
        "serial_numbers_collected": False, "settings_changed": False})


def _matches(row, category):
    name = str(row.get("DeviceName") or "").casefold()
    device_class = str(row.get("DeviceClass") or "").casefold()
    if category == "all":
        return True
    if category == "display":
        return device_class == "display"
    if category == "nvidia":
        return device_class == "display" and "nvidia" in name
    if category == "chipset":
        return device_class == "system" and bool(re.search(r"chipset|smbus|serial io|management engine|pci express.*root|host bridge|lpc controller", name))
    if category == "audio":
        return device_class in {"media", "audioendpoint"}
    if category == "network":
        return device_class == "net"
    return device_class == "bluetooth"


def installed_drivers(category: str = "all") -> CommandResult:
    if not isinstance(category, str) or category not in DRIVER_CATEGORIES:
        return CommandResult(False, "Choose all, display, nvidia, chipset, audio, network or bluetooth.")
    raw = _run_powershell_json(_DRIVER_SCRIPT, timeout=20)
    if (not isinstance(raw, dict) or not isinstance(raw.get("Drivers"), list)
            or type(raw.get("Total")) is not int or raw["Total"] < len(raw["Drivers"])):
        return CommandResult(False, "Installed driver inventory is unavailable; update status was not checked.")
    rows = [_clean(row, _DRIVER_FIELDS) for row in raw["Drivers"][:1000] if isinstance(row, dict)]
    matches = sorted([row for row in rows if _matches(row, category)],
                     key=lambda row: (str(row.get("DeviceClass") or ""), str(row.get("DeviceName") or "")))
    shown = matches[:100]
    partial = raw["Total"] > len(rows) or len(matches) > len(shown) or any(not row.get("DriverVersion") for row in shown)
    lines = [f"Installed {category} drivers: {len(shown)} shown. This is not an update check."]
    for row in shown:
        lines.append(f"- {_text(row, 'DeviceName')} | version {_text(row, 'DriverVersion')} | date {_text(row, 'DriverDate')} | provider {_text(row, 'DriverProviderName')} | INF {_text(row, 'InfName')}")
    if not shown:
        lines.append("No matching devices were returned; this does not prove that a driver is missing.")
    if category == "chipset":
        lines.append("Chipset-related components selected by device class/name, not one chipset package version; coverage may be incomplete.")
    if partial:
        lines.append("Inventory is partial: some records or versions are unavailable, or a display limit was reached.")
    lines.append("Driver dates are package dates, not installation dates; an old date alone does not prove a driver is outdated. OEM origin, latest version and compatibility have not been verified.")
    return CommandResult(True, "\n".join(lines), metadata={"drivers": shown, "category": category,
        "partial": partial, "total_records": raw["Total"], "matched_records": len(matches),
        "observed_at": datetime.now(timezone.utc).isoformat(), "source": "Win32_PnPSignedDriver",
        "update_checked": False, "settings_changed": False, "chipset_classification_heuristic": category == "chipset"})
