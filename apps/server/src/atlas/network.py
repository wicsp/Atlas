from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel

ConnectivityState = Literal["up", "down"]


@dataclass(frozen=True)
class ConnectivityTarget:
    label: str
    url: str
    timeout: float = 3.0
    expected_status_min: int = 200
    expected_status_max: int = 399


class ConnectivityResult(BaseModel):
    label: str
    target: str
    status: ConnectivityState
    latency_ms: float | None = None
    last_checked: datetime | None = None
    status_code: int | None = None
    error: str | None = None


class NetworkConnectivity(BaseModel):
    domestic: ConnectivityResult
    international: ConnectivityResult


DOMESTIC_TARGET = ConnectivityTarget(
    label="Domestic",
    url="https://www.baidu.com/",
)
INTERNATIONAL_TARGET = ConnectivityTarget(
    label="International",
    url="https://www.google.com/generate_204",
    expected_status_min=204,
    expected_status_max=204,
)


async def check_connectivity(target: ConnectivityTarget) -> ConnectivityResult:
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=target.timeout,
            follow_redirects=False,
            trust_env=True,
        ) as client:
            response = await client.request("GET", target.url)
        latency_ms = (time.perf_counter() - start) * 1000
        is_expected = (
            target.expected_status_min <= response.status_code <= target.expected_status_max
        )
        return ConnectivityResult(
            label=target.label,
            target=target.url,
            status="up" if is_expected else "down",
            latency_ms=round(latency_ms, 2),
            last_checked=datetime.now(UTC),
            status_code=response.status_code,
            error=None if is_expected else f"Unexpected status code {response.status_code}",
        )
    except httpx.HTTPError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return ConnectivityResult(
            label=target.label,
            target=target.url,
            status="down",
            latency_ms=round(latency_ms, 2),
            last_checked=datetime.now(UTC),
            error=str(exc) or exc.__class__.__name__,
        )


async def get_network_connectivity() -> NetworkConnectivity:
    domestic, international = await asyncio.gather(
        check_connectivity(DOMESTIC_TARGET),
        check_connectivity(INTERNATIONAL_TARGET),
    )
    return NetworkConnectivity(domestic=domestic, international=international)
