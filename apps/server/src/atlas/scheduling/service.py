from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from atlas.content.models import SourceUpsert
from atlas.content.service import ContentService
from atlas.db.session import create_sqlite_session_factory
from atlas.work.models import RunRecord
from atlas.work.service import WorkService
from atlas.workflows.models import WorkflowInvocationCreate
from atlas.workflows.service import WorkflowService

from .models import FavoriteScanItem, ScheduleRecord
from .repository import ScheduleRepository

LOGGER = logging.getLogger(__name__)
FAVORITES_SCHEDULE_ID = "bilibili-atlas-favorites-daily"


class ScheduleCoordinator:
    def __init__(
        self,
        repository: ScheduleRepository,
        work: WorkService,
        workflows: WorkflowService,
        content: ContentService,
        poll_seconds: float,
    ) -> None:
        self._repository = repository
        self._work = work
        self._workflows = workflows
        self._content = content
        self._poll_seconds = poll_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._ensure_builtin(_now())

    def list_schedules(self) -> list[ScheduleRecord]:
        return self._repository.list_schedules()

    def tick(self, now: datetime | None = None) -> list[str]:
        current = now or _now()
        invoked: list[str] = []
        for schedule in self._repository.list_schedules():
            if not schedule.enabled:
                continue
            local = current.astimezone(ZoneInfo(schedule.timezone))
            occurrence = local.date().isoformat()
            if local.time() < time(schedule.hour, schedule.minute):
                continue
            if (
                schedule.last_occurrence_date is not None
                and schedule.last_occurrence_date >= occurrence
            ):
                continue
            invocation = self._workflows.invoke_once(
                WorkflowInvocationCreate(
                    workflow_name=schedule.workflow_name,
                    workflow_version=schedule.workflow_version,
                    input={**schedule.input, "occurrence_date": occurrence},
                ),
                f"schedule:{schedule.schedule_id}:{occurrence}",
            )
            self._repository.mark_occurrence(
                schedule.schedule_id, occurrence, invocation.invocation_id, current
            )
            invoked.append(invocation.invocation_id)
        self.reconcile_favorites()
        return invoked

    def reconcile_favorites(self) -> int:
        dispatched = 0
        for run in self._work.list_runs(project_id="bilibili-ingest", limit=500):
            if (
                run.status != "completed"
                or run.workflow is None
                or run.workflow.name != "bilibili.favorites-scan"
                or run.workflow.version != "1"
                or run.step_name != "scan"
            ):
                continue
            dispatched += self._dispatch_scan(run)
        return dispatched

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                LOGGER.exception("Atlas schedule tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                pass

    def _dispatch_scan(self, run: RunRecord) -> int:
        raw_items = (run.output or {}).get("items")
        if not isinstance(raw_items, list):
            raise ValueError(f"favorites scan {run.run_id} omitted items")
        if len(raw_items) > 500:
            raise ValueError(f"favorites scan {run.run_id} exceeded 500 items")
        dispatched = 0
        for raw in raw_items:
            item = FavoriteScanItem.model_validate(raw)
            fanout_key = f"{run.run_id}:{item.bvid}"
            if self._repository.get_fanout(fanout_key) is not None:
                continue
            url = f"https://www.bilibili.com/video/{item.bvid}"
            source = self._content.upsert_source(
                SourceUpsert(
                    source_key=f"bilibili:{item.bvid}",
                    kind="video",
                    canonical_uri=url,
                    title=item.title,
                    external_ids={"bvid": item.bvid, "aid": item.aid},
                    metadata={
                        "captured_via": "atlas-scheduled-favorites-scan",
                        "bilibili_owner": item.owner,
                        "duration_seconds": item.duration_seconds,
                    },
                )
            )
            summaries = self._content.list_resources(
                source_id=source.source_id, kind="summary", limit=1
            )
            if summaries:
                disposition = "reused"
                invocation_id = None
            else:
                invocation = self._workflows.invoke_once(
                    WorkflowInvocationCreate(
                        workflow_name="bilibili.summary",
                        workflow_version="5",
                        input={
                            "url": url,
                            "canonical_url": url,
                            "source_id": source.source_id,
                            "origin": "bilibili-atlas-favorites-scheduled",
                            "scan_run_id": run.run_id,
                        },
                    ),
                    f"favorites-summary:{run.run_id}:{item.bvid}",
                )
                disposition = "invoked"
                invocation_id = invocation.invocation_id
            self._repository.record_fanout(
                fanout_key,
                run.run_id,
                item.bvid,
                source.source_id,
                disposition,
                invocation_id,
                _now(),
            )
            dispatched += 1
        return dispatched

    def _ensure_builtin(self, now: datetime) -> None:
        self._repository.ensure_daily_schedule(
            FAVORITES_SCHEDULE_ID,
            "bilibili.favorites-scan",
            "1",
            {"folder_name": "Atlas"},
            "Asia/Shanghai",
            2,
            0,
            now,
        )


def create_schedule_coordinator(
    database_path: Path,
    work: WorkService,
    workflows: WorkflowService,
    content: ContentService,
    poll_seconds: float,
) -> ScheduleCoordinator:
    return ScheduleCoordinator(
        ScheduleRepository(create_sqlite_session_factory(database_path)),
        work,
        workflows,
        content,
        poll_seconds,
    )


def _now() -> datetime:
    return datetime.now(UTC)
