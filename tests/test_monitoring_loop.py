from __future__ import annotations

import threading
import time

from jarvis.monitoring import checks
from jarvis.monitoring.loop import BackgroundMonitor


def test_check_battery_notifies_on_low_battery(monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(15, False, True))
    notified = []
    monitor = BackgroundMonitor(notify=notified.append)
    monitor._check_battery()
    assert len(notified) == 1
    assert "15" in notified[0]


def test_check_battery_silent_when_charging(monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(15, True, True))
    notified = []
    monitor = BackgroundMonitor(notify=notified.append)
    monitor._check_battery()
    assert notified == []


def test_check_internet_notifies_when_offline(monkeypatch):
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(False))
    notified = []
    monitor = BackgroundMonitor(notify=notified.append)
    monitor._check_internet()
    assert len(notified) == 1


def test_check_nvidia_driver_silent_on_first_reading(monkeypatch):
    monkeypatch.setattr(
        checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading("NVIDIA GeForce RTX", "1.2.3", True)
    )
    notified = []
    monitor = BackgroundMonitor(notify=notified.append)
    monitor._check_nvidia_driver()
    assert notified == []


def test_check_windows_update_notifies_when_pending(monkeypatch):
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(2, True))
    notified = []
    monitor = BackgroundMonitor(notify=notified.append)
    monitor._check_windows_update()
    assert len(notified) == 1
    assert "2" in notified[0]


def test_check_gpu_notifies_when_temperature_crosses_default_threshold(monkeypatch):
    monkeypatch.setattr(checks, "read_gpu", lambda: checks.GpuReading("RTX 4060", 40.0, 90.0, True))
    notified = []
    monitor = BackgroundMonitor(notify=notified.append)
    monitor._check_gpu()
    assert len(notified) == 1
    assert "90" in notified[0]


def test_check_gpu_silent_below_default_threshold(monkeypatch):
    monkeypatch.setattr(checks, "read_gpu", lambda: checks.GpuReading("RTX 4060", 40.0, 70.0, True))
    notified = []
    monitor = BackgroundMonitor(notify=notified.append)
    monitor._check_gpu()
    assert notified == []


def test_check_gpu_uses_the_live_settings_temperature_threshold(monkeypatch):
    from jarvis.user_settings import JarvisSettings

    monkeypatch.setattr(checks, "read_gpu", lambda: checks.GpuReading("RTX 4060", 40.0, 72.0, True))
    settings = JarvisSettings(mode_preferences={"temperature_warning_c": 70})
    notified = []
    monitor = BackgroundMonitor(notify=notified.append, settings=settings)
    monitor._check_gpu()
    assert len(notified) == 1
    assert "72" in notified[0]
    assert "70" in notified[0]


def test_check_gpu_threshold_change_takes_effect_without_reconstructing_the_monitor(monkeypatch):
    # settings is held live (see loop.py's __init__ comment), same as
    # router.py/GuiSafetyPolicy -- a Settings page Save must take effect on
    # the very next poll, no app restart needed.
    from jarvis.user_settings import JarvisSettings

    monkeypatch.setattr(checks, "read_gpu", lambda: checks.GpuReading("RTX 4060", 40.0, 72.0, True))
    settings = JarvisSettings(mode_preferences={"temperature_warning_c": 90})
    notified = []
    monitor = BackgroundMonitor(notify=notified.append, settings=settings)
    monitor._check_gpu()
    assert notified == []  # 72 < 90, no alert yet

    settings.mode_preferences["temperature_warning_c"] = 70
    monitor._check_gpu()
    assert len(notified) == 1  # now 72 >= 70


def test_check_battery_reports_reading_even_without_an_alert(monkeypatch):
    reading = checks.BatteryReading(80, True, True)
    monkeypatch.setattr(checks, "read_battery", lambda: reading)
    seen = []
    monitor = BackgroundMonitor(notify=lambda message: None, on_reading=lambda kind, r: seen.append((kind, r)))
    monitor._check_battery()
    assert seen == [("battery", reading)]


def test_each_check_reports_its_own_kind(monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(80, True, True))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(
        checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading("NVIDIA GeForce RTX", "1.2.3", True)
    )
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(0, True))

    seen_kinds = []
    monitor = BackgroundMonitor(notify=lambda message: None, on_reading=lambda kind, r: seen_kinds.append(kind))
    monitor._check_battery()
    monitor._check_internet()
    monitor._check_nvidia_driver()
    monitor._check_windows_update()
    assert seen_kinds == ["battery", "internet", "nvidia_driver", "windows_update"]


def test_on_reading_is_optional_and_defaults_to_none(monkeypatch):
    # Backward compatibility: existing callers that don't pass on_reading
    # must keep working exactly as before.
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(15, False, True))
    notified = []
    monitor = BackgroundMonitor(notify=notified.append)
    monitor._check_battery()  # must not raise despite no on_reading callback
    assert len(notified) == 1


def test_a_raising_on_reading_callback_does_not_break_alerting(monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(15, False, True))
    notified = []

    def flaky_on_reading(kind, reading):
        raise RuntimeError("simulated UI callback failure")

    monitor = BackgroundMonitor(notify=notified.append, on_reading=flaky_on_reading)
    monitor._check_battery()  # on_reading raises internally, must not propagate or block notify
    assert len(notified) == 1
    assert "15" in notified[0]


def test_start_spawns_one_thread_per_check_and_stop_ends_them(monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(None, None, False))
    monkeypatch.setattr(checks, "read_internet", lambda: checks.InternetReading(True))
    monkeypatch.setattr(checks, "read_nvidia_driver", lambda: checks.NvidiaDriverReading(None, None, False))
    monkeypatch.setattr(checks, "read_windows_update", lambda: checks.WindowsUpdateReading(None, False))
    monkeypatch.setattr(checks, "read_cpu", lambda: checks.CpuReading(None, False))
    monkeypatch.setattr(checks, "read_memory", lambda: checks.MemoryReading(None, None, None, False))
    monkeypatch.setattr(checks, "read_gpu", lambda: checks.GpuReading(None, None, None, False))
    monkeypatch.setattr(checks, "read_disk", lambda: checks.DiskReading(None, None, None, "C:\\", False))
    from jarvis.monitoring.thermal import CpuTemperatureReading
    monkeypatch.setattr("jarvis.monitoring.loop.read_cpu_temperature", lambda: CpuTemperatureReading())

    monitor = BackgroundMonitor(notify=lambda message: None)
    monitor.start()
    try:
        assert len(monitor._threads) == 9
        assert all(thread.is_alive() for thread in monitor._threads)
    finally:
        monitor.stop()

    for thread in monitor._threads:
        thread.join(timeout=2)
        assert not thread.is_alive()


def test_a_raising_check_does_not_kill_the_background_thread():
    calls = {"n": 0}

    def flaky_job() -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated failure")

    monitor = BackgroundMonitor(notify=lambda message: None)
    thread = threading.Thread(target=monitor._run_loop, args=(flaky_job, 0.01), daemon=True)
    thread.start()
    try:
        deadline = time.time() + 2
        while calls["n"] < 3 and time.time() < deadline:
            time.sleep(0.01)
        assert calls["n"] >= 3, "job() should keep being called after it raises once"
        assert thread.is_alive()
    finally:
        monitor.stop()
        thread.join(timeout=2)
    assert not thread.is_alive()


def test_slow_check_cannot_publish_readings_or_alerts_after_stop(monkeypatch):
    entered = threading.Event()
    release = threading.Event()

    def slow_read():
        entered.set()
        assert release.wait(2)
        return checks.BatteryReading(10, False, True)

    monkeypatch.setattr(checks, "read_battery", slow_read)
    readings, alerts = [], []
    monitor = BackgroundMonitor(notify=alerts.append, on_reading=lambda *args: readings.append(args))
    thread = threading.Thread(target=monitor._check_battery)
    thread.start()
    try:
        assert entered.wait(2)
        monitor.stop()
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive()
    assert readings == []
    assert alerts == []


def test_start_is_idempotent_and_stopped_monitor_cannot_restart(monkeypatch):
    monitor = BackgroundMonitor(notify=lambda message: None)
    # No hardware queries: these worker threads only wait for shutdown.
    monkeypatch.setattr(monitor, "_run_loop", lambda *args: monitor._stop_event.wait(2))
    monitor.start()
    first_threads = list(monitor._threads)
    try:
        monitor.start()
        assert monitor._threads == first_threads
        assert len(first_threads) == 9
    finally:
        monitor.stop()
        for thread in first_threads:
            thread.join(2)
            assert not thread.is_alive()
    monitor.start()
    assert monitor._threads == first_threads


def test_callback_can_stop_monitor_without_deadlock(monkeypatch):
    monkeypatch.setattr(checks, "read_battery", lambda: checks.BatteryReading(10, False, True))
    alerts = []
    monitor = BackgroundMonitor(notify=alerts.append)
    monitor.on_reading = lambda *args: monitor.stop()
    monitor._check_battery()
    assert alerts == []
