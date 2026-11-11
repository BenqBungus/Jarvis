from __future__ import annotations

import json
import csv
import math
import os
import socket
import subprocess
from dataclasses import dataclass

from ..processes import background_process_options, powershell_command

# psutil backs read_cpu()/read_memory()/read_disk() below. Imported lazily
# inside each of those (not at module level) because this module is pulled
# in unconditionally by cli.py's plain text mode via monitoring/loop.py --
# a top-level import here would make psutil a mandatory dependency for
# every user, including ones who never touch --monitor/--gui.

# --- Raw readings -----------------------------------------------------------


def _run_powershell_json(script: str, timeout: float):
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


def _first(data) -> dict:
    if isinstance(data, list):
        return data[0] if data else {}
    return data or {}


@dataclass(frozen=True)
class BatteryReading:
    percent: int | None
    charging: bool | None
    available: bool


def read_battery() -> BatteryReading:
    data = _run_powershell_json(
        "Get-CimInstance -ClassName Win32_Battery | "
        "Select-Object EstimatedChargeRemaining, BatteryStatus | ConvertTo-Json -Compress",
        timeout=15.0,
    )
    if not data:
        return BatteryReading(percent=None, charging=None, available=False)
    row = _first(data)
    percent = row.get("EstimatedChargeRemaining")
    status = row.get("BatteryStatus")
    # BatteryStatus == 2 means "on AC / charging" per the Win32_Battery docs.
    charging = (status == 2) if status is not None else None
    return BatteryReading(percent=percent, charging=charging, available=percent is not None)


@dataclass(frozen=True)
class NvidiaDriverReading:
    name: str | None
    driver_version: str | None
    available: bool


def read_nvidia_driver() -> NvidiaDriverReading:
    data = _run_powershell_json(
        "Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match 'NVIDIA' } | "
        "Select-Object Name, DriverVersion | ConvertTo-Json -Compress",
        timeout=15.0,
    )
    if not data:
        return NvidiaDriverReading(name=None, driver_version=None, available=False)
    row = _first(data)
    name = row.get("Name")
    version = row.get("DriverVersion")
    return NvidiaDriverReading(name=name, driver_version=version, available=bool(version))


@dataclass(frozen=True)
class WindowsUpdateReading:
    pending_count: int | None
    available: bool


def read_windows_update() -> WindowsUpdateReading:
    # Microsoft.Update.Session searches can take 30-90s+ on a real machine,
    # hence the long timeout; run this check on a long interval.
    data = _run_powershell_json(
        "$s = New-Object -ComObject Microsoft.Update.Session; "
        "$r = $s.CreateUpdateSearcher().Search('IsInstalled=0 and IsHidden=0'); "
        "[PSCustomObject]@{ PendingCount = $r.Updates.Count } | ConvertTo-Json -Compress",
        timeout=120.0,
    )
    if not data:
        return WindowsUpdateReading(pending_count=None, available=False)
    row = _first(data)
    count = row.get("PendingCount")
    return WindowsUpdateReading(pending_count=count, available=count is not None)


@dataclass(frozen=True)
class InternetReading:
    connected: bool


def read_internet(host: str = "1.1.1.1", port: int = 53, timeout: float = 3.0) -> InternetReading:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return InternetReading(connected=True)
    except OSError:
        return InternetReading(connected=False)


def _import_psutil():
    try:
        import psutil

        return psutil
    except ImportError:
        return None


@dataclass(frozen=True)
class CpuReading:
    percent: float | None
    available: bool


def prime_cpu_reading() -> None:
    """cpu_percent(interval=None) is stateful -- it diffs against whatever
    the previous call measured, so the very first call after import always
    returns a meaningless 0.0. Callers that show a CPU reading on first
    paint should call this once at startup before the first read_cpu()."""
    psutil = _import_psutil()
    if psutil is None:
        return
    try:
        psutil.cpu_percent(interval=None)
    except Exception:  # pragma: no cover - defensive, matches read_cpu()
        pass


def read_cpu() -> CpuReading:
    psutil = _import_psutil()
    if psutil is None:
        return CpuReading(percent=None, available=False)
    try:
        # A short measured window also works on a new worker thread; the
        # nonblocking first sample on that thread would be a misleading zero.
        percent = psutil.cpu_percent(interval=0.1)
        if not math.isfinite(percent) or not 0 <= percent <= 100:
            return CpuReading(percent=None, available=False)
    except Exception:
        return CpuReading(percent=None, available=False)
    return CpuReading(percent=percent, available=True)


@dataclass(frozen=True)
class MemoryReading:
    percent_used: float | None
    used_gb: float | None
    total_gb: float | None
    available: bool


def read_memory() -> MemoryReading:
    psutil = _import_psutil()
    if psutil is None:
        return MemoryReading(percent_used=None, used_gb=None, total_gb=None, available=False)
    try:
        vm = psutil.virtual_memory()
    except Exception:
        return MemoryReading(percent_used=None, used_gb=None, total_gb=None, available=False)
    return MemoryReading(
        percent_used=vm.percent,
        used_gb=round(vm.used / (1024**3), 1),
        total_gb=round(vm.total / (1024**3), 1),
        available=True,
    )


@dataclass(frozen=True)
class DiskReading:
    # Named percent_free (not percent) deliberately: psutil.disk_usage()'s
    # own .percent field is percent-USED, and feeding that raw into a
    # low-space alert would invert the logic (fires when nearly empty,
    # silent when nearly full). This field is always the free-space share.
    percent_free: float | None
    free_gb: float | None
    total_gb: float | None
    drive: str
    available: bool


def read_disk(drive: str | None = None) -> DiskReading:
    drive = drive or (os.environ.get("SystemDrive", "C:") + "\\")
    psutil = _import_psutil()
    if psutil is None:
        return DiskReading(percent_free=None, free_gb=None, total_gb=None, drive=drive, available=False)
    try:
        usage = psutil.disk_usage(drive)
    except Exception:
        return DiskReading(percent_free=None, free_gb=None, total_gb=None, drive=drive, available=False)
    percent_free = round(100 - usage.percent, 1)
    return DiskReading(
        percent_free=percent_free,
        free_gb=round(usage.free / (1024**3), 1),
        total_gb=round(usage.total / (1024**3), 1),
        drive=drive,
        available=True,
    )


@dataclass(frozen=True)
class GpuReading:
    name: str | None
    utilization_percent: float | None
    temperature_c: float | None
    available: bool


def read_gpu(timeout: float = 3.0) -> GpuReading:
    # Direct nvidia-smi call, not PowerShell-wrapped: measured ~50ms direct
    # vs ~190ms through a spawned powershell.exe on this machine. The
    # PowerShell wrapper windows_actions.py uses for temperatures exists
    # because it also needs a combined CIM thermal-zone query in the same
    # CommandResult string -- neither reason applies to a typed, polled field.
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            errors="replace",
            **background_process_options(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return GpuReading(name=None, utilization_percent=None, temperature_c=None, available=False)

    if completed.returncode != 0:
        return GpuReading(name=None, utilization_percent=None, temperature_c=None, available=False)

    lines = (completed.stdout or "").strip().splitlines()
    if not lines:
        return GpuReading(name=None, utilization_percent=None, temperature_c=None, available=False)

    parts = next(csv.reader([lines[0]], skipinitialspace=True))
    if len(parts) < 3:
        return GpuReading(name=None, utilization_percent=None, temperature_c=None, available=False)

    def metric(value, upper):
        try:
            number = float(value)
            return number if math.isfinite(number) and 0 <= number <= upper else None
        except ValueError:
            return None

    name = parts[0].strip()
    utilization, temperature = metric(parts[1], 100), metric(parts[2], 150)
    return GpuReading(name=name or None, utilization_percent=utilization, temperature_c=temperature,
                      available=bool(name) and (utilization is not None or temperature is not None))


# --- Alerting policy ---------------------------------------------------------
# Each evaluate_* function is pure: given a fresh reading and the mutable
# state from the previous check, it decides whether the change is worth
# telling the user about and updates state in place.

BATTERY_WARNING_TIERS = (20, 10, 5)


@dataclass
class BatteryState:
    last_alert_tier: int | None = None


def evaluate_battery(reading: BatteryReading, state: BatteryState) -> str | None:
    if not reading.available:
        return None

    if reading.charging:
        state.last_alert_tier = None
        return None

    crossed = [tier for tier in BATTERY_WARNING_TIERS if reading.percent <= tier]
    if not crossed:
        state.last_alert_tier = None
        return None

    tier = min(crossed)
    if state.last_alert_tier is not None and tier >= state.last_alert_tier:
        return None

    state.last_alert_tier = tier
    return f"Battery low: {reading.percent}% remaining."


@dataclass
class InternetState:
    last_connected: bool | None = None


def evaluate_internet(reading: InternetReading, state: InternetState) -> str | None:
    message = None
    if state.last_connected is None:
        if not reading.connected:
            message = "No internet connection detected."
    elif reading.connected and not state.last_connected:
        message = "Internet connection restored."
    elif not reading.connected and state.last_connected:
        message = "Internet connection lost."

    state.last_connected = reading.connected
    return message


@dataclass
class WindowsUpdateState:
    last_count: int | None = None


def evaluate_windows_update(reading: WindowsUpdateReading, state: WindowsUpdateState) -> str | None:
    if not reading.available:
        return None

    message = None
    baseline = state.last_count or 0
    if reading.pending_count > 0 and reading.pending_count > baseline:
        message = f"{reading.pending_count} Windows update(s) available."

    state.last_count = reading.pending_count
    return message


@dataclass
class NvidiaDriverState:
    last_version: str | None = None
    initialized: bool = False


def evaluate_nvidia_driver(reading: NvidiaDriverReading, state: NvidiaDriverState) -> str | None:
    if not reading.available:
        return None

    message = None
    if state.initialized and reading.driver_version != state.last_version:
        message = f"NVIDIA driver changed: {state.last_version} -> {reading.driver_version}."

    state.last_version = reading.driver_version
    state.initialized = True
    return message


DISK_WARNING_TIERS = (15, 5)  # percent free


@dataclass
class DiskState:
    last_alert_tier: int | None = None


def evaluate_disk_space(reading: DiskReading, state: DiskState) -> str | None:
    if not reading.available or reading.percent_free is None:
        return None

    crossed = [tier for tier in DISK_WARNING_TIERS if reading.percent_free <= tier]
    if not crossed:
        state.last_alert_tier = None
        return None

    tier = min(crossed)
    if state.last_alert_tier is not None and tier >= state.last_alert_tier:
        return None

    state.last_alert_tier = tier
    return f"Low disk space: {reading.percent_free}% free on {reading.drive}."


# threshold_c is per-call, not a module constant like BATTERY_WARNING_TIERS/
# DISK_WARNING_TIERS: it comes from the user's Settings > mode volumes >
# "Temperature warning threshold" control (data/settings.json's
# mode_preferences["temperature_warning_c"], default 85 to match
# windows_actions.py's temperature_warning() command), read fresh on every
# check so a live Settings change takes effect on the next poll with no
# restart -- the same live-settings behavior every other Settings control has.


@dataclass
class GpuTemperatureState:
    alerted: bool = False


def evaluate_gpu_temperature(reading: GpuReading, threshold_c: float, state: GpuTemperatureState) -> str | None:
    if not reading.available or reading.temperature_c is None:
        return None

    if reading.temperature_c < threshold_c:
        state.alerted = False
        return None

    # Single threshold, not tiers like battery/disk: fire once on crossing
    # into the warning zone, stay silent on every subsequent poll while
    # still hot, and only re-arm once the reading drops back below the
    # threshold -- otherwise a GPU sitting at 90C would renotify every 5s.
    if state.alerted:
        return None

    state.alerted = True
    return f"GPU temperature high: {reading.temperature_c:.0f}C (threshold {threshold_c:.0f}C)."
