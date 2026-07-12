from __future__ import annotations

import asyncio
import re
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from .config import ProbeTarget

ProbeState = Literal["unknown", "up", "down"]
PING_LATENCY_PATTERN = re.compile(r"time[=<]([0-9.]+)\s*ms")


class ProbeResult(BaseModel):
    name: str
    type: Literal["http", "tcp", "icmp"]
    target: str
    status: ProbeState
    latency_ms: float | None = None
    last_checked: datetime | None = None
    status_code: int | None = None
    error: str | None = None


class ProbeHistoryBucket(BaseModel):
    started_at: datetime
    ended_at: datetime
    status: ProbeState
    total_checks: int
    up_checks: int
    down_checks: int
    average_latency_ms: float | None = None


class ProbeHistorySummary(BaseModel):
    name: str
    target: str
    window_hours: int
    bucket_minutes: int
    total_checks: int
    up_checks: int
    down_checks: int
    uptime_percent: float | None
    outage_count: int
    first_checked_at: datetime | None = None
    last_checked_at: datetime | None = None
    last_down_at: datetime | None = None
    buckets: list[ProbeHistoryBucket] = Field(default_factory=list)


def unknown_result(target: ProbeTarget) -> ProbeResult:
    return ProbeResult(
        name=target.name,
        type=target.type,
        target=target.display_target,
        status="unknown",
    )


async def run_http_probe(target: ProbeTarget) -> ProbeResult:
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=target.timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.request(target.method, target.url or "")
        latency_ms = (time.perf_counter() - start) * 1000
        is_expected = (
            target.expected_status_min <= response.status_code <= target.expected_status_max
        )
        return ProbeResult(
            name=target.name,
            type="http",
            target=target.display_target,
            status="up" if is_expected else "down",
            latency_ms=round(latency_ms, 2),
            last_checked=datetime.now(UTC),
            status_code=response.status_code,
            error=None if is_expected else f"Unexpected status code {response.status_code}",
        )
    except httpx.HTTPError as exc:
        return _failed_result(target, start, str(exc) or exc.__class__.__name__)


async def run_tcp_probe(target: ProbeTarget) -> ProbeResult:
    start = time.perf_counter()
    writer: asyncio.StreamWriter | None = None
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(target.host, target.port),
            timeout=target.timeout,
        )
        latency_ms = (time.perf_counter() - start) * 1000
        return ProbeResult(
            name=target.name,
            type="tcp",
            target=target.display_target,
            status="up",
            latency_ms=round(latency_ms, 2),
            last_checked=datetime.now(UTC),
        )
    except (TimeoutError, OSError) as exc:
        return _failed_result(target, start, str(exc) or exc.__class__.__name__)
    finally:
        if writer is not None:
            writer.close()
            await writer.wait_closed()


async def run_icmp_probe(target: ProbeTarget) -> ProbeResult:
    start = time.perf_counter()
    timeout_seconds = max(1, int(round(target.timeout)))
    try:
        process = await asyncio.create_subprocess_exec(
            "ping",
            "-n",
            "-c",
            "1",
            "-W",
            str(timeout_seconds),
            target.host or "",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=target.timeout + 1,
        )
    except FileNotFoundError as exc:
        return _failed_result(target, start, str(exc) or "ping command not found")
    except (TimeoutError, OSError) as exc:
        return _failed_result(target, start, str(exc) or exc.__class__.__name__)

    latency_ms = _parse_ping_latency(stdout.decode(errors="replace"))
    if latency_ms is None:
        latency_ms = (time.perf_counter() - start) * 1000
    error_text = stderr.decode(errors="replace").strip()
    if process.returncode == 0:
        return ProbeResult(
            name=target.name,
            type="icmp",
            target=target.display_target,
            status="up",
            latency_ms=round(latency_ms, 2),
            last_checked=datetime.now(UTC),
        )
    return ProbeResult(
        name=target.name,
        type="icmp",
        target=target.display_target,
        status="down",
        latency_ms=round(latency_ms, 2),
        last_checked=datetime.now(UTC),
        error=error_text or f"ping exited with status {process.returncode}",
    )


async def run_probe(target: ProbeTarget) -> ProbeResult:
    if target.type == "http":
        return await run_http_probe(target)
    if target.type == "tcp":
        return await run_tcp_probe(target)
    return await run_icmp_probe(target)


async def run_probes(targets: list[ProbeTarget]) -> list[ProbeResult]:
    if not targets:
        return []
    return list(await asyncio.gather(*(run_probe(target) for target in targets)))


def merge_probe_results(
    targets: list[ProbeTarget],
    cached_results: dict[str, ProbeResult],
) -> list[ProbeResult]:
    return [cached_results.get(target.name, unknown_result(target)) for target in targets]


def save_probe_history(
    database_path: Path,
    results: list[ProbeResult],
    retention_hours: int,
) -> None:
    if not results:
        return

    database_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    rows = [
        (
            result.name,
            result.type,
            result.target,
            result.status,
            result.latency_ms,
            result.status_code,
            result.error,
            _normalize_datetime(result.last_checked or now).isoformat(),
        )
        for result in results
    ]
    cutoff = (now - timedelta(hours=retention_hours)).isoformat()
    with sqlite3.connect(database_path) as connection:
        _ensure_probe_history_schema(connection)
        connection.executemany(
            """
            INSERT INTO probe_samples (
                name,
                type,
                target,
                status,
                latency_ms,
                status_code,
                error,
                checked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        connection.execute("DELETE FROM probe_samples WHERE checked_at < ?", (cutoff,))


def get_probe_history_summaries(
    database_path: Path,
    targets: list[ProbeTarget],
    window_hours: int,
    bucket_minutes: int = 5,
) -> list[ProbeHistorySummary]:
    if not targets:
        return []
    window_end = _ceil_to_bucket(datetime.now(UTC), bucket_minutes)
    window_start = window_end - timedelta(hours=window_hours)
    if not database_path.exists():
        return [
            _empty_history_summary(target, window_hours, bucket_minutes, window_start, window_end)
            for target in targets
        ]

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_probe_history_schema(connection)
        return [
            _load_probe_history_summary(
                connection,
                target,
                window_hours,
                bucket_minutes,
                window_start,
                window_end,
            )
            for target in targets
        ]


def _failed_result(target: ProbeTarget, start: float, error: str) -> ProbeResult:
    latency_ms = (time.perf_counter() - start) * 1000
    return ProbeResult(
        name=target.name,
        type=target.type,
        target=target.display_target,
        status="down",
        latency_ms=round(latency_ms, 2),
        last_checked=datetime.now(UTC),
        error=error,
    )


def _parse_ping_latency(output: str) -> float | None:
    match = PING_LATENCY_PATTERN.search(output)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _ensure_probe_history_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS probe_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            target TEXT NOT NULL,
            status TEXT NOT NULL,
            latency_ms REAL,
            status_code INTEGER,
            error TEXT,
            checked_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_probe_samples_name_checked_at
        ON probe_samples (name, checked_at)
        """
    )


def _load_probe_history_summary(
    connection: sqlite3.Connection,
    target: ProbeTarget,
    window_hours: int,
    bucket_minutes: int,
    window_start: datetime,
    window_end: datetime,
) -> ProbeHistorySummary:
    rows = connection.execute(
        """
        SELECT status, latency_ms, checked_at
        FROM probe_samples
        WHERE name = ? AND checked_at >= ? AND checked_at < ?
        ORDER BY checked_at ASC
        """,
        (target.name, window_start.isoformat(), window_end.isoformat()),
    ).fetchall()
    if not rows:
        return _empty_history_summary(
            target,
            window_hours,
            bucket_minutes,
            window_start,
            window_end,
        )

    up_checks = 0
    down_checks = 0
    outage_count = 0
    previous_status: str | None = None
    checked_times: list[datetime] = []
    last_down_at: datetime | None = None
    buckets = _build_probe_history_buckets(rows, window_start, window_end, bucket_minutes)

    for row in rows:
        status = str(row["status"])
        checked_at = _parse_stored_datetime(str(row["checked_at"]))
        checked_times.append(checked_at)
        if status == "up":
            up_checks += 1
        elif status == "down":
            down_checks += 1
            last_down_at = checked_at
            if previous_status != "down":
                outage_count += 1
        previous_status = status

    total_checks = len(rows)
    uptime_percent = round((up_checks / total_checks) * 100, 2) if total_checks else None
    return ProbeHistorySummary(
        name=target.name,
        target=target.display_target,
        window_hours=window_hours,
        bucket_minutes=bucket_minutes,
        total_checks=total_checks,
        up_checks=up_checks,
        down_checks=down_checks,
        uptime_percent=uptime_percent,
        outage_count=outage_count,
        first_checked_at=checked_times[0],
        last_checked_at=checked_times[-1],
        last_down_at=last_down_at,
        buckets=buckets,
    )


def _empty_history_summary(
    target: ProbeTarget,
    window_hours: int,
    bucket_minutes: int,
    window_start: datetime,
    window_end: datetime,
) -> ProbeHistorySummary:
    return ProbeHistorySummary(
        name=target.name,
        target=target.display_target,
        window_hours=window_hours,
        bucket_minutes=bucket_minutes,
        total_checks=0,
        up_checks=0,
        down_checks=0,
        uptime_percent=None,
        outage_count=0,
        buckets=_build_probe_history_buckets([], window_start, window_end, bucket_minutes),
    )


def _build_probe_history_buckets(
    rows: list[sqlite3.Row],
    window_start: datetime,
    window_end: datetime,
    bucket_minutes: int,
) -> list[ProbeHistoryBucket]:
    bucket_seconds = bucket_minutes * 60
    bucket_count = max(1, int((window_end - window_start).total_seconds() // bucket_seconds))
    bucket_data = [
        {
            "started_at": window_start + timedelta(seconds=index * bucket_seconds),
            "total_checks": 0,
            "up_checks": 0,
            "down_checks": 0,
            "latencies": [],
        }
        for index in range(bucket_count)
    ]

    for row in rows:
        checked_at = _parse_stored_datetime(str(row["checked_at"]))
        if checked_at < window_start or checked_at >= window_end:
            continue
        bucket_index = min(
            bucket_count - 1,
            int((checked_at - window_start).total_seconds() // bucket_seconds),
        )
        bucket = bucket_data[bucket_index]
        bucket["total_checks"] += 1
        status = str(row["status"])
        if status == "up":
            bucket["up_checks"] += 1
        elif status == "down":
            bucket["down_checks"] += 1
        latency_ms = row["latency_ms"]
        if isinstance(latency_ms, int | float):
            bucket["latencies"].append(float(latency_ms))

    buckets: list[ProbeHistoryBucket] = []
    for bucket in bucket_data:
        up_checks = int(bucket["up_checks"])
        down_checks = int(bucket["down_checks"])
        total_checks = int(bucket["total_checks"])
        latencies = list(bucket["latencies"])
        status: ProbeState
        if down_checks > 0:
            status = "down"
        elif up_checks > 0:
            status = "up"
        else:
            status = "unknown"
        started_at = bucket["started_at"]
        buckets.append(
            ProbeHistoryBucket(
                started_at=started_at,
                ended_at=started_at + timedelta(seconds=bucket_seconds),
                status=status,
                total_checks=total_checks,
                up_checks=up_checks,
                down_checks=down_checks,
                average_latency_ms=round(sum(latencies) / len(latencies), 2)
                if latencies
                else None,
            )
        )
    return buckets


def _ceil_to_bucket(value: datetime, bucket_minutes: int) -> datetime:
    normalized = _normalize_datetime(value)
    bucket_seconds = bucket_minutes * 60
    timestamp = normalized.timestamp()
    bucket_start = int(timestamp // bucket_seconds) * bucket_seconds
    if timestamp > bucket_start:
        bucket_start += bucket_seconds
    return datetime.fromtimestamp(bucket_start, UTC)


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _parse_stored_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return _normalize_datetime(parsed)
