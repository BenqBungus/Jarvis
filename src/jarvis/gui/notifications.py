from __future__ import annotations

from dataclasses import dataclass

# Keyed by the exact vocabulary evaluate_battery()/evaluate_internet()/
# evaluate_nvidia_driver()/evaluate_windows_update() actually produce in
# monitoring/checks.py -- each alert message matches exactly one category,
# so keyword-overlap ordering does not matter here.
_CATEGORY_KEYWORDS = {
    "battery": ("battery",),
    "internet": ("internet",),
    "nvidia_driver": ("driver",),
    "windows_update": ("update",),
    "disk": ("disk",),
    "temperature": ("temperature",),
}

_TITLES = {
    "battery": "Battery",
    "internet": "Internet",
    "nvidia_driver": "NVIDIA Driver",
    "windows_update": "Windows Update",
    "disk": "Disk Space",
    "temperature": "Temperature",
}


@dataclass(frozen=True)
class NotificationInfo:
    title: str
    category: str  # "info" | "warning"


def classify_alert(message: str) -> NotificationInfo:
    """Maps a BackgroundMonitor alert message to a toast title + severity."""
    lowered = message.lower()
    for kind, keywords in _CATEGORY_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return NotificationInfo(title=_TITLES[kind], category=_severity(kind, lowered))
    return NotificationInfo(title="Jarvis", category="info")


def _severity(kind: str, lowered_message: str) -> str:
    if kind == "battery":
        return "warning"  # every evaluate_battery() alert is a low-battery warning
    if kind == "internet":
        return "info" if "restored" in lowered_message else "warning"
    if kind == "disk":
        return "warning"  # every evaluate_disk_space() alert is a low-space warning
    if kind == "temperature":
        return "warning"  # every evaluate_gpu_temperature() alert is a too-hot warning
    return "info"
