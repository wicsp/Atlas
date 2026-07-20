from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel

from .config import Settings
from .network import NetworkConnectivity, get_network_connectivity
from .probes import (
    ProbeHistorySummary,
    ProbeResult,
    get_probe_history_summaries,
    merge_probe_results,
    run_probes,
    save_probe_history,
)
from .sub2api import (
    Sub2ApiAccountsResponse,
    Sub2ApiSnapshotCollector,
    get_sub2api_accounts,
)
from .system import GpuSummary, SystemGlanceSummary, get_gpu_summaries, get_system_glance_summary

SYSTEM_REFRESH_SECONDS = 30.0
GPU_REFRESH_SECONDS = 5.0
NETWORK_REFRESH_SECONDS = 30.0
PROBE_REFRESH_SECONDS = 30.0

T = TypeVar("T")


class SnapshotMeta(BaseModel):
    checked_at: datetime | None = None
    age_seconds: float | None = None
    stale: bool
    refreshing: bool = False
    error: str | None = None


class DashboardSnapshot(BaseModel):
    checked_at: datetime
    system: SystemGlanceSummary | None
    system_meta: SnapshotMeta
    gpus: list[GpuSummary]
    gpu_meta: SnapshotMeta
    network: NetworkConnectivity | None
    network_meta: SnapshotMeta
    probes: list[ProbeResult]
    probes_meta: SnapshotMeta
    probe_history: list[ProbeHistorySummary]
    sub2api: Sub2ApiAccountsResponse | None


@dataclass
class _SnapshotSlot(Generic[T]):
    value: T | None = None
    checked_at: datetime | None = None
    refreshing: bool = False
    error: str | None = None

    def meta(self, stale_after_seconds: float) -> SnapshotMeta:
        age_seconds = self.age_seconds()
        return SnapshotMeta(
            checked_at=self.checked_at,
            age_seconds=age_seconds,
            stale=self.value is None
            or self.error is not None
            or age_seconds is None
            or age_seconds > stale_after_seconds,
            refreshing=self.refreshing,
            error=self.error,
        )

    def age_seconds(self) -> float | None:
        if self.checked_at is None:
            return None
        return max(0.0, (datetime.now(UTC) - self.checked_at).total_seconds())


class DashboardSnapshotCollector:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._system: _SnapshotSlot[SystemGlanceSummary] = _SnapshotSlot()
        self._gpus: _SnapshotSlot[list[GpuSummary]] = _SnapshotSlot()
        self._network: _SnapshotSlot[NetworkConnectivity] = _SnapshotSlot()
        self._probes: _SnapshotSlot[list[ProbeResult]] = _SnapshotSlot(
            value=merge_probe_results(settings.probes, {}),
        )
        self._tasks: list[asyncio.Task[None]] = []
        self._locks = {
            "system": asyncio.Lock(),
            "gpus": asyncio.Lock(),
            "network": asyncio.Lock(),
            "probes": asyncio.Lock(),
        }

    @property
    def running(self) -> bool:
        return any(not task.done() for task in self._tasks)

    def start(self) -> None:
        if self.running:
            return
        self._tasks = [
            asyncio.create_task(
                self._run_loop(self.refresh_system, SYSTEM_REFRESH_SECONDS),
                name="dashboard-system-snapshot",
            ),
            asyncio.create_task(
                self._run_loop(self.refresh_gpus, GPU_REFRESH_SECONDS),
                name="dashboard-gpu-snapshot",
            ),
            asyncio.create_task(
                self._run_loop(self.refresh_network, NETWORK_REFRESH_SECONDS),
                name="dashboard-network-snapshot",
            ),
            asyncio.create_task(
                self._run_loop(self.refresh_probes, PROBE_REFRESH_SECONDS),
                name="dashboard-probe-snapshot",
            ),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def refresh_system(self) -> SystemGlanceSummary:
        return await self._refresh(
            self._system,
            self._locks["system"],
            lambda: asyncio.to_thread(get_system_glance_summary),
        )

    async def refresh_gpus(self) -> list[GpuSummary]:
        return await self._refresh(
            self._gpus,
            self._locks["gpus"],
            lambda: asyncio.to_thread(get_gpu_summaries),
        )

    async def refresh_network(self) -> NetworkConnectivity:
        return await self._refresh(
            self._network,
            self._locks["network"],
            get_network_connectivity,
        )

    async def refresh_probes(self) -> list[ProbeResult]:
        return await self._refresh(
            self._probes,
            self._locks["probes"],
            self._collect_probes,
        )

    async def get_system(self) -> SystemGlanceSummary:
        if self._system.value is None:
            return await self.refresh_system()
        return self._system.value

    async def get_gpus(self) -> list[GpuSummary]:
        if self._gpus.value is None:
            return await self.refresh_gpus()
        return self._gpus.value

    async def get_network(self) -> NetworkConnectivity:
        if self._network.value is None:
            return await self.refresh_network()
        return self._network.value

    async def get_probes(self) -> list[ProbeResult]:
        if self._probes.value is None or self._probe_results_are_unknown():
            return await self.refresh_probes()
        return self._probes.value

    async def get_probe_history(self) -> list[ProbeHistorySummary]:
        return await asyncio.to_thread(
            get_probe_history_summaries,
            self._settings.probe_history.database_path,
            self._settings.probes,
            self._settings.probe_history.summary_window_hours,
        )

    async def get_snapshot(
        self,
        sub2api_collector: Sub2ApiSnapshotCollector | None,
    ) -> DashboardSnapshot:
        await asyncio.gather(
            self._ensure_system(),
            self._ensure_gpus(),
            self._ensure_network(),
            self._ensure_probes(),
            return_exceptions=True,
        )

        sub2api = await get_sub2api_accounts(
            self._settings.sub2api,
            refreshing=sub2api_collector.refreshing if sub2api_collector is not None else False,
        )
        return DashboardSnapshot(
            checked_at=datetime.now(UTC),
            system=self._system.value,
            system_meta=self._system.meta(SYSTEM_REFRESH_SECONDS * 3),
            gpus=self._gpus.value or [],
            gpu_meta=self._gpus.meta(GPU_REFRESH_SECONDS * 3),
            network=self._network.value,
            network_meta=self._network.meta(NETWORK_REFRESH_SECONDS * 3),
            probes=self._probes.value or [],
            probes_meta=self._probes.meta(PROBE_REFRESH_SECONDS * 3),
            probe_history=await self.get_probe_history(),
            sub2api=sub2api,
        )

    async def _collect_probes(self) -> list[ProbeResult]:
        if not self._settings.probes:
            return []
        results = await run_probes(self._settings.probes)
        await asyncio.to_thread(
            save_probe_history,
            self._settings.probe_history.database_path,
            results,
            self._settings.probe_history.retention_hours,
        )
        return results

    async def _ensure_system(self) -> None:
        if self._system.value is None:
            await self.refresh_system()

    async def _ensure_gpus(self) -> None:
        if self._gpus.value is None:
            await self.refresh_gpus()

    async def _ensure_network(self) -> None:
        if self._network.value is None:
            await self.refresh_network()

    async def _ensure_probes(self) -> None:
        if self._probes.value is None or self._probe_results_are_unknown():
            await self.refresh_probes()

    async def _run_loop(
        self,
        refresh: Callable[[], Awaitable[object]],
        interval_seconds: float,
    ) -> None:
        while True:
            try:
                await refresh()
            except Exception:
                pass
            await asyncio.sleep(interval_seconds)

    async def _refresh(
        self,
        slot: _SnapshotSlot[T],
        lock: asyncio.Lock,
        collect: Callable[[], Awaitable[T]],
    ) -> T:
        async with lock:
            slot.refreshing = True
            try:
                value = await collect()
            except Exception as exc:
                slot.error = str(exc) or exc.__class__.__name__
                if slot.value is not None:
                    return slot.value
                raise
            finally:
                slot.refreshing = False

            slot.value = value
            slot.checked_at = datetime.now(UTC)
            slot.error = None
            return value

    def _probe_results_are_unknown(self) -> bool:
        return bool(self._probes.value) and all(
            result.status == "unknown" for result in self._probes.value
        )
