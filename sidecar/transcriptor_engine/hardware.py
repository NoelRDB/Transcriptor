from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import time
from typing import Any

import psutil


def _cpu_name() -> str:
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                return str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).strip()
        except OSError:
            pass
    return platform.processor().strip() or "Procesador del sistema"


def _nvidia_snapshot() -> dict[str, Any] | None:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return None
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        completed = subprocess.run(
            [
                executable,
                "--query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            check=True,
            encoding="utf-8",
            errors="replace",
            startupinfo=startupinfo,
            timeout=3,
        )
        values = [value.strip() for value in completed.stdout.splitlines()[0].split(",")]
        return {
            "name": values[0],
            "totalVramMiB": round(float(values[1])),
            "usedVramMiB": round(float(values[2])),
            "utilizationPercent": round(float(values[3]), 1),
            "driverVersion": values[4],
        }
    except (IndexError, OSError, subprocess.SubprocessError, ValueError):
        return None


def get_hardware_info(cuda_available: bool = False) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    logical = max(1, psutil.cpu_count(logical=True) or os.cpu_count() or 1)
    physical = max(1, psutil.cpu_count(logical=False) or logical)
    gpu = _nvidia_snapshot()
    return {
        "cpu": {
            "name": _cpu_name(),
            "physicalCores": physical,
            "logicalCores": logical,
            "usagePercent": round(psutil.cpu_percent(interval=0.1), 1),
        },
        "memory": {
            "totalMiB": round(memory.total / (1024 * 1024)),
            "availableMiB": round(memory.available / (1024 * 1024)),
            "usagePercent": round(memory.percent, 1),
        },
        "gpu": gpu,
        "cudaAvailable": bool(cuda_available and gpu),
        "recommendedProfile": "maximum" if cuda_available and logical >= 8 else "performance",
    }


class RuntimeMonitor:
    def __init__(self) -> None:
        self.process = psutil.Process()
        self.process.cpu_percent()
        self._last_gpu_at = 0.0
        self._gpu: dict[str, Any] | None = None

    def snapshot(self) -> dict[str, Any]:
        memory = psutil.virtual_memory()
        now = time.monotonic()
        if now - self._last_gpu_at >= 1:
            self._gpu = _nvidia_snapshot()
            self._last_gpu_at = now
        result = {
            "ramMiB": round(self.process.memory_info().rss / (1024 * 1024), 1),
            "cpuUsagePercent": round(self.process.cpu_percent() / max(1, psutil.cpu_count() or 1), 1),
            "systemRamUsedMiB": round(memory.used / (1024 * 1024)),
            "systemRamTotalMiB": round(memory.total / (1024 * 1024)),
        }
        if self._gpu:
            result.update(
                {
                    "gpuUsagePercent": self._gpu["utilizationPercent"],
                    "gpuVramUsedMiB": self._gpu["usedVramMiB"],
                    "gpuVramTotalMiB": self._gpu["totalVramMiB"],
                }
            )
        return result
