from __future__ import annotations

from jarvis.monitoring import checks


# --- Battery -----------------------------------------------------------------


def test_battery_warns_at_first_tier_crossing():
    state = checks.BatteryState()
    message = checks.evaluate_battery(checks.BatteryReading(18, False, True), state)
    assert message is not None
    assert "18" in message


def test_battery_does_not_repeat_within_same_tier():
    state = checks.BatteryState()
    checks.evaluate_battery(checks.BatteryReading(19, False, True), state)
    message = checks.evaluate_battery(checks.BatteryReading(17, False, True), state)
    assert message is None


def test_battery_warns_again_at_a_deeper_tier():
    state = checks.BatteryState()
    checks.evaluate_battery(checks.BatteryReading(19, False, True), state)
    message = checks.evaluate_battery(checks.BatteryReading(9, False, True), state)
    assert message is not None
    assert "9" in message


def test_battery_resets_after_charging():
    state = checks.BatteryState()
    checks.evaluate_battery(checks.BatteryReading(9, False, True), state)
    checks.evaluate_battery(checks.BatteryReading(50, True, True), state)
    message = checks.evaluate_battery(checks.BatteryReading(19, False, True), state)
    assert message is not None


def test_battery_silent_while_charging():
    state = checks.BatteryState()
    message = checks.evaluate_battery(checks.BatteryReading(5, True, True), state)
    assert message is None


def test_battery_ignores_unavailable_reading():
    state = checks.BatteryState()
    message = checks.evaluate_battery(checks.BatteryReading(None, None, False), state)
    assert message is None


# --- Internet ------------------------------------------------------------------


def test_internet_alerts_when_starting_offline():
    state = checks.InternetState()
    message = checks.evaluate_internet(checks.InternetReading(connected=False), state)
    assert message is not None


def test_internet_silent_when_starting_online():
    state = checks.InternetState()
    message = checks.evaluate_internet(checks.InternetReading(connected=True), state)
    assert message is None


def test_internet_alerts_on_disconnect_then_reconnect():
    state = checks.InternetState()
    checks.evaluate_internet(checks.InternetReading(True), state)
    lost = checks.evaluate_internet(checks.InternetReading(False), state)
    restored = checks.evaluate_internet(checks.InternetReading(True), state)
    assert lost is not None and "lost" in lost.lower()
    assert restored is not None and "restored" in restored.lower()


def test_internet_silent_when_state_unchanged():
    state = checks.InternetState()
    checks.evaluate_internet(checks.InternetReading(True), state)
    message = checks.evaluate_internet(checks.InternetReading(True), state)
    assert message is None


# --- Windows Update --------------------------------------------------------------


def test_windows_update_alerts_when_pending_on_first_check():
    state = checks.WindowsUpdateState()
    message = checks.evaluate_windows_update(checks.WindowsUpdateReading(3, True), state)
    assert message is not None
    assert "3" in message


def test_windows_update_silent_on_repeat_count():
    state = checks.WindowsUpdateState()
    checks.evaluate_windows_update(checks.WindowsUpdateReading(3, True), state)
    message = checks.evaluate_windows_update(checks.WindowsUpdateReading(3, True), state)
    assert message is None


def test_windows_update_alerts_again_when_count_grows():
    state = checks.WindowsUpdateState()
    checks.evaluate_windows_update(checks.WindowsUpdateReading(3, True), state)
    message = checks.evaluate_windows_update(checks.WindowsUpdateReading(5, True), state)
    assert message is not None
    assert "5" in message


def test_windows_update_silent_when_count_drops_to_zero():
    state = checks.WindowsUpdateState()
    checks.evaluate_windows_update(checks.WindowsUpdateReading(3, True), state)
    message = checks.evaluate_windows_update(checks.WindowsUpdateReading(0, True), state)
    assert message is None


def test_windows_update_ignores_unavailable_reading():
    state = checks.WindowsUpdateState()
    message = checks.evaluate_windows_update(checks.WindowsUpdateReading(None, False), state)
    assert message is None


# --- NVIDIA driver --------------------------------------------------------------


def test_nvidia_driver_silent_on_first_reading():
    state = checks.NvidiaDriverState()
    reading = checks.NvidiaDriverReading("NVIDIA GeForce RTX", "31.0.15.3623", True)
    message = checks.evaluate_nvidia_driver(reading, state)
    assert message is None


def test_nvidia_driver_alerts_on_version_change():
    state = checks.NvidiaDriverState()
    checks.evaluate_nvidia_driver(checks.NvidiaDriverReading("NVIDIA GeForce RTX", "31.0.15.3623", True), state)
    message = checks.evaluate_nvidia_driver(checks.NvidiaDriverReading("NVIDIA GeForce RTX", "31.0.15.4000", True), state)
    assert message is not None
    assert "31.0.15.3623" in message and "31.0.15.4000" in message


def test_nvidia_driver_silent_when_version_unchanged():
    state = checks.NvidiaDriverState()
    reading = checks.NvidiaDriverReading("NVIDIA GeForce RTX", "31.0.15.3623", True)
    checks.evaluate_nvidia_driver(reading, state)
    message = checks.evaluate_nvidia_driver(reading, state)
    assert message is None


def test_nvidia_driver_silent_when_unavailable():
    state = checks.NvidiaDriverState()
    message = checks.evaluate_nvidia_driver(checks.NvidiaDriverReading(None, None, False), state)
    assert message is None


# --- Disk space ------------------------------------------------------------------


def test_disk_warns_at_first_tier_crossing():
    state = checks.DiskState()
    reading = checks.DiskReading(percent_free=12.0, free_gb=50.0, total_gb=500.0, drive="C:\\", available=True)
    message = checks.evaluate_disk_space(reading, state)
    assert message is not None
    assert "12" in message
    assert "C:\\" in message


def test_disk_does_not_repeat_within_same_tier():
    state = checks.DiskState()
    checks.evaluate_disk_space(checks.DiskReading(13.0, 50.0, 500.0, "C:\\", True), state)
    message = checks.evaluate_disk_space(checks.DiskReading(11.0, 45.0, 500.0, "C:\\", True), state)
    assert message is None


def test_disk_warns_again_at_a_deeper_tier():
    state = checks.DiskState()
    checks.evaluate_disk_space(checks.DiskReading(13.0, 50.0, 500.0, "C:\\", True), state)
    message = checks.evaluate_disk_space(checks.DiskReading(4.0, 15.0, 500.0, "C:\\", True), state)
    assert message is not None
    assert "4" in message


def test_disk_resets_after_space_recovers():
    state = checks.DiskState()
    checks.evaluate_disk_space(checks.DiskReading(4.0, 15.0, 500.0, "C:\\", True), state)
    checks.evaluate_disk_space(checks.DiskReading(50.0, 200.0, 500.0, "C:\\", True), state)
    message = checks.evaluate_disk_space(checks.DiskReading(13.0, 50.0, 500.0, "C:\\", True), state)
    assert message is not None


def test_disk_ignores_unavailable_reading():
    state = checks.DiskState()
    message = checks.evaluate_disk_space(checks.DiskReading(None, None, None, "C:\\", False), state)
    assert message is None


def test_disk_silent_when_plenty_of_space():
    state = checks.DiskState()
    message = checks.evaluate_disk_space(checks.DiskReading(80.0, 400.0, 500.0, "C:\\", True), state)
    assert message is None


# --- GPU temperature ---------------------------------------------------------------


def _gpu_reading(temperature_c):
    return checks.GpuReading(name="RTX 4060", utilization_percent=30.0, temperature_c=temperature_c, available=True)


def test_gpu_temperature_warns_when_at_or_above_threshold():
    state = checks.GpuTemperatureState()
    message = checks.evaluate_gpu_temperature(_gpu_reading(87.0), 85.0, state)
    assert message is not None
    assert "87" in message
    assert "85" in message


def test_gpu_temperature_silent_below_threshold():
    state = checks.GpuTemperatureState()
    message = checks.evaluate_gpu_temperature(_gpu_reading(70.0), 85.0, state)
    assert message is None


def test_gpu_temperature_does_not_repeat_while_still_hot():
    state = checks.GpuTemperatureState()
    checks.evaluate_gpu_temperature(_gpu_reading(87.0), 85.0, state)
    message = checks.evaluate_gpu_temperature(_gpu_reading(90.0), 85.0, state)
    assert message is None


def test_gpu_temperature_rearms_after_cooling_down():
    state = checks.GpuTemperatureState()
    checks.evaluate_gpu_temperature(_gpu_reading(87.0), 85.0, state)
    checks.evaluate_gpu_temperature(_gpu_reading(70.0), 85.0, state)
    message = checks.evaluate_gpu_temperature(_gpu_reading(88.0), 85.0, state)
    assert message is not None


def test_gpu_temperature_ignores_unavailable_reading():
    state = checks.GpuTemperatureState()
    unavailable = checks.GpuReading(name=None, utilization_percent=None, temperature_c=None, available=False)
    message = checks.evaluate_gpu_temperature(unavailable, 85.0, state)
    assert message is None


def test_gpu_temperature_respects_a_custom_threshold():
    state = checks.GpuTemperatureState()
    message = checks.evaluate_gpu_temperature(_gpu_reading(75.0), 70.0, state)
    assert message is not None
    assert "75" in message
    assert "70" in message


# --- Real (non-mocked) I/O smoke tests ---------------------------------------


def test_read_internet_returns_a_reading_without_raising():
    reading = checks.read_internet(host="1.1.1.1", port=53, timeout=1.0)
    assert isinstance(reading.connected, bool)


def test_read_cpu_returns_a_reading_without_raising():
    reading = checks.read_cpu()
    assert isinstance(reading.available, bool)


def test_read_memory_returns_a_reading_without_raising():
    reading = checks.read_memory()
    assert isinstance(reading.available, bool)


def test_read_disk_returns_a_reading_without_raising():
    reading = checks.read_disk()
    assert isinstance(reading.available, bool)
    if reading.available:
        # Sanity-check the percent-free-not-percent-used fix: free_gb must
        # never exceed total_gb, and percent_free must be a real percentage.
        assert 0.0 <= reading.percent_free <= 100.0
        assert reading.free_gb <= reading.total_gb


def test_read_gpu_returns_a_reading_without_raising():
    # Safe on machines without an NVIDIA GPU too: read_gpu() catches
    # FileNotFoundError (nvidia-smi not on PATH) and returns available=False.
    reading = checks.read_gpu(timeout=3.0)
    assert isinstance(reading.available, bool)


def test_prime_cpu_reading_does_not_raise():
    checks.prime_cpu_reading()


# --- Graceful degradation without psutil --------------------------------------


def test_read_cpu_degrades_gracefully_without_psutil(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "psutil", None)
    reading = checks.read_cpu()
    assert reading == checks.CpuReading(percent=None, available=False)


def test_read_memory_degrades_gracefully_without_psutil(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "psutil", None)
    reading = checks.read_memory()
    assert reading == checks.MemoryReading(percent_used=None, used_gb=None, total_gb=None, available=False)


def test_read_disk_degrades_gracefully_without_psutil(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "psutil", None)
    reading = checks.read_disk(drive="C:\\")
    assert reading == checks.DiskReading(percent_free=None, free_gb=None, total_gb=None, drive="C:\\", available=False)
