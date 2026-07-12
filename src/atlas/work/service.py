from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from atlas.db.session import create_sqlite_session_factory

from .models import (
    ArtifactRef,
    EventRecord,
    ProjectCreate,
    ProjectRecord,
    RunCancel,
    RunComplete,
    RunCreate,
    RunFail,
    RunRecord,
    RunStatus,
)
from .repository import WorkRepository


class WorkService:
    def __init__(
        self,
        repository: WorkRepository,
        lease_ttl_seconds: int = 120,
    ) -> None:
        self._repository = repository
        self._lease_ttl = timedelta(seconds=lease_ttl_seconds)

    # ── Projects ──────────────────────────────────────────────

    def create_project(self, payload: ProjectCreate) -> ProjectRecord:
        return self._repository.create_project(payload, _now())

    def list_projects(self) -> list[ProjectRecord]:
        return self._repository.list_projects()

    # ── Runs ──────────────────────────────────────────────────

    def enqueue_run(self, payload: RunCreate) -> RunRecord:
        record = self._repository.create_run(payload, _now())
        self._append_event(record.run_id, None, "enqueued", body="Run created")
        return record

    def claim_next(self, agent_id: str, capabilities: list[str] | None = None) -> RunRecord | None:
        now = _now()
        run = self._repository.find_next_pending(capabilities, now)
        if run is None:
            return None
        lease = now + self._lease_ttl
        claimed = self._repository.claim_run(run.run_id, agent_id, lease, now)
        self._append_event(
            claimed.run_id,
            agent_id,
            "claimed",
            body=f"Claimed by {agent_id}, attempt {claimed.attempt_number}",
        )
        return claimed

    def claim_by_id(self, run_id: str, agent_id: str) -> RunRecord:
        now = _now()
        lease = now + self._lease_ttl
        run = self._repository.claim_run(run_id, agent_id, lease, now)
        self._append_event(
            run.run_id,
            agent_id,
            "claimed",
            body=f"Claimed by {agent_id}, attempt {run.attempt_number}",
        )
        return run

    def heartbeat(self, run_id: str, agent_id: str) -> RunRecord:
        lease = _now() + self._lease_ttl
        return self._repository.heartbeat_run(run_id, agent_id, lease)

    def complete(self, run_id: str, payload: RunComplete) -> RunRecord:
        run = self._repository.complete_run(
            run_id,
            payload.agent_id,
            payload.output,
            payload.artifacts,
            _now(),
        )
        self._append_event(
            run.run_id,
            payload.agent_id,
            "completed",
            body=f"Completed with {len(payload.artifacts)} artifact(s)",
        )
        return run

    def fail(self, run_id: str, payload: RunFail) -> RunRecord:
        run = self._repository.fail_run(run_id, payload.agent_id, payload.error_message, _now())
        self._append_event(
            run.run_id,
            payload.agent_id,
            "failed",
            body=payload.error_message or "No error message",
        )
        return run

    def cancel(self, run_id: str, payload: RunCancel) -> RunRecord:
        run = self._repository.cancel_run(run_id, _now())
        self._append_event(
            run.run_id,
            payload.agent_id,
            "cancelled",
            body="Cancelled manually",
        )
        return run

    def get_run(self, run_id: str) -> RunRecord:
        return self._repository.get_run(run_id)

    def list_runs(
        self,
        project_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        return self._repository.list_runs(project_id=project_id, status=status, limit=limit)

    # ── Events ────────────────────────────────────────────────

    def list_events(self, run_id: str, limit: int = 200) -> list[EventRecord]:
        return self._repository.list_events(run_id, limit=limit)

    # ── Artifacts ─────────────────────────────────────────────

    def list_artifacts(self, run_id: str) -> list[ArtifactRef]:
        return self._repository.list_artifacts(run_id)

    # ── Helpers ────────────────────────────────────────────────

    def _append_event(
        self,
        run_id: str,
        agent_id: str | None,
        event_type: str,
        body: str,
    ) -> None:
        try:
            self._repository.append_event(run_id, agent_id, event_type, body, _now())
        except Exception:
            pass  # non-fatal; event logging best-effort only


def _now() -> datetime:
    return datetime.now(UTC)


def create_work_service(
    database_path: Path,
    lease_ttl_seconds: int = 120,
) -> WorkService:
    session_factory = create_sqlite_session_factory(database_path)
    return WorkService(
        repository=WorkRepository(session_factory),
        lease_ttl_seconds=lease_ttl_seconds,
    )
