"""Driver updates (src/jarvis/driver_updates.py). Every system touch point is
faked: nothing here searches Windows Update, downloads, elevates or installs."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest

from jarvis.driver_updates import (
    SCAN_TTL_SECONDS,
    DriverUpdates,
    ElevationDeclined,
    _allowed_download,
    nvidia_version_from_windows,
    windows_install_script,
)

MOUSE_ID = "3f1c2a4b-0000-4000-8000-000000000001"
REALTEK_ID = "3f1c2a4b-0000-4000-8000-000000000002"
ULIC_ID = "3f1c2a4b-0000-4000-8000-000000000003"
MONITOR_ID = "3f1c2a4b-0000-4000-8000-000000000004"
FIRMWARE_ID = "3f1c2a4b-0000-4000-8000-000000000005"
MOUSE = "ASUSTeK Computer Inc. Mouse Driver Update (1.0.72.0)"
REALTEK = "Realtek - Net - 7/5/2017 12:00:00 AM - 10.19.705.2017"
ULIC = "ULIC Tek Inc. SoftwareComponent Driver Update (1.0.275.0)"
MONITOR = "LEN International (Europe) GmbH - Monitor - 10/10/2016 12:00:00 AM - 1.0.0.0"
FIRMWARE = "Contoso - Firmware - 1/1/2026 12:00:00 AM - 1.0.0.1"

# Shaped like the real 2026-09-24 scan of this laptop: three offers are for
# devices that are remembered but unplugged, and Realtek's offer carries a
# newer date but an older version than the installed driver.
SCAN = {
    "offers": [
        {"id": MONITOR_ID, "title": MONITOR, "driver_class": "OtherHardware", "hardware_id": "MONITOR\\LEN61A9",
         "provider": "LEN International (Europe) GmbH", "date": "2016-10-10", "size_mb": 0, "eula": True},
        {"id": REALTEK_ID, "title": REALTEK, "driver_class": "Networking",
         "hardware_id": "USB\\VID_0BDA&PID_8152&REV_2000", "provider": "Realtek", "date": "2017-07-05",
         "size_mb": 0.2, "eula": True},
        {"id": ULIC_ID, "title": ULIC, "driver_class": "OtherHardware", "hardware_id": "SWC\\SWCOMP_ACERSERVICECOMPONENT",
         "provider": "ULIC Tek Inc.", "date": "2026-03-18", "size_mb": 12.3, "eula": True},
        {"id": MOUSE_ID, "title": MOUSE, "driver_class": "OtherHardware", "hardware_id": "HID\\VID_0B05&PID_1910&MI_00&COL01",
         "provider": "ASUSTeK Computer Inc.", "date": "2026-08-17", "size_mb": 1.1, "eula": True},
        {"id": FIRMWARE_ID, "title": FIRMWARE, "driver_class": "Firmware", "hardware_id": "UEFI\\RES_{0000}",
         "provider": "Contoso", "date": "2026-01-01", "size_mb": 4.0, "eula": False},
    ],
    # Get-PnpDevice shape: every hardware and compatible ID, plus whether the device is plugged in.
    "devices": [
        {"name": "NVIDIA GeForce RTX 4050 Laptop GPU", "class": "Display", "present": True, "version": "32.0.16.1088",
         "provider": "NVIDIA", "date": "2026-07-22",
         "ids": ["PCI\\VEN_10DE&DEV_28A1&SUBSYS_16021025&REV_A1", "PCI\\VEN_10DE&DEV_28A1&CC_030000"]},
        {"name": "Realtek USB FE Family Controller", "class": "Net", "present": False, "version": "11.19.602.2025",
         "provider": "Realtek", "date": "2016-03-30",
         "ids": ["USB\\VID_0BDA&PID_8152&REV_2000", "USB\\VID_0BDA&PID_8152", "USB\\Class_FF&SubClass_FF"]},
        {"name": "Acer Service Software Component", "class": "SoftwareComponent", "present": True,
         "version": "1.0.274.0", "provider": "ULIC Tek Inc.", "date": "2025-10-28",
         "ids": ["SWC\\SWCOMP_ACERSERVICECOMPONENT"]},
        {"name": "TUF GAMING M3", "class": "Mouse", "present": False, "version": "1.0.62.0",
         "provider": "ASUSTeK Computer Inc.", "date": "2025-04-25",
         "ids": ["HID\\VID_0B05&PID_1910&REV_0100&MI_00&COL01", "HID\\VID_0B05&PID_1910&MI_00&COL01",
                 "HID_DEVICE_SYSTEM_MOUSE", "HID_DEVICE"]},
        {"name": "Generic Monitor (LEN T22i-10)", "class": "Monitor", "present": False,
         "version": "10.0.26100.9278", "provider": "Microsoft", "date": "2006-06-21", "ids": ["MONITOR\\LEN61A9", "*PNP09FF"]},
    ],
}
PRODUCTS_XML = ('<?xml version="1.0"?><LookupValueSearch><LookupValues>'
                '<LookupValue ParentID="120"><Name>GeForce RTX 4090</Name><Value>995</Value></LookupValue>'
                '<LookupValue ParentID="129"><Name>GeForce RTX 4050 Laptop GPU</Name><Value>1008</Value></LookupValue>'
                '</LookupValues></LookupValueSearch>')
NVIDIA_URL = "https://us.download.nvidia.com/Windows/617.14/617.14-notebook-win10-win11-64bit-international-dch-whql.exe"


def _lookup(url: str = NVIDIA_URL, version: str = "617.14") -> bytes:
    return json.dumps({"Success": "1", "IDS": [{"downloadInfo": {
        "Version": version, "Name": "GeForce%20Game%20Ready%20Driver", "ReleaseDateTime": "Tue%20Sep%2022%2C%202026",
        "DownloadURL": url, "DownloadURLFileSize": "990.85%20MB",
        "DetailsURL": "https://www.nvidia.com/en-us/drivers/details/279804/"}}]}).encode()


class _System:
    """Records every call; plays Windows Update, NVIDIA and the UAC prompt."""

    def __init__(self, tmp_path: Path, *, lookup: bytes | None = None, signature: str = "Valid",
                 installed_after: str = "32.0.16.1714", decline_uac: bool = False, report: dict | None = None):
        self.tmp_path = tmp_path
        self.lookup = lookup or _lookup()
        self.signature, self.installed_after, self.decline_uac = signature, installed_after, decline_uac
        self.report = report
        self.scripts: list[str] = []
        self.elevated: list[str] = []
        self.downloads: list[str] = []
        self.clock = 1000.0

    def powershell(self, script: str, timeout: float) -> str:
        self.scripts.append(script)
        if "Microsoft.Update.Session" in script:
            return json.dumps(SCAN)
        if "Get-AuthenticodeSignature" in script:
            subject = "CN=NVIDIA Corporation, O=NVIDIA Corporation, L=Santa Clara, S=California, C=US"
            return json.dumps({"status": self.signature, "subject": subject})
        if "Win32_VideoController" in script:
            return self.installed_after
        raise AssertionError(f"unexpected script: {script[:80]}")

    def http_get(self, url: str) -> bytes:
        return PRODUCTS_XML.encode() if "lookupValueSearch" in url else self.lookup

    def download(self, url, destination: Path, progress, cancelled) -> None:
        self.downloads.append(url)
        destination.write_bytes(b"MZ fake installer")
        progress(10, 20)
        progress(20, 20)

    def elevate(self, executable: str, parameters: str, timeout: float, on_tick) -> int | None:
        if self.decline_uac:
            raise ElevationDeclined()
        script = base64.b64decode(parameters.split("-EncodedCommand ", 1)[1]).decode("utf-16-le")
        self.elevated.append(script)
        status_path = Path(re.search(r"\$statusPath = '([^']*)'", script).group(1))
        report = self.report
        if report is None:
            if "$wanted" in script:
                wanted = re.findall(r"'([0-9a-f-]{36})'", script)
                report = {"stage": "done", "restore_point": "created", "reboot_required": True,
                          "updates": [{"id": value, "title": {MOUSE_ID: MOUSE, ULIC_ID: ULIC}.get(value, value),
                                       "result_code": 2, "hresult": "0x00000000"} for value in wanted]}
            else:
                report = {"stage": "done", "restore_point": "skipped: one per day", "exit_code": 0}
        status_path.write_text(json.dumps(report), encoding="utf-8")
        on_tick()
        return 0

    def service(self, **overrides) -> DriverUpdates:
        options = dict(powershell=self.powershell, elevate=self.elevate, http_get=self.http_get,
                       download=self.download, disk_free=lambda path: 50 * 1024 ** 3, battery=lambda: (80.0, True),
                       work_dir=self.tmp_path / "work", start_thread=lambda target: target(), clock=lambda: self.clock)
        options.update(overrides)
        return DriverUpdates(**options)


@pytest.fixture(autouse=True)
def _windows(monkeypatch):
    monkeypatch.setattr("jarvis.driver_updates.os.name", "nt")


def test_nvidia_marketing_version_comes_from_the_windows_driver_version():
    assert nvidia_version_from_windows("32.0.16.1088") == "610.88"
    assert nvidia_version_from_windows("31.0.15.5222") == "552.22"
    assert nvidia_version_from_windows("not a version") is None


def test_scan_flags_stale_unmatched_and_licensed_offers_and_finds_nvidia_update(tmp_path):
    result = _System(tmp_path).service().scan()
    assert result.ok
    offers = {offer["title"]: offer for offer in result.metadata["offers"]}
    # Newer date, older version, same vendor: still a downgrade.
    assert offers[REALTEK]["flags"] == ["older_than_installed", "not_connected"]
    assert not offers[REALTEK]["installable"] and offers[REALTEK]["installed"]["version"] == "11.19.602.2025"
    # Lenovo's 1.0.0.0 INF vs Microsoft's generic 10.0.x driver: different vendors, not a downgrade.
    assert offers[MONITOR]["flags"] == ["not_connected"] and offers[MONITOR]["installable"]
    assert offers[MOUSE]["flags"] == ["not_connected"] and offers[MOUSE]["installable"]
    assert offers[ULIC]["flags"] == [] and offers[ULIC]["installed"]["name"] == "Acer Service Software Component"
    assert offers[FIRMWARE]["flags"] == ["needs_license", "no_matching_device"] and not offers[FIRMWARE]["installable"]
    nvidia = result.metadata["nvidia"]
    assert (nvidia["status"], nvidia["installed"], nvidia["version"]) == ("update_available", "610.88", "617.14")
    assert "OLDER than the installed Realtek USB FE Family Controller driver (11.19.602.2025" in result.message
    assert "TUF GAMING M3, which is not connected right now" in result.message
    assert "NVIDIA GeForce RTX 4050 Laptop GPU: installed 610.88" in result.message
    assert f'"{MOUSE}"' in result.message


def test_scan_changes_nothing_in_dry_run(tmp_path):
    system = _System(tmp_path)
    result = system.service(dry_run=True).scan()
    assert result.ok and "dry run" in result.message
    assert system.scripts == []


def test_nvidia_lookup_off_nvidia_servers_is_treated_as_unknown(tmp_path):
    system = _System(tmp_path, lookup=_lookup(url="https://example.com/617.14-notebook-win10-win11-64bit.exe"))
    nvidia = system.service().scan().metadata["nvidia"]
    assert nvidia["status"] == "lookup_failed"
    assert not _allowed_download("http://us.download.nvidia.com/x.exe")
    assert not _allowed_download("https://download.nvidia.com.evil.example/x.exe")
    assert _allowed_download(NVIDIA_URL)


def test_install_refuses_stale_unknown_and_older_offers_without_elevating(tmp_path):
    system = _System(tmp_path)
    service = system.service()
    scan_id = service.scan().metadata["scan_id"]
    older = service.install_windows_drivers(scan_id, REALTEK)
    unknown = service.install_windows_drivers(scan_id, f"{MOUSE} | Not A Real Driver")
    wrong_scan = service.install_windows_drivers("deadbeef", MOUSE)
    assert not older.ok and "older than the installed" in older.message
    assert not unknown.ok and "Not A Real Driver" in unknown.message
    assert not wrong_scan.ok and "latest" in wrong_scan.message
    system.clock += SCAN_TTL_SECONDS + 1
    expired = service.install_windows_drivers(scan_id, MOUSE)
    assert not expired.ok and "15 minutes" in expired.message
    assert system.elevated == []


def test_windows_install_elevates_a_fixed_script_and_reports_windows_results(tmp_path):
    system = _System(tmp_path)
    service = system.service()
    finished = []
    service.on_finished = finished.append
    scan_id = service.scan().metadata["scan_id"]
    started = service.install_windows_drivers(scan_id, f"{MOUSE} | {ULIC.lower()}")
    assert started.ok and started.metadata["background_job"]
    script = system.elevated[0]
    assert MOUSE_ID in script and ULIC_ID in script and REALTEK_ID not in script
    assert MOUSE not in script  # titles never reach the administrator script
    assert "Checkpoint-Computer" in script and "Restart" not in script
    result = finished[0]
    assert result.ok and result.metadata["reboot_required"]
    assert "restart" in result.message and "restore point was created" in result.message
    status = service.status()
    assert status.metadata["finished"] and MOUSE in status.message
    assert not any((tmp_path / "work").glob("*.json"))


def test_declining_the_uac_prompt_installs_nothing(tmp_path):
    system = _System(tmp_path, decline_uac=True)
    service = system.service()
    finished = []
    service.on_finished = finished.append
    scan_id = service.scan().metadata["scan_id"]
    assert service.install_windows_drivers(scan_id, MOUSE).ok  # started; the prompt comes later
    assert not finished[0].ok and "declined" in finished[0].message


def test_failed_windows_update_run_is_reported_not_claimed(tmp_path):
    system = _System(tmp_path, report={"stage": "failed", "restore_point": "failed: disabled",
                                       "error": "None of the selected drivers is still offered by Windows Update."})
    service = system.service()
    finished = []
    service.on_finished = finished.append
    service.install_windows_drivers(service.scan().metadata["scan_id"], MOUSE)
    assert not finished[0].ok and "still offered" in finished[0].message
    assert "No restore point" in finished[0].message


def test_nvidia_install_checks_signature_and_version_then_removes_the_installer(tmp_path):
    system = _System(tmp_path)
    service = system.service()
    finished = []
    service.on_finished = finished.append
    scan_id = service.scan().metadata["scan_id"]
    wrong = service.install_nvidia_driver(scan_id, "616.00")
    assert not wrong.ok and system.downloads == []
    assert service.install_nvidia_driver(scan_id, "617.14").ok
    assert system.downloads == [NVIDIA_URL]
    script = system.elevated[0]
    assert "'-s', '-noreboot'" in script and "617.14-notebook" in script
    result = finished[0]
    assert result.ok and result.metadata["verified"] and result.metadata["installed_version"] == "617.14"
    assert not list((tmp_path / "work").glob("*.exe"))


def test_unsigned_nvidia_download_is_deleted_and_never_run(tmp_path):
    system = _System(tmp_path, signature="HashMismatch")
    service = system.service()
    finished = []
    service.on_finished = finished.append
    service.install_nvidia_driver(service.scan().metadata["scan_id"], "617.14")
    assert not finished[0].ok and "not validly signed" in finished[0].message
    assert system.elevated == []
    assert not list((tmp_path / "work").glob("*.exe"))


def test_unverified_nvidia_version_keeps_the_installer_and_says_so(tmp_path):
    system = _System(tmp_path, installed_after="32.0.16.1088")
    service = system.service()
    finished = []
    service.on_finished = finished.append
    service.install_nvidia_driver(service.scan().metadata["scan_id"], "617.14")
    assert not finished[0].ok and "not confirmed" in finished[0].message and "610.88" in finished[0].message
    assert list((tmp_path / "work").glob("*.exe"))


def test_nvidia_preflight_blocks_low_battery_and_low_disk(tmp_path):
    system = _System(tmp_path)
    low_battery = system.service(battery=lambda: (18.0, False))
    result = low_battery.install_nvidia_driver(low_battery.scan().metadata["scan_id"], "617.14")
    assert not result.ok and "charger" in result.message
    low_disk = system.service(disk_free=lambda path: 1024 ** 3)
    result = low_disk.install_nvidia_driver(low_disk.scan().metadata["scan_id"], "617.14")
    assert not result.ok and "4 GB" in result.message
    assert system.downloads == []


def test_only_one_driver_job_runs_at_a_time_and_status_shows_progress(tmp_path):
    system = _System(tmp_path)
    service = system.service(start_thread=lambda target: None)  # the job never gets to run
    scan_id = service.scan().metadata["scan_id"]
    assert service.install_windows_drivers(scan_id, MOUSE).ok
    second = service.install_nvidia_driver(scan_id, "617.14")
    assert not second.ok and "already running" in second.message
    with service._lock:
        service._job.update(stage="downloading", detail="Downloading.", done_bytes=512 * 1024 ** 2,
                            total_bytes=1024 * 1024 ** 2)
    status = service.status()
    assert not status.metadata["finished"] and "512 of 1024 MB (50%)" in status.message


def test_administrator_script_accepts_only_guids_and_quotes_paths(tmp_path):
    script = windows_install_script(tmp_path / "O'Brien" / "job.json", [MOUSE_ID])
    assert "O''Brien" in script
    with pytest.raises(ValueError):
        windows_install_script(tmp_path / "job.json", ["'; Remove-Item C:\\ -Recurse; '"])


def test_router_registers_driver_tools_behind_the_admin_gate(tmp_path, monkeypatch):
    from jarvis.realtime import RealtimeVoiceSession
    from jarvis.router import CommandRouter
    from jarvis.windows_actions import WindowsActions

    class _Decline:
        asked: list[tuple[str, str]] = []

        def confirm(self, title: str, message: str) -> bool:
            self.asked.append((title, message))
            return False

    monkeypatch.chdir(tmp_path)
    safety = _Decline()
    router = CommandRouter(WindowsActions(dry_run=True), safety)
    specs = {spec.name: spec for spec in router.tools.list_specs()}
    assert specs["scan_driver_updates"].permission == "safe"
    assert specs["driver_update_status"].permission == "safe"
    for name in ("install_windows_driver_updates", "install_nvidia_driver"):
        assert specs[name].permission == "admin" and specs[name].requires_confirmation
    execute = RealtimeVoiceSession.tool_executor_from_router(router)
    payload = execute("install_windows_driver_updates", {"scan_id": "abc", "drivers": f"{MOUSE} | {ULIC}"})
    assert payload["ok"] is False and "cancelled" in payload["message"]
    assert MOUSE in safety.asked[0][1] and ULIC in safety.asked[0][1]  # the dialog names the drivers
