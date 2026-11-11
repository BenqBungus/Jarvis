import json
import os
import subprocess
from unittest.mock import Mock

import pytest

from jarvis import device_inventory as inventory
from jarvis.realtime import realtime_tool_schemas
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


@pytest.fixture
def hardware_data():
    return {
        "system": [{"Manufacturer": "Acer", "Model": "Nitro ANV15-51", "SystemType": "x64-based PC", "TotalPhysicalMemory": 16 * 1024**3}],
        "cpu": [{"Name": "Intel i7", "NumberOfCores": 10, "NumberOfLogicalProcessors": 16}],
        "gpu": [{"Name": "NVIDIA RTX", "DriverVersion": "32.0.1"}, {"Name": "Intel UHD", "DriverVersion": "32.0.2"}],
        "board": [{"Manufacturer": "Acer", "Product": "Board model"}],
        "bios": [{"Manufacturer": "Insyde", "SMBIOSBIOSVersion": "V1.60"}],
        "os": [{"Caption": "Windows 11", "Version": "10.0.26200", "BuildNumber": "26200", "OSArchitecture": "64-bit"}],
    }


def driver(name, device_class, version="1.2.3", **fields):
    return {"DeviceName": name, "DeviceClass": device_class, "DriverVersion": version,
            "DriverDate": "2026-01-01", "Manufacturer": "Vendor", "DriverProviderName": "Vendor",
            "InfName": "oem7.inf", "IsSigned": True, **fields}


@pytest.fixture
def driver_data():
    rows = [driver("NVIDIA GeForce RTX 4050", "DISPLAY"), driver("Intel UHD Graphics", "DISPLAY"),
            driver("Intel SMBus", "SYSTEM"), driver("Intel Management Engine Interface", "SYSTEM"),
            driver("Realtek Audio", "MEDIA"), driver("Speakers", "AudioEndpoint"),
            driver("Wi-Fi", "NET"), driver("Bluetooth Radio", "Bluetooth"),
            driver("NVIDIA Audio", "MEDIA"), driver("Unrelated PCI device", "SYSTEM")]
    return {"Drivers": rows, "Total": len(rows)}


def test_identity_reports_observed_model_and_both_gpus(monkeypatch, hardware_data):
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: hardware_data)
    result = WindowsActions().device_info()
    assert result.ok and not result.metadata["partial"]
    assert "Acer" in result.message and "Nitro ANV15-51" in result.message
    assert "NVIDIA RTX" in result.message and "Intel UHD" in result.message
    assert "16.0 GiB" in result.message
    assert len(result.metadata["hardware"]["gpu"]) == 2
    assert not result.metadata["settings_changed"]


def test_sensitive_unrequested_fields_are_discarded(monkeypatch, hardware_data):
    for rows in hardware_data.values():
        for row in rows:
            row.update(SerialNumber="PRIVATE-SERIAL", UUID="PRIVATE-UUID", UserName="PRIVATE-USER")
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: hardware_data)
    result = inventory.device_info()
    assert "PRIVATE-" not in str(result)
    assert not result.metadata["serial_numbers_collected"]
    for field in ("SerialNumber", "UUID", "UserName"):
        assert field not in inventory._DEVICE_SCRIPT


def test_partial_identity_does_not_guess_acer_or_fill_missing_gpu(monkeypatch):
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: {"cpu": [{"Name": "Observed CPU"}]})
    result = inventory.device_info()
    assert result.ok and result.metadata["partial"]
    assert "Acer" not in result.message
    assert "model: unavailable" in result.message
    assert result.metadata["hardware"]["gpu"] == []
    assert "system" in result.metadata["missing_sections"]


@pytest.mark.parametrize("data", [None, [], "invalid", {}, {"system": [None, {}]}, {"gpu": "bad shape"}])
def test_unavailable_identity_is_not_success(monkeypatch, data):
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: data)
    assert not inventory.device_info().ok


@pytest.mark.parametrize("category,expected", [
    ("display", {"NVIDIA GeForce RTX 4050", "Intel UHD Graphics"}),
    ("nvidia", {"NVIDIA GeForce RTX 4050"}),
    ("chipset", {"Intel SMBus", "Intel Management Engine Interface"}),
    ("audio", {"Realtek Audio", "Speakers", "NVIDIA Audio"}),
    ("network", {"Wi-Fi"}), ("bluetooth", {"Bluetooth Radio"}),
])
def test_driver_categories_are_separate(monkeypatch, driver_data, category, expected):
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: driver_data)
    result = WindowsActions().driver_info(category)
    assert result.ok
    assert {row["DeviceName"] for row in result.metadata["drivers"]} == expected
    assert not result.metadata["update_checked"]
    assert not result.metadata["settings_changed"]
    assert "not an update check" in result.message
    assert "OEM origin, latest version and compatibility have not been verified" in result.message
    if category == "chipset":
        assert result.metadata["chipset_classification_heuristic"]
        assert "not one chipset package version" in result.message


def test_driver_dates_and_inf_names_are_not_oem_or_installation_evidence(monkeypatch):
    data = {"Drivers": [driver("Intel SMBus", "SYSTEM", DriverDate="1968-07-18")], "Total": 1}
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: data)
    result = inventory.installed_drivers("chipset")
    assert "1968-07-18" in result.message and "oem7.inf" in result.message
    assert "not installation dates" in result.message
    assert "an old date alone does not prove" in result.message


@pytest.mark.parametrize("category", ["unknown", "all'; Remove-Item C:\\", None, ["audio"]])
def test_invalid_driver_category_never_spawns_a_command(monkeypatch, category):
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: pytest.fail("Invalid category must not query"))
    assert not WindowsActions().driver_info(category).ok
    assert not inventory.installed_drivers(category).ok


def test_all_inventory_limits_and_missing_versions_are_explicit(monkeypatch):
    data = {"Drivers": [driver(f"Device {n:03}", "MEDIA") for n in range(101)], "Total": 200}
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: data)
    result = inventory.installed_drivers()
    assert len(result.metadata["drivers"]) == 100
    assert result.metadata["partial"]
    data.update(Drivers=[driver("Device", "MEDIA", version=None)], Total=1)
    result = inventory.installed_drivers()
    assert result.metadata["partial"] and "version unavailable" in result.message


@pytest.mark.parametrize("data", [None, [], {}, {"Drivers": "bad", "Total": 1},
    {"Drivers": [], "Total": True}, {"Drivers": [{}], "Total": 0}])
def test_driver_query_failures_are_not_up_to_date(monkeypatch, data):
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: data)
    result = inventory.installed_drivers()
    assert not result.ok
    assert "unavailable" in result.message


def test_no_matches_does_not_mean_missing_driver(monkeypatch):
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: {"Drivers": [], "Total": 0})
    result = inventory.installed_drivers("nvidia")
    assert result.ok and not result.metadata["drivers"]
    assert "does not prove" in result.message


@pytest.mark.parametrize("operation", ["device", "drivers"])
def test_inventory_helpers_are_hidden_bounded_and_noninteractive(monkeypatch, operation):
    calls = []
    def run(command, **options):
        calls.append((command, options))
        return subprocess.CompletedProcess(command, 0, json.dumps({"Drivers": [], "Total": 0}), "")
    monkeypatch.setattr(subprocess, "run", run)
    (inventory.device_info if operation == "device" else inventory.installed_drivers)()
    assert len(calls) == 1
    command, options = calls[0]
    assert "-NonInteractive" in command and "Hidden" in command
    assert options["stdin"] == subprocess.DEVNULL
    assert options["timeout"] <= 20
    assert not options.get("shell")
    if os.name == "nt":
        assert options["creationflags"] & subprocess.CREATE_NO_WINDOW


@pytest.mark.parametrize("phrase,tool", [
    ("Jarvis, what laptop do I have?", "device_info"),
    ("local show bios version", "device_info"),
    ("jarvis show chipset drivers", "driver_info"),
    ("local show installed drivers", "driver_info"),
    ("jarvis what is my nvidia driver version", "nvidia_driver_info"),
])
def test_inventory_routes_are_local_read_only_and_available_to_voice(phrase, tool):
    ai = Mock()
    ai.parse_intent.side_effect = AssertionError("No AI needed for inventory")
    safety = SafetyPolicy()
    safety.confirm = Mock(side_effect=AssertionError("No admin permission for a read-only inventory"))
    router = CommandRouter(WindowsActions(dry_run=True), safety, ai=ai)
    result = router.handle(phrase)
    assert result.ok and result.action == tool and result.permission == "safe"
    assert tool in {schema["name"] for schema in realtime_tool_schemas(router.tools)}
    ai.parse_intent.assert_not_called()


def test_dry_run_never_reads_inventory(monkeypatch):
    monkeypatch.setattr(inventory, "_run_powershell_json", lambda *a, **kw: pytest.fail("Dry run must not query"))
    actions = WindowsActions(dry_run=True)
    assert actions.device_info().ok
    assert actions.nvidia_driver_info().ok
    assert actions.driver_info("audio").ok
