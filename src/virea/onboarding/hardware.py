"""Portable device facts. Unavailable measurements remain null, never zero."""

from __future__ import annotations

import csv
import io
import json
import os
import platform
import shutil
import subprocess
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import psutil


def command(argv):
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
            creationflags=0x08000000 if os.name == "nt" else 0,
        )
        return result.stdout if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def number(value, multiplier=1):
    try:
        return int(float(value.strip()) * multiplier)
    except (ValueError, AttributeError):
        return None


@lru_cache(maxsize=1)
def cpu_name():
    if os.name == "nt":
        import winreg

        try:
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    if platform.system() == "Darwin":
        name = command(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
        if name:
            return name
    return platform.processor() or platform.machine()


def conda_environments():
    executable = (
        shutil.which("conda") or shutil.which("micromamba") or os.getenv("CONDA_EXE")
    )
    if not executable:
        for prefix in ("miniforge3", "miniconda3", "anaconda3", "mambaforge"):
            candidate = (
                Path.home()
                / prefix
                / ("Scripts/conda.exe" if os.name == "nt" else "bin/conda")
            )
            if candidate.is_file():
                executable = str(candidate)
                break
    try:
        data = (
            json.loads(command([executable, "env", "list", "--json"]))
            if executable
            else {}
        )
    except ValueError:
        data = {}
    return dict(
        executable=executable,
        environments=[p for p in data.get("envs", []) if isinstance(p, str)],
    )


def gpu_facts():
    smi = shutil.which("nvidia-smi")
    if smi:
        output = command(
            [
                smi,
                "--query-gpu=name,memory.total,memory.used,memory.free,driver_version,utilization.gpu",
                "--format=csv,noheader,nounits",
            ]
        )
        rows = []
        for row in csv.reader(io.StringIO(output)):
            if len(row) != 6:
                continue
            name, total, used, free, driver, utilization = row
            rows.append(
                dict(
                    name=name.strip(),
                    vendor="NVIDIA",
                    memory_kind="dedicated",
                    total_bytes=number(total, 1048576),
                    used_bytes=number(used, 1048576),
                    available_bytes=number(free, 1048576),
                    driver=driver.strip(),
                    utilization_percent=number(utilization),
                    source="nvidia-smi",
                )
            )
        if rows:
            return rows
    if platform.system() == "Darwin":
        try:
            items = json.loads(
                command(["system_profiler", "SPDisplaysDataType", "-json"])
            )
            return [
                dict(
                    name=g.get("sppci_model", "Apple GPU"),
                    vendor=g.get("spdisplays_vendor", "Apple"),
                    memory_kind="unified"
                    if platform.machine() == "arm64"
                    else "unknown",
                    total_bytes=None,
                    available_bytes=None,
                    source="system_profiler",
                )
                for g in items.get("SPDisplaysDataType", [])
            ]
        except ValueError:
            return []
    if os.name == "nt":
        try:
            values = json.loads(
                command(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-NonInteractive",
                        "-Command",
                        "@(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion) | ConvertTo-Json -Compress",
                    ]
                )
            )
            return [
                dict(
                    name=g["Name"],
                    driver=g["DriverVersion"],
                    memory_kind="unknown",
                    total_bytes=None,
                    available_bytes=None,
                    source="Win32_VideoController",
                )
                for g in (values if isinstance(values, list) else [values])
                if g
            ]
        except (ValueError, TypeError, KeyError):
            return []
    # Linux DRM exposes vendor/device even without a vendor-specific CLI.
    return [
        dict(
            name=p.parent.name,
            vendor=p.read_text().strip(),
            memory_kind="unknown",
            total_bytes=None,
            available_bytes=None,
            source="sysfs",
        )
        for p in Path("/sys/class/drm").glob("card[0-9]/device/vendor")
    ]


def inspect_hardware(root):
    memory, swap = psutil.virtual_memory(), psutil.swap_memory()
    disks, seen = [], set()
    for part in psutil.disk_partitions(all=False):
        if part.mountpoint in seen or {"cdrom", "remote"}.intersection(
            part.opts.split(",")
        ):
            continue
        seen.add(part.mountpoint)
        try:
            usage = shutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        disks.append(
            dict(
                mount=part.mountpoint,
                filesystem=part.fstype,
                total_bytes=usage.total,
                used_bytes=usage.used,
                available_bytes=usage.free,
            )
        )
    usage = shutil.disk_usage(root)
    return dict(
        measured_at=datetime.now(timezone.utc).isoformat(),
        system=dict(
            name=platform.system(),
            release=platform.release(),
            version=platform.version(),
            architecture=platform.machine(),
            python=platform.python_version(),
        ),
        cpu=dict(
            name=cpu_name(),
            physical_cores=psutil.cpu_count(logical=False),
            logical_cores=psutil.cpu_count(),
            utilization_percent=psutil.cpu_percent(interval=0.1),
        ),
        memory=dict(
            total_bytes=memory.total,
            available_bytes=memory.available,
            used_bytes=memory.total - memory.available,
            utilization_percent=memory.percent,
            swap_total_bytes=swap.total,
            swap_available_bytes=swap.free,
        ),
        storage=dict(
            path=str(root),
            total_bytes=usage.total,
            available_bytes=usage.free,
            used_bytes=usage.used,
        ),
        disks=disks,
        gpus=gpu_facts(),
        tools={
            name: dict(available=bool(shutil.which(name)), path=shutil.which(name))
            for name in (
                "uv",
                "git",
                "node",
                "pnpm",
                "ollama",
                "ffmpeg",
                "nvidia-smi",
                "wsl",
            )
        },
    )
