from __future__ import annotations

import threading

from jarvis.gui.dashboard_model import DashboardModel
from jarvis.gui.monitor_bridge import MonitorBridge
from jarvis.monitoring import checks


def test_notify_emits_alert_received(qapp):
    bridge = MonitorBridge()
    received = []
    bridge.alert_received.connect(received.append)
    bridge.notify("Battery low: 15% remaining.")
    assert received == ["Battery low: 15% remaining."]


def test_on_reading_emits_reading_received(qapp):
    bridge = MonitorBridge()
    received = []
    bridge.reading_received.connect(lambda kind, reading: received.append((kind, reading)))
    reading = checks.BatteryReading(80, True, True)
    bridge.on_reading("battery", reading)
    assert received == [("battery", reading)]


def test_notify_works_across_threads(qapp, pump_events):
    bridge = MonitorBridge()
    received = []
    bridge.alert_received.connect(received.append)

    thread = threading.Thread(target=lambda: bridge.notify("cross-thread alert"))
    thread.start()

    assert pump_events(lambda: len(received) == 1)
    thread.join()
    assert received == ["cross-thread alert"]


def test_dashboard_model_tracks_latest_reading_per_kind(qapp):
    model = DashboardModel()
    battery_reading = checks.BatteryReading(80, True, True)
    internet_reading = checks.InternetReading(True)

    model.on_reading("battery", battery_reading)
    model.on_reading("internet", internet_reading)

    assert model.latest("battery") == battery_reading
    assert model.latest("internet") == internet_reading
    assert model.latest("nvidia_driver") is None
    assert model.all_readings() == {"battery": battery_reading, "internet": internet_reading}


def test_dashboard_model_overwrites_previous_reading_for_same_kind(qapp):
    model = DashboardModel()
    model.on_reading("battery", checks.BatteryReading(80, True, True))
    model.on_reading("battery", checks.BatteryReading(50, False, True))
    assert model.latest("battery") == checks.BatteryReading(50, False, True)


def test_dashboard_model_emits_updated_with_the_kind(qapp):
    model = DashboardModel()
    updates = []
    model.updated.connect(updates.append)
    model.on_reading("windows_update", checks.WindowsUpdateReading(3, True))
    assert updates == ["windows_update"]


def test_monitor_bridge_wired_directly_to_dashboard_model(qapp):
    # This is exactly how app.py wires them: bridge.reading_received ->
    # dashboard_model.on_reading.
    bridge = MonitorBridge()
    model = DashboardModel()
    bridge.reading_received.connect(model.on_reading)

    reading = checks.NvidiaDriverReading("NVIDIA GeForce RTX", "31.0.15.3623", True)
    bridge.on_reading("nvidia_driver", reading)

    assert model.latest("nvidia_driver") == reading
