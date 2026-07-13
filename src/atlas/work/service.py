from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from atlas.db.session import create_sqlite_session_factory

from .models import (
    ArtifactRef,
    EventRecord,
    ExecutionAttemptRecord,
    ProjectCreate,
    ProjectRecord,
    ReconcileRequest,
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
        return self._repository.create_run(payload, _now())

    def claim_next(self, agent_id: str, capabilities: list[str] | None = None) -> (
        tuple[RunRecord, str, str] | None
    ):
        now = _now()
        lease = now + self._lease_ttl
        result = self._repository.claim_next_atomic(
            agent_id, lease, now, capabilities
        )
        if result is None:
            return None
        return result.run, result.attempt_id, result.claim_token

    def claim_by_id(
        self, run_id: str, agent_id: str, capabilities: list[str]
    ) -> tuple[RunRecord, str, str]:
        now = _now()
        lease = now + self._lease_ttl
        result = self._repository.claim_run(run_id, agent_id, lease, now, capabilities)
        return result.run, result.attempt_id, result.claim_token

    def heartbeat(self, run_id: str, agent_id: str, attempt_id: str, claim_token: str) -> RunRecord:
        lease = _now() + self._lease_ttl
        return self._repository.heartbeat_run(
            run_id, agent_id, attempt_id, claim_token, lease, _now()
        )

    def complete(
        self,
        run_id: str,
        payload: RunComplete,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        return self._repository.complete_run(
            run_id,
            payload.attempt_id,
            payload.claim_token,
            payload.agent_id,
            payload.output,
            payload.artifacts,
            _now(),
            idempotency_key=idempotency_key,
            payload_digest=_payload_digest(payload) if idempotency_key else None,
        )

    def fail(
        self,
        run_id: str,
        payload: RunFail,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        return self._repository.fail_run(
            run_id,
            payload.attempt_id,
            payload.claim_token,
            payload.agent_id,
            payload.error_code,
            payload.error_message,
            payload.retryable,
            _now(),
            idempotency_key=idempotency_key,
            payload_digest=_payload_digest(payload) if idempotency_key else None,
        )

    def cancel(self, run_id: str, payload: RunCancel) -> RunRecord:
        return self._repository.cancel_run(run_id, _now())

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

    def reconcile(
        self,
        run_id: str,
        agent_id: str,
        request: ReconcileRequest,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        return self._repository.reconcile_attempt(
            run_id, agent_id, request, _now(), idempotency_key=idempotency_key
        )

    def list_attempts(self, run_id: str) -> list[ExecutionAttemptRecord]:
        return self._repository.list_attempts(run_id)

    def list_artifacts(self, run_id: str) -> list[ArtifactRef]:
        return self._repository.list_artifacts(run_id)


def _now() -> datetime:
    return datetime.now(UTC)


def _payload_digest(payload: Any) -> str:
    """Produce a stable digest of a Pydantic model for idempotency."""
    raw = payload.model_dump_json()
    return hashlib.sha256(raw.encode()).hexdigest()


def create_work_service(
    database_path: Path,
    lease_ttl_seconds: int = 120,
) -> WorkService:
    session_factory = create_sqlite_session_factory(database_path)
    return WorkService(
        repository=WorkRepository(session_factory),
        lease_ttl_seconds=lease_ttl_seconds,
    )
