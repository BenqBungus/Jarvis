"""Read-only CPU sensors from an already running hardware monitor."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import time
from http.client import HTTPException
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener

from .checks import _run_powershell_json


LHM_URL = "http://127.0.0.1:8085/data.json"
MAX_RESPONSE = 1024 * 1024
_CPU_SENSOR = re.compile(r"^/(?:intelcpu|amdcpu|cpu)/\d+/temperature/\d+$", re.I)
_EXCLUDED = re.compile(r"distance|tjmax|critical|threshold|limit|offset", re.I)
_WMI_SCRIPT = r"""
$rows = @()
foreach ($namespace in @('root/LibreHardwareMonitor', 'root/OpenHardwareMonitor')) {
    try {
        $sensors = @(Get-CimInstance -Namespace $namespace -ClassName Sensor -Filter "SensorType = 'Temperature'" -ErrorAction Stop)
        foreach ($sensor in $sensors) {
            if ($sensor.Identifier -match '^/(intelcpu|amdcpu|cpu)/\d+/temperature/\d+$') {
                $rows += [pscustomobject]@{Identifier=$sensor.Identifier; Name=$sensor.Name; Value=$sensor.Value; Source=$namespace}
            }
        }
    } catch { }
}
ConvertTo-Json -InputObject @($rows) -Compress -Depth 4
""".strip()


@dataclass(frozen=True)
class CpuTemperatureReading:
    temperature_c: float | None = None
    available: bool = False
    sensor: str = ""
    source: str = ""
    reason: str = "CPU sensor unavailable. Run a supported hardware monitor; ACPI zones are not CPU core temperatures."


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise URLError("Sensor redirects are refused")


def _read_lhm_json():
    # Fixed loopback GET only: no proxy, discovery, credentials or control endpoints.
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    deadline = time.monotonic() + 2.0
    with opener.open(LHM_URL, timeout=1.0) as response:
        chunks, size = [], 0
        while True:
            if time.monotonic() > deadline:
                raise ValueError("Sensor response timed out")
            chunk = response.read1(min(65536, MAX_RESPONSE + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_RESPONSE:
                raise ValueError("Sensor response exceeds 1 MB")
            chunks.append(chunk)
    return json.loads(b"".join(chunks))


def _valid_sensor(identifier, name, value, source):
    if not isinstance(identifier, str) or not _CPU_SENSOR.fullmatch(identifier):
        return None
    if not isinstance(name, str) or not name or _EXCLUDED.search(name):
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 125:
        return None
    return CpuTemperatureReading(float(value), True, name[:120], source, "")


def parse_lhm_temperatures(data) -> list[CpuTemperatureReading]:
    pending, result, seen = [(data, 0)], [], 0
    while pending:
        node, depth = pending.pop()
        seen += 1
        if seen > 10000 or depth > 32:
            raise ValueError("Sensor tree exceeds limits")
        if not isinstance(node, dict):
            continue
        if node.get("Type") == "Temperature":
            reading = _valid_sensor(node.get("SensorId"), node.get("Text"), node.get("RawValue"), "LibreHardwareMonitor local API")
            if reading:
                result.append(reading)
        children = node.get("Children", [])
        if not isinstance(children, list) or len(children) + seen + len(pending) > 10000:
            raise ValueError("Invalid sensor tree")
        pending.extend((child, depth + 1) for child in children)
    return result


def read_cpu_temperature() -> CpuTemperatureReading:
    try:
        readings = parse_lhm_temperatures(_read_lhm_json())
        if readings:
            return max(readings, key=lambda item: item.temperature_c)
    except (OSError, URLError, HTTPException, ValueError, RecursionError):
        pass
    rows = _run_powershell_json(_WMI_SCRIPT, timeout=4.0)
    if not isinstance(rows, list):
        return CpuTemperatureReading()
    readings = []
    for row in rows[:10000]:
        if not isinstance(row, dict):
            continue
        source = row.get("Source")
        if source not in {"root/LibreHardwareMonitor", "root/OpenHardwareMonitor"}:
            continue
        reading = _valid_sensor(row.get("Identifier"), row.get("Name"), row.get("Value"), source)
        if reading:
            readings.append(reading)
    return max(readings, key=lambda item: item.temperature_c) if readings else CpuTemperatureReading()
