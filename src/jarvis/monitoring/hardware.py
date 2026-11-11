"""One observed hardware snapshot shared by command tools and thermal checks."""
from dataclasses import asdict
from datetime import datetime, timezone

from . import checks
from .thermal import read_cpu_temperature
from ..models import CommandResult


def hardware_status() -> CommandResult:
    cpu = checks.read_cpu()
    memory = checks.read_memory()
    gpu = checks.read_gpu()
    thermal = read_cpu_temperature()
    def value(number, suffix):
        return f"{number:.1f}{suffix}" if number is not None else "unavailable"

    lines = [f"CPU usage: {value(cpu.percent, '%')}",
             f"CPU temperature (hottest exposed sensor): {value(thermal.temperature_c, ' C')}",
             f"GPU: {gpu.name or 'not detected'} (first NVIDIA GPU)",
             f"GPU usage: {value(gpu.utilization_percent, '%')}",
             f"GPU temperature: {value(gpu.temperature_c, ' C')}",
             f"RAM usage: {value(memory.percent_used, '%')}"]
    if thermal.available:
        lines.append(f"CPU sensor: {thermal.sensor}; source: {thermal.source}")
    else:
        lines.append(thermal.reason)
    metadata = {"observed_at": datetime.now(timezone.utc).isoformat(), "cpu": asdict(cpu),
                "cpu_temperature": asdict(thermal), "gpu": asdict(gpu), "memory": asdict(memory),
                "partial": not (cpu.available and thermal.available and gpu.utilization_percent is not None
                                and gpu.temperature_c is not None and memory.available)}
    return CommandResult(any((cpu.available, thermal.available, gpu.available, memory.available)),
                         "\n".join(lines), metadata=metadata)
