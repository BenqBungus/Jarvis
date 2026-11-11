from dataclasses import asdict
from io import BytesIO
import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import URLError

import pytest

from jarvis.monitoring import checks, hardware, thermal
from jarvis.monitoring.loop import BackgroundMonitor
from jarvis.router import CommandRouter
from jarvis.safety import SafetyPolicy
from jarvis.windows_actions import WindowsActions


def sensor(value=65, name="CPU Package", identifier="/intelcpu/0/temperature/0"):
    return {"Type": "Temperature", "Text": name, "SensorId": identifier, "RawValue": value, "Children": []}


@pytest.mark.parametrize("value", [None, "65 C", True, float("nan"), float("inf"), -1, 0, 200])
def test_invalid_cpu_values_are_not_temperatures(value):
    assert thermal.parse_lhm_temperatures(sensor(value)) == []


@pytest.mark.parametrize("name,identifier", [
    ("CPU Core Distance to TjMax", "/intelcpu/0/temperature/1"),
    ("CPU Package", "/lpc/nct6798d/temperature/0"),
    ("GPU Core", "/nvidiagpu/0/temperature/0"),
    ("CPU Critical", "/amdcpu/0/temperature/1"),
])
def test_non_cpu_and_relative_temperature_sensors_are_excluded(name, identifier):
    assert thermal.parse_lhm_temperatures(sensor(name=name, identifier=identifier)) == []


def test_local_api_prefers_hottest_real_cpu_sensor(monkeypatch):
    tree = {"Children": [sensor(63), sensor(71, "CPU Core #2"), sensor(95, "Distance to TjMax")]}
    monkeypatch.setattr(thermal, "_read_lhm_json", lambda: tree)
    monkeypatch.setattr(thermal, "_run_powershell_json", lambda *args, **kw: pytest.fail("No unnecessary WMI"))
    result = thermal.read_cpu_temperature()
    assert result.available and result.temperature_c == 71
    assert result.sensor == "CPU Core #2"
    assert "local API" in result.source


def test_legacy_wmi_fallback_is_validated(monkeypatch):
    monkeypatch.setattr(thermal, "_read_lhm_json", lambda: {})
    monkeypatch.setattr(thermal, "_run_powershell_json", lambda *args, **kw: [
        {"Identifier": "/amdcpu/0/temperature/0", "Name": "CPU Package", "Value": 70,
         "Source": "root/OpenHardwareMonitor"},
        {"Identifier": "/amdcpu/0/temperature/1", "Name": "CPU Package", "Value": 100,
         "Source": "unexpected provider"},
    ])
    result = thermal.read_cpu_temperature()
    assert result.available and result.temperature_c == 70
    assert result.source == "root/OpenHardwareMonitor"


def test_missing_provider_clears_previous_reading(monkeypatch):
    monkeypatch.setattr(thermal, "_read_lhm_json", lambda: sensor())
    assert thermal.read_cpu_temperature().available
    monkeypatch.setattr(thermal, "_read_lhm_json", Mock(side_effect=URLError("offline")))
    monkeypatch.setattr(thermal, "_run_powershell_json", lambda *args, **kw: None)
    result = thermal.read_cpu_temperature()
    assert not result.available and result.temperature_c is None
    assert "unavailable" in result.reason


def test_sensor_fetch_is_fixed_loopback_read_only_and_bounded(monkeypatch):
    calls = []
    class Opener:
        def open(self, url, timeout):
            calls.append((url, timeout))
            return BytesIO(json.dumps(sensor()).encode())
    def opener(*handlers):
        assert handlers[0].proxies == {}
        assert isinstance(handlers[1], thermal._NoRedirect)
        return Opener()
    monkeypatch.setattr(thermal, "build_opener", opener)
    assert thermal._read_lhm_json()["RawValue"] == 65
    assert calls == [("http://127.0.0.1:8085/data.json", 1.0)]
    with pytest.raises(URLError):
        thermal._NoRedirect().redirect_request(None, None, 302, "", {}, "https://example.com")
    monkeypatch.setattr(thermal, "build_opener", lambda *args: SimpleNamespace(
        open=lambda *args, **kw: BytesIO(b"x" * (thermal.MAX_RESPONSE + 1))))
    with pytest.raises(ValueError, match="1 MB"):
        thermal._read_lhm_json()


def test_sensor_tree_limits():
    data = sensor()
    for _ in range(34):
        data = {"Children": [data]}
    with pytest.raises(ValueError):
        thermal.parse_lhm_temperatures(data)
    with pytest.raises(ValueError):
        thermal.parse_lhm_temperatures({"Children": [{}] * 10001})


@pytest.mark.parametrize("csv,usage,temp", [
    ("RTX 4050, 25, 53", 25, 53), ("RTX 4050, N/A, 53", None, 53),
    ("RTX 4050, 0, N/A", 0, None), ("RTX 4050, nan, inf", None, None),
    ("RTX 4050, 110, -10", None, None), ('"NVIDIA, test", 7, 44', 7, 44),
])
def test_gpu_partial_and_nonfinite_values(monkeypatch, csv, usage, temp):
    monkeypatch.setattr(subprocess, "run", lambda command, **kw: subprocess.CompletedProcess(command, 0, csv, ""))
    result = checks.read_gpu()
    assert result.utilization_percent == usage
    assert result.temperature_c == temp
    assert result.available == (usage is not None or temp is not None)


def test_cpu_uses_measured_window_even_on_first_call(monkeypatch):
    cpu_percent = Mock(return_value=23.5)
    monkeypatch.setattr(checks, "_import_psutil", lambda: SimpleNamespace(cpu_percent=cpu_percent))
    assert checks.read_cpu().percent == 23.5
    cpu_percent.assert_called_once_with(interval=0.1)


def test_hardware_snapshot_reports_missing_cpu_sensor_without_losing_other_readings(monkeypatch):
    monkeypatch.setattr(checks, "read_cpu", lambda: checks.CpuReading(20, True))
    monkeypatch.setattr(checks, "read_memory", lambda: checks.MemoryReading(40, 6.4, 16, True))
    monkeypatch.setattr(checks, "read_gpu", lambda: checks.GpuReading("RTX 4050", 12, 53, True))
    monkeypatch.setattr(hardware, "read_cpu_temperature", lambda: thermal.CpuTemperatureReading())
    result = WindowsActions().system_hardware_status()
    assert result.ok and result.metadata["partial"]
    assert result.metadata["cpu_temperature"]["temperature_c"] is None
    assert "20.0%" in result.message and "53.0 C" in result.message
    assert "CPU sensor unavailable" in result.message
    assert "observed_at" in result.metadata


@pytest.mark.parametrize("phrase", ["jarvis temp", "jarvis usage", "jarvis CPU usage",
    "local gpu temperature", "jarvis show hardware status", "jarvis usage на процесора"])
def test_hardware_phrases_stay_local_and_safe(phrase):
    ai = Mock()
    ai.parse_intent.side_effect = AssertionError("Must not use AI to read hardware")
    safety = SafetyPolicy()
    safety.confirm = Mock(side_effect=AssertionError("Read-only hardware needs no confirmation"))
    router = CommandRouter(WindowsActions(dry_run=True), safety, ai=ai)
    result = router.handle(phrase)
    assert result.ok and result.action == "system_hardware_status"
    assert result.permission == "safe"
    ai.parse_intent.assert_not_called()


def test_cpu_monitor_reports_readings_and_warns_once_until_cool(monkeypatch):
    readings = iter([thermal.CpuTemperatureReading(90, True), thermal.CpuTemperatureReading(91, True),
                     thermal.CpuTemperatureReading(), thermal.CpuTemperatureReading(65, True),
                     thermal.CpuTemperatureReading(92, True)])
    monkeypatch.setattr("jarvis.monitoring.loop.read_cpu_temperature", lambda: next(readings))
    events, alerts = [], []
    monitor = BackgroundMonitor(notify=alerts.append, on_reading=lambda kind, value: events.append(kind))
    for _ in range(5):
        monitor._check_cpu_temperature()
    assert events == ["cpu_temperature"] * 5
    assert len(alerts) == 2 and all("CPU temperature high" in item for item in alerts)


def test_missing_temperature_cannot_be_reported_as_all_clear(monkeypatch):
    from jarvis.models import CommandResult
    actions = WindowsActions()
    monkeypatch.setattr(actions, "system_hardware_status", lambda: CommandResult(True, "", metadata={
        "cpu_temperature": asdict(thermal.CpuTemperatureReading()),
        "gpu": asdict(checks.GpuReading(None, None, None, False))}))
    result = actions.temperature_warning()
    assert not result.ok
    assert result.metadata["missing_sensors"] == ["CPU", "GPU"]
    assert "cannot be assessed" in result.message


def test_cpu_row_and_partial_gpu_values_render(qapp):
    from jarvis.gui.app import _format_reading
    from jarvis.gui.main_window import MainWindow
    window = MainWindow()
    try:
        window.update_dashboard("cpu_temperature", _format_reading("cpu_temperature", thermal.CpuTemperatureReading(65, True)))
        assert window._dashboard_labels["cpu_temperature"].text() == "65C"
        assert _format_reading("cpu_temperature", thermal.CpuTemperatureReading()) == "sensor unavailable"
        assert _format_reading("gpu", checks.GpuReading("RTX", None, 53, True)) == "N/A (53C)"
        assert _format_reading("gpu", checks.GpuReading("RTX", 0, None, True)) == "0% (N/A)"
    finally:
        window.close()
