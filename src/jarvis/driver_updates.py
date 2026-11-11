"""Reviewed driver updates: Windows Update driver offers and NVIDIA Game Ready.

Built by Claude at the user's request on 2026-09-24; driver work is otherwise
Codex's backend area (see docs/claude/INTEGRATION_REQUESTS.md #10).

Safety model:
- scan_driver_updates only reads: a Windows Update search, the installed
  driver list and NVIDIA's public driver lookup.
- Installing goes through the ADMIN confirmation gate with the exact driver
  titles/version as arguments, then one Windows administrator (UAC) prompt.
- Windows Update offers dated older than the installed driver for the same
  hardware are refused (Windows sometimes offers stale drivers), as are offers
  whose license would have to be accepted on the user's behalf.
- NVIDIA installers come only over HTTPS from *.download.nvidia.com, must carry
  a valid Authenticode signature from NVIDIA Corporation, and the installed
  version is read back afterwards.
- A system restore point is attempted first. Jarvis never restarts Windows.
- Installs run in the background; driver_update_status reports progress.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .models import CommandResult
from .permissions import ADMIN
from .privacy import redact_sensitive_text
from .processes import background_process_options, powershell_command
from .tool_registry import ToolParameter, ToolSpec

SCAN_TTL_SECONDS = 15 * 60
SCAN_TIMEOUT_SECONDS = 170
WINDOWS_INSTALL_TIMEOUT_SECONDS = 45 * 60
NVIDIA_INSTALL_TIMEOUT_SECONDS = 40 * 60
MIN_FREE_BYTES = 4 * 1024 ** 3
MAX_INSTALLER_BYTES = 2 * 1024 ** 3
MIN_BATTERY_PERCENT = 30
NVIDIA_PRODUCTS_URL = "https://www.nvidia.com/Download/API/lookupValueSearch.aspx?TypeID=3"
NVIDIA_LOOKUP_URL = "https://gfwsl.geforce.com/services_toolkit/services/com/nvidia/services/AjaxDriverService.php"
NVIDIA_OS_IDS = {"windows11": "135", "windows10": "57"}
_GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_INSTALLER_NAME = re.compile(r"^\d{3,4}\.\d{2}-[A-Za-z0-9._-]+\.exe$")
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Jarvis"
_RESULT_CODES = {2: "installed", 3: "installed with errors", 4: "failed", 5: "aborted"}

_SCAN_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$session = New-Object -ComObject Microsoft.Update.Session
$found = $session.CreateUpdateSearcher().Search("IsInstalled=0 and IsHidden=0 and Type='Driver'")
$offers = @(foreach ($u in $found.Updates) {
    [ordered]@{
        id = [string]$u.Identity.UpdateID; title = [string]$u.Title; driver_class = [string]$u.DriverClass
        provider = [string]$u.DriverProvider; model = [string]$u.DriverModel; hardware_id = [string]$u.DriverHardwareID
        date = $(if ($u.DriverVerDate) { $u.DriverVerDate.ToString('yyyy-MM-dd') } else { '' })
        size_mb = [math]::Round([double]$u.MaxDownloadSize / 1MB, 1); eula = [bool]$u.EulaAccepted
    }
})
$drivers = @{}
foreach ($signed in Get-CimInstance Win32_PnPSignedDriver) { if ($signed.DeviceID) { $drivers[$signed.DeviceID] = $signed } }
$offerIds = @($offers | ForEach-Object { ([string]$_.hardware_id).ToLowerInvariant() } | Where-Object { $_ })
function Test-OfferMatch($ids) {
    foreach ($candidate in $ids) {
        $value = ([string]$candidate).ToLowerInvariant()
        foreach ($offerId in $offerIds) {
            if ($value -eq $offerId -or $value.StartsWith($offerId + '&') -or $offerId.StartsWith($value + '&')) { return $true }
        }
    }
    return $false
}
# Windows Update matches an offer against ALL hardware and compatible IDs of a
# device, including devices that are not plugged in right now (an external
# monitor, a mouse, a USB adapter). Only matching devices and display adapters
# are reported; drivers of unplugged devices come from their PnP properties.
$devices = @(Get-PnpDevice | ForEach-Object {
    $ids = @(@($_.HardwareID) + @($_.CompatibleID) | Where-Object { $_ } | ForEach-Object { [string]$_ })
    if ($_.Class -ne 'Display' -and -not (Test-OfferMatch $ids)) { return }
    $driver = $drivers[$_.InstanceId]
    if ($driver) {
        $version = [string]$driver.DriverVersion; $provider = [string]$driver.DriverProviderName
        $date = $(if ($driver.DriverDate) { $driver.DriverDate.ToString('yyyy-MM-dd') } else { '' })
    } else {
        $props = @(Get-PnpDeviceProperty -InstanceId $_.InstanceId -ErrorAction SilentlyContinue `
            -KeyName DEVPKEY_Device_DriverVersion, DEVPKEY_Device_DriverProvider, DEVPKEY_Device_DriverDate)
        $version = [string]($props | Where-Object KeyName -eq 'DEVPKEY_Device_DriverVersion').Data
        $provider = [string]($props | Where-Object KeyName -eq 'DEVPKEY_Device_DriverProvider').Data
        $rawDate = ($props | Where-Object KeyName -eq 'DEVPKEY_Device_DriverDate').Data
        $date = $(if ($rawDate) { ([datetime]$rawDate).ToString('yyyy-MM-dd') } else { '' })
    }
    [ordered]@{ name = [string]$_.FriendlyName; class = [string]$_.Class; present = [bool]$_.Present
                version = $version; provider = $provider; date = $date; ids = $ids }
})
[ordered]@{ offers = $offers; devices = $devices } | ConvertTo-Json -Depth 4 -Compress
"""

# Shared by both elevated scripts: progress goes to a JSON file Jarvis polls,
# and a restore point is attempted (Windows allows one per 24 hours by default).
_ELEVATED_PRELUDE = r"""
$ErrorActionPreference = 'Stop'
function Write-Status { $report | ConvertTo-Json -Depth 5 -Compress | Set-Content -LiteralPath $statusPath -Encoding UTF8 }
function New-JarvisRestorePoint {
    try {
        Checkpoint-Computer -Description 'Jarvis driver update' -RestorePointType DEVICE_DRIVER_INSTALL `
            -WarningVariable rpWarning -WarningAction SilentlyContinue
        if ($rpWarning) { return 'skipped: ' + ($rpWarning -join ' ') }
        return 'created'
    } catch { return 'failed: ' + $_.Exception.Message }
}
"""

_WINDOWS_INSTALL_BODY = r"""
$report = [ordered]@{ stage = 'restore_point'; restore_point = $null; updates = @(); reboot_required = $false; error = $null }
Write-Status
try {
    $report.restore_point = New-JarvisRestorePoint
    $report.stage = 'searching'; Write-Status
    $session = New-Object -ComObject Microsoft.Update.Session
    $session.ClientApplicationID = 'Jarvis'
    $found = $session.CreateUpdateSearcher().Search("IsInstalled=0 and Type='Driver'")
    $collection = New-Object -ComObject Microsoft.Update.UpdateColl
    foreach ($update in $found.Updates) {
        if ($wanted -contains $update.Identity.UpdateID -and $update.EulaAccepted) { [void]$collection.Add($update) }
    }
    if ($collection.Count -eq 0) { throw 'None of the selected drivers is still offered by Windows Update.' }
    $report.stage = 'downloading'; Write-Status
    $downloader = $session.CreateUpdateDownloader(); $downloader.Updates = $collection; [void]$downloader.Download()
    $report.stage = 'installing'; Write-Status
    $installer = $session.CreateUpdateInstaller(); $installer.Updates = $collection
    $result = $installer.Install()
    for ($i = 0; $i -lt $collection.Count; $i++) {
        $item = $result.GetUpdateResult($i)
        $report.updates += [ordered]@{ id = [string]$collection.Item($i).Identity.UpdateID; title = [string]$collection.Item($i).Title
                                       result_code = [int]$item.ResultCode; hresult = ('0x{0:X8}' -f $item.HResult) }
    }
    $report.reboot_required = [bool]$result.RebootRequired
    $report.stage = 'done'
} catch { $report.stage = 'failed'; $report.error = $_.Exception.Message }
Write-Status
"""

_NVIDIA_INSTALL_BODY = r"""
$report = [ordered]@{ stage = 'restore_point'; restore_point = $null; exit_code = $null; error = $null }
Write-Status
try {
    $report.restore_point = New-JarvisRestorePoint
    $report.stage = 'installing'; Write-Status
    $process = Start-Process -FilePath $installerPath -ArgumentList '-s', '-noreboot' -Wait -PassThru
    $report.exit_code = [int]$process.ExitCode
    $report.stage = 'done'
} catch { $report.stage = 'failed'; $report.error = $_.Exception.Message }
Write-Status
"""


class ElevationDeclined(Exception):
    """The user answered No to the Windows administrator (UAC) prompt."""


def nvidia_version_from_windows(driver_version: str) -> str | None:
    """'32.0.16.1088' -> '610.88': NVIDIA's version is the last five digits."""
    if not isinstance(driver_version, str) or driver_version.count(".") != 3:
        return None
    digits = re.sub(r"\D", "", driver_version)
    if len(digits) < 5:
        return None
    tail = digits[-5:]
    return f"{int(tail[:3])}.{tail[3:]}"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", version or ""))


def _title_version(title: str) -> str:
    """Windows Update driver titles end in the version: '... - 10.19.705.2017' or '(1.0.72.0)'."""
    match = re.search(r"(\d+(?:\.\d+){1,3})\)?\s*$", title or "")
    return match.group(1) if match else ""


def _vendor(provider: str) -> str:
    match = re.match(r"\W*(\w+)", provider or "")
    return match.group(1).casefold() if match else ""


def _powershell_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _encoded_command(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


def _allowed_download(url: str) -> bool:
    parts = urllib.parse.urlsplit(url or "")
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and (host == "download.nvidia.com" or host.endswith(".download.nvidia.com"))


def _same_hardware(offer_id: str, device: dict[str, Any]) -> bool:
    """Whether a Windows Update offer targets this device: its hardware ID is
    one of the device's hardware/compatible IDs (or a more general form of one)."""
    offer_id = offer_id.casefold()
    if not offer_id:
        return False
    ids = device.get("ids")
    if isinstance(ids, str):
        ids = [ids]
    for device_id in (str(value).casefold() for value in ids or [] if value):
        if offer_id == device_id or device_id.startswith(offer_id + "&") or offer_id.startswith(device_id + "&"):
            return True
    return False


def windows_install_script(status_path: Path, update_ids: list[str]) -> str:
    if not update_ids or not all(isinstance(value, str) and _GUID.match(value) for value in update_ids):
        raise ValueError("Driver update identifiers must be Windows Update GUIDs.")
    wanted = ", ".join(_powershell_literal(value) for value in update_ids)
    return (f"$statusPath = {_powershell_literal(str(status_path))}\n$wanted = @({wanted})\n"
            + _ELEVATED_PRELUDE + _WINDOWS_INSTALL_BODY)


def nvidia_install_script(status_path: Path, installer: Path) -> str:
    if not _INSTALLER_NAME.match(installer.name):
        raise ValueError("Unexpected NVIDIA installer file name.")
    return (f"$statusPath = {_powershell_literal(str(status_path))}\n"
            f"$installerPath = {_powershell_literal(str(installer))}\n" + _ELEVATED_PRELUDE + _NVIDIA_INSTALL_BODY)


# --------------------------------------------------------------- real system

def _run_powershell(script: str, timeout: float) -> str:
    completed = subprocess.run(powershell_command(script), capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout, check=False, **background_process_options())
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "PowerShell failed.").strip()[:400])
    return completed.stdout


def _http_get(url: str, timeout: float = 30) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https endpoints
        return response.read(8 * 1024 * 1024)


def _download(url: str, destination: Path, progress: Callable[[int, int], None], cancelled: Callable[[], bool]) -> None:
    partial = destination.with_name(destination.name + ".part")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - allowlisted host
            if not _allowed_download(response.geturl()):
                raise ValueError("The download was redirected away from NVIDIA's download servers.")
            total = int(response.headers.get("Content-Length") or 0)
            if total > MAX_INSTALLER_BYTES:
                raise ValueError("The installer is larger than expected.")
            done = 0
            with partial.open("wb") as stream:
                while True:
                    if cancelled():
                        raise InterruptedError("Download cancelled.")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    done += len(chunk)
                    if done > MAX_INSTALLER_BYTES:
                        raise ValueError("The installer is larger than expected.")
                    stream.write(chunk)
                    progress(done, total)
            if total and done != total:
                raise ValueError("The download ended early.")
        os.replace(partial, destination)
    finally:
        partial.unlink(missing_ok=True)


def _run_elevated(executable: str, parameters: str, timeout: float, on_tick: Callable[[], None]) -> int | None:
    """ShellExecuteEx "runas": Windows shows its administrator (UAC) prompt and
    this waits for the process. Returns its exit code, or None if it is still
    running at the timeout -- it is never killed, since stopping an installer
    midway is worse than waiting."""
    return _shell_execute("runas", executable, parameters, timeout, on_tick)


def _shell_execute(verb: str, executable: str, parameters: str, timeout: float,
                   on_tick: Callable[[], None]) -> int | None:
    import ctypes
    from ctypes import wintypes

    class ShellExecuteInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIconOrMonitor", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    shell32.ShellExecuteExW.argtypes = [ctypes.POINTER(ShellExecuteInfo)]
    shell32.ShellExecuteExW.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    info = ShellExecuteInfo()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = verb
    info.lpFile = executable
    info.lpParameters = parameters
    info.nShow = 0  # SW_HIDE
    if not shell32.ShellExecuteExW(ctypes.byref(info)):
        error = ctypes.get_last_error()
        if error == 1223:  # ERROR_CANCELLED: the user chose No
            raise ElevationDeclined()
        raise OSError(error, "Could not start the administrator process.")
    if not info.hProcess:
        raise OSError("Windows did not return the administrator process.")
    try:
        deadline = time.monotonic() + timeout
        while kernel32.WaitForSingleObject(info.hProcess, 1000) != 0:
            on_tick()
            if time.monotonic() >= deadline:
                return None
        on_tick()
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(info.hProcess, ctypes.byref(code))
        return int(code.value)
    finally:
        kernel32.CloseHandle(info.hProcess)


def _battery() -> tuple[float, bool] | None:
    try:
        import psutil

        reading = psutil.sensors_battery()
    except Exception:  # pragma: no cover - optional dependency / no battery API
        return None
    return None if reading is None else (float(reading.percent), bool(reading.power_plugged))


def _work_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return base / "Jarvis" / "driver-updates"


def _nvidia_os_id() -> str:
    build = getattr(sys, "getwindowsversion", lambda: None)()
    return NVIDIA_OS_IDS["windows11" if build is not None and build.build >= 22000 else "windows10"]


# ------------------------------------------------------------------ service

class DriverUpdates:
    """Scan, install and report driver updates. Every system touch point is
    injectable so tests never search, download, elevate or install."""

    def __init__(self, *, dry_run: bool = False, cancelled: Callable[[], bool] | None = None,
                 powershell: Callable[[str, float], str] = _run_powershell,
                 elevate: Callable[[str, str, float, Callable[[], None]], int | None] = _run_elevated,
                 http_get: Callable[[str], bytes] = _http_get,
                 download: Callable[..., None] = _download,
                 disk_free: Callable[[Path], int] = lambda path: shutil.disk_usage(path).free,
                 battery: Callable[[], tuple[float, bool] | None] = _battery,
                 work_dir: Path | None = None,
                 start_thread: Callable[[Callable[[], None]], None] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.dry_run = dry_run
        self.cancelled = cancelled or (lambda: False)
        self._powershell, self._elevate, self._http_get, self._download = powershell, elevate, http_get, download
        self._disk_free, self._battery, self._clock = disk_free, battery, clock
        self._work_dir = work_dir or _work_dir()
        self._start_thread = start_thread or (lambda target: threading.Thread(target=target, daemon=True,
                                                                               name="jarvis-driver-update").start())
        self._lock = threading.RLock()
        self._scan: dict[str, Any] | None = None
        self._job: dict[str, Any] | None = None
        # Set by the GUI to surface the final result (called on the job thread).
        self.on_finished: Callable[[CommandResult], None] | None = None

    def tool_specs(self) -> list[tuple[ToolSpec, Callable[..., CommandResult]]]:
        return [
            (ToolSpec("scan_driver_updates",
                      "Search Windows Update for driver updates and check NVIDIA for a newer Game Ready driver. "
                      "Read-only; can take up to two minutes. Lists every offer with its date, marks offers older "
                      "than the installed driver, and returns the scan_id needed to install.",
                      category="drivers"), self.scan),
            (ToolSpec("install_windows_driver_updates",
                      "Install chosen Windows Update driver offers from the latest scan, in the background. Windows "
                      "asks for administrator approval (UAC); a restore point is attempted first; offers older than "
                      "the installed driver are refused; a restart may be needed and Jarvis never restarts by itself.",
                      permission=ADMIN, requires_confirmation=True, category="drivers", parameters=(
                          ToolParameter("scan_id", "string", "Exact scan_id returned by scan_driver_updates."),
                          ToolParameter("drivers", "string", "Exact driver titles from that scan, separated by ' | '."))),
             self.install_windows_drivers),
            (ToolSpec("install_nvidia_driver",
                      "Download NVIDIA's signed Game Ready driver found by the latest scan (about 1 GB) and install it "
                      "silently in the background with NVIDIA's express components. Windows asks for administrator "
                      "approval (UAC); a restore point is attempted first; the screen may go black briefly and audio "
                      "devices may restart. The installed version is checked afterwards.",
                      permission=ADMIN, requires_confirmation=True, category="drivers", parameters=(
                          ToolParameter("scan_id", "string", "Exact scan_id returned by scan_driver_updates."),
                          ToolParameter("version", "string", "Exact NVIDIA version from that scan, e.g. 617.14."))),
             self.install_nvidia_driver),
            (ToolSpec("driver_update_status", "Report the progress or final result of the current driver installation.",
                      category="drivers"), self.status),
        ]

    # ------------------------------------------------------------------ scan

    def scan(self) -> CommandResult:
        if self.dry_run:
            return CommandResult(True, "Would search Windows Update and NVIDIA for driver updates; dry run changes nothing.")
        if os.name != "nt":
            return CommandResult(False, "Driver updates are only supported on Windows.")
        try:
            data = json.loads(self._powershell(_SCAN_SCRIPT, SCAN_TIMEOUT_SECONDS).strip() or "{}")
        except subprocess.TimeoutExpired:
            return CommandResult(False, "Windows Update did not answer within three minutes; nothing was changed. Try again later.")
        except (RuntimeError, OSError, ValueError) as exc:
            return CommandResult(False, "Could not search Windows Update for drivers: "
                                 + redact_sensitive_text(str(exc)).text[:200])
        devices = self._as_list(data.get("devices"))
        offers = [self._assess(number, offer, devices)
                  for number, offer in enumerate(self._as_list(data.get("offers")), start=1)]
        scan = {"scan_id": uuid4().hex[:8], "created": self._clock(), "offers": offers,
                "nvidia": self._nvidia_status(devices)}
        with self._lock:
            self._scan = scan
        return CommandResult(True, self._describe(scan), metadata={
            "scan_id": scan["scan_id"], "offers": offers, "nvidia": scan["nvidia"], "read_only": True})

    @staticmethod
    def _as_list(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            value = [value]
        return [item for item in value or [] if isinstance(item, dict)]

    @staticmethod
    def _assess(number: int, offer: dict[str, Any], devices: list[dict[str, Any]]) -> dict[str, Any]:
        matches = [device for device in devices if _same_hardware(str(offer.get("hardware_id", "")), device)]
        installed = max(matches, key=lambda device: str(device.get("date", ""))) if matches else None
        flags = []
        title = str(offer.get("title", "")).strip()
        offer_date = str(offer.get("date", ""))
        offer_version = _title_version(title)
        if not offer.get("eula"):
            flags.append("needs_license")
        if installed:
            older_date = bool(offer_date and installed.get("date") and offer_date < str(installed["date"]))
            # Versions are only comparable within one vendor: Lenovo's monitor INF 1.0.0.0
            # is not "older" than Microsoft's generic 10.0.x monitor driver.
            same_vendor = _vendor(str(offer.get("provider", ""))) == _vendor(str(installed.get("provider", ""))) != ""
            older_version = bool(same_vendor and offer_version and installed.get("version")
                                 and _version_key(offer_version) < _version_key(str(installed["version"])))
            if older_date or older_version:
                flags.append("older_than_installed")
            if not any(device.get("present", True) for device in matches):
                flags.append("not_connected")
        else:
            flags.append("no_matching_device")
        return {
            "number": number, "id": str(offer.get("id", "")), "title": title, "version": offer_version,
            "date": offer_date, "size_mb": offer.get("size_mb"), "driver_class": offer.get("driver_class", ""),
            "installed": ({"name": installed.get("name", ""), "version": installed.get("version", ""),
                           "date": installed.get("date", ""), "connected": bool(installed.get("present", True))}
                          if installed else None),
            "flags": flags,
            "installable": bool(_GUID.match(str(offer.get("id", ""))))
            and not {"older_than_installed", "needs_license"} & set(flags),
        }

    def _nvidia_status(self, devices: list[dict[str, Any]]) -> dict[str, Any]:
        gpus = [device for device in devices if str(device.get("class", "")).upper() == "DISPLAY"
                and "nvidia" in str(device.get("name", "")).casefold()]
        # Prefer the GPU that is actually present over remembered/removed ones.
        gpu = next((device for device in gpus if device.get("present", True)), gpus[0] if gpus else None)
        if gpu is None:
            return {"status": "no_nvidia_gpu"}
        installed = nvidia_version_from_windows(str(gpu.get("version", "")))
        base = {"gpu": str(gpu.get("name", "")), "installed": installed}
        try:
            product = self._nvidia_product(re.sub(r"^nvidia\s+", "", base["gpu"], flags=re.IGNORECASE).strip())
            if product is None:
                return {**base, "status": "unknown_product"}
            latest = self._nvidia_latest(*product)
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            return {**base, "status": "lookup_failed"}
        newer = installed is not None and _version_key(latest["version"]) > _version_key(installed)
        return {**base, **latest, "status": "update_available" if newer else "up_to_date"}

    def _nvidia_product(self, name: str) -> tuple[str, str] | None:
        catalog = self._http_get(NVIDIA_PRODUCTS_URL).decode("utf-8", "replace")
        for parent, product, value in re.findall(
                r'<LookupValue ParentID="(\d+)"[^>]*>\s*<Name>([^<]+)</Name>\s*<Value>(\d+)</Value>', catalog):
            if product.strip().casefold() == name.casefold():
                return parent, value
        return None

    def _nvidia_latest(self, series: str, product: str) -> dict[str, Any]:
        query = urllib.parse.urlencode({
            "func": "DriverManualLookup", "psid": series, "pfid": product, "osID": _nvidia_os_id(),
            "languageCode": "1033", "beta": "0", "isWHQL": "1", "dltype": "-1", "dch": "1", "upCRD": "0",
            "qnf": "0", "sort1": "0", "numberOfResults": "1"})
        payload = json.loads(self._http_get(f"{NVIDIA_LOOKUP_URL}?{query}").decode("utf-8", "replace"))
        info = payload["IDS"][0]["downloadInfo"]
        url = urllib.parse.unquote(str(info["DownloadURL"]))
        file_name = urllib.parse.urlsplit(url).path.rsplit("/", 1)[-1]
        version = str(info["Version"]).strip()
        if not _allowed_download(url) or not _INSTALLER_NAME.match(file_name) or not re.fullmatch(r"\d{3,4}\.\d{2}", version):
            raise ValueError("NVIDIA returned an unexpected download.")
        return {"version": version, "name": urllib.parse.unquote(str(info.get("Name", "GeForce driver"))),
                "released": urllib.parse.unquote(str(info.get("ReleaseDateTime", ""))),
                "size": urllib.parse.unquote(str(info.get("DownloadURLFileSize", ""))),
                "url": url, "file_name": file_name,
                "details_url": urllib.parse.unquote(str(info.get("DetailsURL", "")))}

    @staticmethod
    def _describe(scan: dict[str, Any]) -> str:
        lines = [f"Driver scan {scan['scan_id']}."]
        offers = scan["offers"]
        if offers:
            lines.append(f"Windows Update offers {len(offers)} driver update{'s' if len(offers) != 1 else ''}:")
            for offer in offers:
                details = [offer["date"] or "undated"]
                if offer.get("size_mb"):
                    details.append(f"{offer['size_mb']} MB")
                note = ""
                installed = offer.get("installed")
                if "older_than_installed" in offer["flags"] and installed:
                    note = (f" - OLDER than the installed {installed['name']} driver ({installed['version']}, "
                            f"{installed['date']}); Jarvis will not install it")
                elif "needs_license" in offer["flags"]:
                    note = " - needs a license accepted in Windows Update; not installed by Jarvis"
                elif "no_matching_device" in offer["flags"]:
                    note = " - no matching device found on this PC; probably not needed"
                elif installed:
                    note = f" - replaces {installed['version'] or 'the current driver'} for {installed['name']}"
                    if "not_connected" in offer["flags"]:
                        note += ", which is not connected right now"
                lines.append(f"{offer['number']}. \"{offer['title']}\" ({', '.join(details)}){note}")
        else:
            lines.append("Windows Update has no driver updates for this PC.")
        nvidia = scan["nvidia"]
        status = nvidia.get("status")
        if status == "update_available":
            lines.append(f"{nvidia['gpu']}: installed {nvidia['installed']}, newer {nvidia['name']} "
                         f"{nvidia['version']} available (released {nvidia['released']}, {nvidia['size']}).")
        elif status == "up_to_date":
            lines.append(f"{nvidia['gpu']}: {nvidia['installed']} is the latest Game Ready driver "
                         f"({nvidia['version']}).")
        elif status in {"lookup_failed", "unknown_product"}:
            lines.append(f"{nvidia['gpu']}: installed {nvidia.get('installed') or 'unknown'}; "
                         "could not check NVIDIA for a newer driver.")
        lines.append("To install, pass this scan_id with the exact titles (separated by ' | ') or the exact NVIDIA version.")
        return "\n".join(lines)

    def _current_scan(self, scan_id: str) -> dict[str, Any]:
        with self._lock:
            scan = self._scan
        if not scan or scan["scan_id"] != str(scan_id).strip():
            raise ValueError("That scan is not the latest one; run scan_driver_updates again.")
        if self._clock() - scan["created"] > SCAN_TTL_SECONDS:
            raise ValueError("The driver scan is older than 15 minutes; run scan_driver_updates again.")
        return scan

    # --------------------------------------------------------------- install

    def install_windows_drivers(self, scan_id: str, drivers: str) -> CommandResult:
        try:
            scan = self._current_scan(scan_id)
            titles = [part.strip() for part in re.split(r"\s*\|\s*|\n", str(drivers)) if part.strip()]
            if not titles:
                raise ValueError("Name at least one driver from the scan.")
            by_title = {offer["title"].casefold(): offer for offer in scan["offers"]}
            chosen, problems = [], []
            for title in titles:
                offer = by_title.get(title.casefold())
                if offer is None:
                    problems.append(f"\"{title}\" is not in scan {scan['scan_id']}")
                elif "older_than_installed" in offer["flags"]:
                    problems.append(f"\"{title}\" is older than the installed driver")
                elif not offer["installable"]:
                    problems.append(f"\"{title}\" cannot be installed by Jarvis")
                elif offer not in chosen:
                    chosen.append(offer)
            if problems:
                raise ValueError("; ".join(problems))
        except ValueError as exc:
            return CommandResult(False, f"Nothing was installed: {exc}.", metadata={"executed": False})
        names = ", ".join(offer["title"] for offer in chosen)
        if self.dry_run:
            return CommandResult(True, f"Would install {len(chosen)} driver update(s): {names}. Dry run changes nothing.")
        return self._start_job("windows", f"Installing {len(chosen)} Windows Update driver(s): {names}",
                               lambda job: self._windows_worker(job, chosen))

    def install_nvidia_driver(self, scan_id: str, version: str) -> CommandResult:
        try:
            nvidia = self._current_scan(scan_id)["nvidia"]
            if nvidia.get("status") != "update_available":
                raise ValueError("the latest scan found no newer NVIDIA driver")
            if str(version).strip() != nvidia["version"]:
                raise ValueError(f"the scan found NVIDIA {nvidia['version']}, not {version}")
            if not _allowed_download(nvidia["url"]):
                raise ValueError("the NVIDIA download address is not on NVIDIA's download servers")
            system_drive = Path(os.environ.get("SystemDrive", "C:") + "\\")
            if min(self._disk_free(self._ensure_work_dir()), self._disk_free(system_drive)) < MIN_FREE_BYTES:
                raise ValueError("at least 4 GB of free disk space is needed for the download and installation")
            battery = self._battery()
            if battery and not battery[1] and battery[0] < MIN_BATTERY_PERCENT:
                raise ValueError(f"the battery is at {battery[0]:.0f}%; plug in the charger first")
        except (ValueError, OSError) as exc:
            return CommandResult(False, f"Nothing was installed: {exc}.", metadata={"executed": False})
        if self.dry_run:
            return CommandResult(True, f"Would download and install NVIDIA {nvidia['version']}. Dry run changes nothing.")
        return self._start_job("nvidia", f"Updating NVIDIA driver to {nvidia['version']}",
                               lambda job: self._nvidia_worker(job, dict(nvidia)))

    def _ensure_work_dir(self) -> Path:
        self._work_dir.mkdir(parents=True, exist_ok=True)
        return self._work_dir

    def _start_job(self, kind: str, title: str, worker: Callable[[dict[str, Any]], CommandResult]) -> CommandResult:
        with self._lock:
            if self._job and self._job["state"] == "running":
                return CommandResult(False, "A driver update is already running; ask for driver_update_status.",
                                     metadata={"executed": False})
            job = {"id": uuid4().hex[:8], "kind": kind, "title": title, "state": "running", "stage": "starting",
                   "detail": "Starting.", "started": self._clock(), "done_bytes": 0, "total_bytes": 0, "result": None}
            self._job = job
        self._start_thread(lambda: self._run_job(job, worker))
        return CommandResult(True, f"{title}. Started in the background: approve the Windows administrator prompt "
                             "(UAC) when it appears. Ask for the driver update status any time; Jarvis will not restart "
                             "the computer.", metadata={"job_id": job["id"], "background_job": True,
                                                        "completion_verified": False})

    def _run_job(self, job: dict[str, Any], worker: Callable[[dict[str, Any]], CommandResult]) -> None:
        try:
            result = worker(job)
        except ElevationDeclined:
            result = CommandResult(False, "The Windows administrator prompt was declined, so nothing was installed.")
        except InterruptedError:
            result = CommandResult(False, "Driver update cancelled before installation; nothing was installed.")
        except Exception as exc:  # the job thread must always finish with a result
            result = CommandResult(False, "Driver update failed: " + redact_sensitive_text(str(exc)).text[:300])
        with self._lock:
            job.update(state="finished", stage="finished", detail=result.message, result=result)
        callback = self.on_finished
        if callback is not None:
            try:
                callback(result)
            except Exception:  # pragma: no cover - a UI hiccup must not hide the result from status
                pass

    def _set_stage(self, job: dict[str, Any], stage: str, detail: str) -> None:
        with self._lock:
            job.update(stage=stage, detail=detail)

    def _elevated_powershell(self, job: dict[str, Any], script: str, timeout: float, status_path: Path,
                             stages: dict[str, str]) -> tuple[int | None, dict[str, Any]]:
        def tick() -> None:
            report = self._read_report(status_path)
            stage = report.get("stage")
            if stage in stages:
                self._set_stage(job, stage, stages[stage])

        self._set_stage(job, "admin", "Waiting for you to approve the Windows administrator prompt (UAC).")
        parameters = "-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand " + _encoded_command(script)
        exit_code = self._elevate("powershell.exe", parameters, timeout, tick)
        report = self._read_report(status_path)
        status_path.unlink(missing_ok=True)
        return exit_code, report

    @staticmethod
    def _read_report(path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _restore_note(report: dict[str, Any]) -> str:
        point = str(report.get("restore_point") or "")
        if point == "created":
            return " A restore point was created first."
        if point.startswith("skipped"):
            return " Windows skipped a new restore point (it allows one per day)."
        if point:
            return " No restore point could be created (System Protection may be off)."
        return ""

    def _windows_worker(self, job: dict[str, Any], chosen: list[dict[str, Any]]) -> CommandResult:
        status_path = self._ensure_work_dir() / f"{job['id']}.json"
        exit_code, report = self._elevated_powershell(
            job, windows_install_script(status_path, [offer["id"] for offer in chosen]),
            WINDOWS_INSTALL_TIMEOUT_SECONDS, status_path,
            {"restore_point": "Creating a restore point.", "searching": "Asking Windows Update for the drivers.",
             "downloading": "Downloading the drivers.", "installing": "Installing the drivers; devices may reconnect."})
        if exit_code is None:
            return CommandResult(False, "The installation is still running after 45 minutes. Check Settings > "
                                 "Windows Update > Update history before trying again.")
        if report.get("stage") != "done":
            reason = redact_sensitive_text(str(report.get("error") or "the administrator process stopped early")).text
            return CommandResult(False, f"Windows Update did not install the drivers: {reason[:300]}"
                                 + self._restore_note(report), metadata={"report": report})
        outcomes = [(str(item.get("title", "")), _RESULT_CODES.get(int(item.get("result_code", 0)), "unknown result"),
                     str(item.get("hresult", ""))) for item in report.get("updates", []) if isinstance(item, dict)]
        installed = [title for title, outcome, _code in outcomes if outcome.startswith("installed")]
        failed = [f"{title} ({outcome} {code})" for title, outcome, code in outcomes if not outcome.startswith("installed")]
        parts = []
        if installed:
            parts.append(f"Windows reports installed: {', '.join(installed)}.")
        if failed:
            parts.append(f"Not installed: {', '.join(failed)}.")
        if report.get("reboot_required"):
            parts.append("Windows needs a restart to finish; restart when convenient.")
        return CommandResult(bool(installed) and not failed, " ".join(parts or ["Windows reported no result."])
                             + self._restore_note(report),
                             metadata={"installed": installed, "failed": failed,
                                       "reboot_required": bool(report.get("reboot_required")),
                                       "restore_point": report.get("restore_point"), "verification": "windows_update_result"})

    def _nvidia_worker(self, job: dict[str, Any], nvidia: dict[str, Any]) -> CommandResult:
        work = self._ensure_work_dir()
        installer = work / nvidia["file_name"]
        status_path = work / f"{job['id']}.json"
        self._set_stage(job, "downloading", f"Downloading NVIDIA {nvidia['version']} ({nvidia['size']}).")

        def progress(done: int, total: int) -> None:
            with self._lock:
                job.update(done_bytes=done, total_bytes=total)

        self._download(nvidia["url"], installer, progress, self.cancelled)
        self._set_stage(job, "verifying", "Checking NVIDIA's digital signature.")
        if not self._nvidia_signed(installer):
            installer.unlink(missing_ok=True)
            return CommandResult(False, "The downloaded file is not validly signed by NVIDIA, so it was deleted and "
                                 "nothing was installed.", metadata={"signature_valid": False})
        exit_code, report = self._elevated_powershell(
            job, nvidia_install_script(status_path, installer), NVIDIA_INSTALL_TIMEOUT_SECONDS, status_path,
            {"restore_point": "Creating a restore point.",
             "installing": "Installing the NVIDIA driver; the screen may go black for a moment."})
        if exit_code is None:
            return CommandResult(False, "The NVIDIA installer is still running after 40 minutes; let it finish, then "
                                 "ask for a driver scan.")
        self._set_stage(job, "checking", "Reading the installed NVIDIA driver version.")
        installed = self._installed_nvidia_version()
        verified = installed == nvidia["version"]
        note = self._restore_note(report)
        if verified:
            installer.unlink(missing_ok=True)
            return CommandResult(True, f"NVIDIA driver {installed} is installed and verified. A restart is "
                                 f"recommended.{note}", metadata={"installed_version": installed, "verified": True,
                                                                  "restore_point": report.get("restore_point"),
                                                                  "installer_exit_code": report.get("exit_code")})
        error = redact_sensitive_text(str(report.get("error") or "")).text[:200]
        return CommandResult(False, f"NVIDIA {nvidia['version']} was not confirmed: the installed version is "
                             f"{installed or 'unknown'} (installer exit code {report.get('exit_code')}). {error} "
                             f"The installer was kept at {installer} if you want to run it yourself.{note}",
                             metadata={"installed_version": installed, "verified": False, "installer": str(installer)})

    def _nvidia_signed(self, installer: Path) -> bool:
        script = (f"$signature = Get-AuthenticodeSignature -LiteralPath {_powershell_literal(str(installer))}\n"
                  "[ordered]@{ status = [string]$signature.Status; subject = [string]$signature.SignerCertificate.Subject }"
                  " | ConvertTo-Json -Compress")
        try:
            data = json.loads(self._powershell(script, 120).strip() or "{}")
        except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
            return False
        return data.get("status") == "Valid" and "O=NVIDIA Corporation" in str(data.get("subject", ""))

    def _installed_nvidia_version(self) -> str | None:
        script = ("Get-CimInstance Win32_VideoController | Where-Object { $_.Name -like 'NVIDIA*' } | "
                  "Select-Object -First 1 -ExpandProperty DriverVersion")
        try:
            return nvidia_version_from_windows(self._powershell(script, 60).strip())
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            return None

    # ---------------------------------------------------------------- status

    def status(self) -> CommandResult:
        with self._lock:
            job = dict(self._job) if self._job else None
        if job is None:
            return CommandResult(True, "No driver update has run since Jarvis started.")
        if job["state"] == "finished":
            result: CommandResult = job["result"]
            return CommandResult(result.ok, result.message, metadata={**result.metadata, "job_id": job["id"],
                                                                       "finished": True})
        elapsed = int(self._clock() - job["started"])
        detail = job["detail"]
        if job["stage"] == "downloading" and job["total_bytes"]:
            percent = 100 * job["done_bytes"] / job["total_bytes"]
            detail += f" {job['done_bytes'] / 1024 ** 2:.0f} of {job['total_bytes'] / 1024 ** 2:.0f} MB ({percent:.0f}%)."
        return CommandResult(True, f"{job['title']}: {detail} Running for {elapsed // 60} min {elapsed % 60} s.",
                             metadata={"job_id": job["id"], "stage": job["stage"], "finished": False})
