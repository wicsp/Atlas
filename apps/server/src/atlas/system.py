from __future__ import annotations

import os
import pwd
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import psutil
from pydantic import BaseModel

DEFAULT_DISK_PATHS = ("/home", "/data")
HOME_PATH = Path("/home")


class CpuSummary(BaseModel):
    percent: float
    count: int | None
    load_average: tuple[float, float, float] | None


class MemorySummary(BaseModel):
    total_bytes: int
    used_bytes: int
    available_bytes: int
    percent: float


class DiskSummary(BaseModel):
    path: str
    total_bytes: int
    used_bytes: int
    free_bytes: int
    percent: float


class HomeUsageSummary(BaseModel):
    user: str
    path: str
    used_bytes: int
    percent_of_disk: float | None


class GpuProcessSummary(BaseModel):
    pid: int
    user: str
    process_type: str
    process_name: str
    command: str
    memory_used_bytes: int | None
    memory_percent: float | None
    sm_utilization_percent: float | None


class GpuUserUsage(BaseModel):
    user: str
    process_count: int
    memory_used_bytes: int
    memory_percent: float
    sm_utilization_percent: float | None


class GpuSummary(BaseModel):
    index: int
    name: str
    utilization_percent: float | None
    memory_used_bytes: int | None
    memory_total_bytes: int | None
    memory_percent: float | None
    temperature_c: int | None
    power_draw_watts: float | None
    power_limit_watts: float | None
    users: list[GpuUserUsage]
    processes: list[GpuProcessSummary]


class SystemGlanceSummary(BaseModel):
    timestamp: datetime
    uptime_seconds: int
    cpu: CpuSummary
    memory: MemorySummary
    disks: list[DiskSummary]


class SystemSummary(SystemGlanceSummary):
    home_usage: list[HomeUsageSummary]
    gpus: list[GpuSummary]


def get_system_glance_summary() -> SystemGlanceSummary:
    memory = psutil.virtual_memory()
    load_average = os.getloadavg() if hasattr(os, "getloadavg") else None
    now = datetime.now(UTC)
    return SystemGlanceSummary(
        timestamp=now,
        uptime_seconds=max(0, int(now.timestamp() - psutil.boot_time())),
        cpu=CpuSummary(
            percent=psutil.cpu_percent(interval=None),
            count=psutil.cpu_count(),
            load_average=load_average,
        ),
        memory=MemorySummary(
            total_bytes=memory.total,
            used_bytes=memory.used,
            available_bytes=memory.available,
            percent=memory.percent,
        ),
        disks=get_disk_summaries(),
    )


def get_system_summary() -> SystemSummary:
    memory = psutil.virtual_memory()
    disks = get_disk_summaries()
    load_average = os.getloadavg() if hasattr(os, "getloadavg") else None
    now = datetime.now(UTC)
    return SystemSummary(
        timestamp=now,
        uptime_seconds=max(0, int(now.timestamp() - psutil.boot_time())),
        cpu=CpuSummary(
            percent=psutil.cpu_percent(interval=None),
            count=psutil.cpu_count(),
            load_average=load_average,
        ),
        memory=MemorySummary(
            total_bytes=memory.total,
            used_bytes=memory.used,
            available_bytes=memory.available,
            percent=memory.percent,
        ),
        disks=disks,
        home_usage=get_home_usage(),
        gpus=get_gpu_summaries(),
    )


def get_disk_summaries(paths: tuple[str, ...] = DEFAULT_DISK_PATHS) -> list[DiskSummary]:
    disks = []
    for path in paths:
        if path != "/" and not Path(path).exists():
            continue
        disks.append(_get_disk_summary(path))
    return disks


def get_home_usage(home_path: Path = HOME_PATH, timeout: int = 10) -> list[HomeUsageSummary]:
    if not home_path.exists():
        return []

    home_dirs = _get_home_directories(home_path)
    if not home_dirs:
        return []

    try:
        home_total_bytes = psutil.disk_usage(str(home_path)).total
        completed = subprocess.run(
            ["du", "-sB1", "--", *(str(path) for path in home_dirs)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError, TimeoutError):
        return []

    usage = []
    for line in completed.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        used_bytes = _parse_int(parts[0])
        if used_bytes is None:
            continue
        usage.append(
            HomeUsageSummary(
                user=Path(parts[1]).name,
                path=parts[1],
                used_bytes=used_bytes,
                percent_of_disk=_percentage(used_bytes, home_total_bytes),
            )
        )

    usage.sort(key=lambda item: item.used_bytes, reverse=True)
    return usage


def _get_home_directories(home_path: Path) -> list[Path]:
    user_dirs = {
        Path(user.pw_dir)
        for user in pwd.getpwall()
        if Path(user.pw_dir).parent == home_path and Path(user.pw_dir).is_dir()
    }
    if user_dirs:
        return sorted(user_dirs)

    return sorted(
        path for path in home_path.iterdir() if path.is_dir() and path.name != "lost+found"
    )


def _get_disk_summary(path: str) -> DiskSummary:
    disk = psutil.disk_usage(path)
    return DiskSummary(
        path=path,
        total_bytes=disk.total,
        used_bytes=disk.used,
        free_bytes=disk.free,
        percent=disk.percent,
    )


def get_gpu_summaries() -> list[GpuSummary]:
    gpu_rows = _run_nvidia_smi_query(
        [
            "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw,power.limit",
            "--format=csv,noheader,nounits",
        ]
    )
    if gpu_rows is None:
        return []

    process_map = get_gpu_processes()
    gpus: list[GpuSummary] = []
    for line in gpu_rows.splitlines():
        columns = [column.strip() for column in line.split(",")]
        if len(columns) != 8:
            continue

        index = _parse_int(columns[0])
        gpu_index = index if index is not None else len(gpus)
        memory_used_mib = _parse_float(columns[3])
        memory_total_mib = _parse_float(columns[4])
        memory_used_bytes = _mib_to_bytes(memory_used_mib)
        memory_total_bytes = _mib_to_bytes(memory_total_mib)
        memory_percent = _percentage(memory_used_bytes, memory_total_bytes)
        processes = process_map.get(gpu_index, [])
        for process in processes:
            process.memory_percent = _percentage(process.memory_used_bytes, memory_total_bytes)

        gpus.append(
            GpuSummary(
                index=gpu_index,
                name=columns[1] or "Unknown GPU",
                utilization_percent=_parse_float(columns[2]),
                memory_used_bytes=memory_used_bytes,
                memory_total_bytes=memory_total_bytes,
                memory_percent=memory_percent,
                temperature_c=_parse_int(columns[5]),
                power_draw_watts=_parse_float(columns[6]),
                power_limit_watts=_parse_float(columns[7]),
                users=_aggregate_gpu_users(processes, memory_total_bytes),
                processes=processes,
            )
        )
    return gpus


def get_gpu_processes() -> dict[int, list[GpuProcessSummary]]:
    output = _run_nvidia_smi_query(["pmon", "-c", "1", "-s", "um"], timeout=3)
    if output is None:
        return {}

    processes_by_gpu: dict[int, list[GpuProcessSummary]] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        parts = stripped.split()
        if len(parts) < 12:
            continue

        gpu_index = _parse_int(parts[0])
        pid = _parse_int(parts[1])
        if gpu_index is None or pid is None:
            continue

        fallback_name = parts[11]
        identity = _lookup_process_identity(pid, fallback_name)
        memory_used_bytes = _mib_to_bytes(_parse_float(parts[9]))
        memory_percent = None
        sm_utilization_percent = _parse_float(parts[3])

        processes_by_gpu.setdefault(gpu_index, []).append(
            GpuProcessSummary(
                pid=pid,
                user=identity["user"],
                process_type=parts[2],
                process_name=identity["process_name"],
                command=identity["command"],
                memory_used_bytes=memory_used_bytes,
                memory_percent=memory_percent,
                sm_utilization_percent=sm_utilization_percent,
            )
        )

    for processes in processes_by_gpu.values():
        processes.sort(
            key=lambda process: (
                process.memory_used_bytes or 0,
                process.sm_utilization_percent or 0,
            ),
            reverse=True,
        )
    return processes_by_gpu


def _aggregate_gpu_users(
    processes: list[GpuProcessSummary],
    memory_total_bytes: int | None,
) -> list[GpuUserUsage]:
    grouped: dict[str, dict[str, float | int | bool]] = {}
    for process in processes:
        usage = grouped.setdefault(
            process.user,
            {
                "process_count": 0,
                "memory_used_bytes": 0,
                "sm_utilization_percent": 0.0,
                "has_sm_utilization": False,
            },
        )
        usage["process_count"] = int(usage["process_count"]) + 1
        usage["memory_used_bytes"] = int(usage["memory_used_bytes"]) + (
            process.memory_used_bytes or 0
        )
        if process.sm_utilization_percent is not None:
            usage["sm_utilization_percent"] = float(usage["sm_utilization_percent"]) + (
                process.sm_utilization_percent
            )
            usage["has_sm_utilization"] = True

    users = [
        GpuUserUsage(
            user=user,
            process_count=int(usage["process_count"]),
            memory_used_bytes=int(usage["memory_used_bytes"]),
            memory_percent=_percentage(int(usage["memory_used_bytes"]), memory_total_bytes) or 0,
            sm_utilization_percent=round(float(usage["sm_utilization_percent"]), 1)
            if usage["has_sm_utilization"]
            else None,
        )
        for user, usage in grouped.items()
    ]
    users.sort(
        key=lambda usage: (usage.memory_used_bytes, usage.sm_utilization_percent or 0),
        reverse=True,
    )
    return users


def _lookup_process_identity(pid: int, fallback_name: str) -> dict[str, str]:
    try:
        process = psutil.Process(pid)
        process_name = process.name() or fallback_name
        command_parts = process.cmdline()
        command = " ".join(command_parts) if command_parts else process_name
        user = process.username() or "unknown"
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
        process_name = fallback_name
        command = fallback_name
        user = "unknown"

    return {
        "user": user.rsplit("\\", 1)[-1],
        "process_name": process_name,
        "command": command,
    }


def _run_nvidia_smi_query(args: list[str], timeout: int = 2) -> str | None:
    try:
        completed = subprocess.run(
            ["nvidia-smi", *args],
            capture_output=True,
            check=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.SubprocessError, TimeoutError):
        return None
    return completed.stdout


def _parse_float(value: str) -> float | None:
    if value in {"", "-", "N/A", "[N/A]"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str) -> int | None:
    parsed = _parse_float(value)
    if parsed is None:
        return None
    return int(parsed)


def _mib_to_bytes(value: float | None) -> int | None:
    if value is None:
        return None
    return int(value * 1024 * 1024)


def _percentage(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return round((numerator / denominator) * 100, 1)
