import asyncio
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from atlas.config import ProbeTarget
from atlas.probes import (
    ProbeResult,
    get_probe_history_summaries,
    run_http_probe,
    run_icmp_probe,
    run_tcp_probe,
    save_probe_history,
)


@pytest.mark.asyncio
async def test_http_probe_success(monkeypatch) -> None:
    async def fake_request(self, method: str, url: str):
        return httpx.Response(204)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    target = ProbeTarget(
        name="api",
        type="http",
        url="https://example.test/health",
        expected_status_min=200,
        expected_status_max=299,
    )

    result = await run_http_probe(target)

    assert result.status == "up"
    assert result.status_code == 204
    assert result.error is None


@pytest.mark.asyncio
async def test_http_probe_unexpected_status(monkeypatch) -> None:
    async def fake_request(self, method: str, url: str):
        return httpx.Response(500)

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    target = ProbeTarget(name="api", type="http", url="https://example.test/health")

    result = await run_http_probe(target)

    assert result.status == "down"
    assert result.status_code == 500
    assert result.error == "Unexpected status code 500"


@pytest.mark.asyncio
async def test_http_probe_timeout(monkeypatch) -> None:
    async def fake_request(self, method: str, url: str):
        raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    target = ProbeTarget(name="api", type="http", url="https://example.test/health")

    result = await run_http_probe(target)

    assert result.status == "down"
    assert result.error == "timed out"


@pytest.mark.asyncio
async def test_tcp_probe_success() -> None:
    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        target = ProbeTarget(name="tcp", type="tcp", host="127.0.0.1", port=port)

        result = await run_tcp_probe(target)
    finally:
        server.close()
        await server.wait_closed()

    assert result.status == "up"
    assert result.error is None


@pytest.mark.asyncio
async def test_tcp_probe_connection_failure() -> None:
    server = await asyncio.start_server(
        lambda reader, writer: None,
        "127.0.0.1",
        0,
    )
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()

    target = ProbeTarget(name="tcp", type="tcp", host="127.0.0.1", port=port, timeout=0.2)

    result = await run_tcp_probe(target)

    assert result.status == "down"
    assert result.error


@pytest.mark.asyncio
async def test_icmp_probe_success(monkeypatch) -> None:
    class FakeProcess:
        returncode = 0

        async def communicate(self):
            return (
                b"64 bytes from 154.21.80.210: icmp_seq=1 ttl=53 time=18.4 ms\n",
                b"",
            )

    async def fake_create_subprocess_exec(*args, **kwargs):
        assert args == (
            "ping",
            "-n",
            "-c",
            "1",
            "-W",
            "2",
            "154.21.80.210",
        )
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    target = ProbeTarget(
        name="nexus",
        type="icmp",
        host="154.21.80.210",
        timeout=2.0,
    )

    result = await run_icmp_probe(target)

    assert result.status == "up"
    assert result.latency_ms == 18.4
    assert result.error is None


@pytest.mark.asyncio
async def test_icmp_probe_failure(monkeypatch) -> None:
    class FakeProcess:
        returncode = 1

        async def communicate(self):
            return (b"", b"Destination Host Unreachable")

    async def fake_create_subprocess_exec(*args, **kwargs):
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    target = ProbeTarget(name="mio", type="icmp", host="8.135.45.26", timeout=2.0)

    result = await run_icmp_probe(target)

    assert result.status == "down"
    assert result.error == "Destination Host Unreachable"


def test_probe_history_summaries_count_uptime_and_outages(tmp_path) -> None:
    database_path = tmp_path / "probe-history.sqlite3"
    now = datetime.now(UTC)
    target = ProbeTarget(name="nexus", type="icmp", host="154.21.80.210")
    samples = [
        ProbeResult(
            name="nexus",
            type="icmp",
            target="154.21.80.210",
            status="up",
            last_checked=now - timedelta(minutes=5),
        ),
        ProbeResult(
            name="nexus",
            type="icmp",
            target="154.21.80.210",
            status="down",
            last_checked=now - timedelta(minutes=4),
        ),
        ProbeResult(
            name="nexus",
            type="icmp",
            target="154.21.80.210",
            status="down",
            last_checked=now - timedelta(minutes=3),
        ),
        ProbeResult(
            name="nexus",
            type="icmp",
            target="154.21.80.210",
            status="up",
            last_checked=now - timedelta(minutes=2),
        ),
    ]

    save_probe_history(database_path, samples, retention_hours=24)
    summary = get_probe_history_summaries(database_path, [target], window_hours=24)[0]

    assert summary.name == "nexus"
    assert summary.total_checks == 4
    assert summary.up_checks == 2
    assert summary.down_checks == 2
    assert summary.uptime_percent == 50.0
    assert summary.outage_count == 1
    assert summary.last_down_at == samples[2].last_checked
    assert summary.bucket_minutes == 5
    assert len(summary.buckets) == 288
    assert sum(bucket.down_checks for bucket in summary.buckets) == 2
    assert any(bucket.status == "down" for bucket in summary.buckets)


def test_probe_history_summaries_return_empty_for_missing_database(tmp_path) -> None:
    target = ProbeTarget(name="mio", type="icmp", host="8.135.45.26")

    summary = get_probe_history_summaries(
        tmp_path / "missing.sqlite3",
        [target],
        window_hours=24,
    )[0]

    assert summary.total_checks == 0
    assert summary.uptime_percent is None
    assert summary.outage_count == 0
    assert len(summary.buckets) == 288
    assert all(bucket.status == "unknown" for bucket in summary.buckets)
