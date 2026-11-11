from __future__ import annotations

from jarvis.gui.notifications import classify_alert

# These are the exact message shapes evaluate_*() functions in
# monitoring/checks.py actually produce (see tests/test_monitoring_checks.py).


def test_battery_alert_is_warning():
    info = classify_alert("Battery low: 15% remaining.")
    assert info.title == "Battery"
    assert info.category == "warning"


def test_internet_lost_is_warning():
    info = classify_alert("Internet connection lost.")
    assert info.title == "Internet"
    assert info.category == "warning"


def test_internet_offline_at_startup_is_warning():
    info = classify_alert("No internet connection detected.")
    assert info.title == "Internet"
    assert info.category == "warning"


def test_internet_restored_is_info():
    info = classify_alert("Internet connection restored.")
    assert info.title == "Internet"
    assert info.category == "info"


def test_windows_update_alert_is_info():
    info = classify_alert("3 Windows update(s) available.")
    assert info.title == "Windows Update"
    assert info.category == "info"


def test_nvidia_driver_alert_is_info():
    info = classify_alert("NVIDIA driver changed: 31.0.15.3623 -> 31.0.15.4000.")
    assert info.title == "NVIDIA Driver"
    assert info.category == "info"


def test_disk_alert_is_warning():
    info = classify_alert("Low disk space: 12.0% free on C:\\.")
    assert info.title == "Disk Space"
    assert info.category == "warning"


def test_temperature_alert_is_warning():
    info = classify_alert("GPU temperature high: 90C (threshold 85C).")
    assert info.title == "Temperature"
    assert info.category == "warning"


def test_unrecognized_message_falls_back_to_generic_info():
    info = classify_alert("Something unexpected happened.")
    assert info.title == "Jarvis"
    assert info.category == "info"
