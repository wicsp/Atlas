from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, String, Text, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from atlas.content.models import ResourceCreate, SourceUpdate
from atlas.content.repository import apply_source_updates, publish_resources
from atlas.db.base import Base

from .models import (
    EXECUTION_CONTRACT_METADATA_KEY,
    ArtifactRef,
    ArtifactRefCreate,
    EventRecord,
    ExecutionAttemptRecord,
    ProjectCreate,
    ProjectRecord,
    RunCreate,
    RunRecord,
    RunStatus,
    SchedulingProfile,
)


class ProjectRow(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(64))


class RunRow(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    job_name: Mapped[str] = mapped_column(String(128))
    capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    started_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


class EventRow(Base):
    __tablename__ = "run_events"

    event_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    agent_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(64), index=True)


class ArtifactRow(Base):
    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    name: Mapped[str] = mapped_column(String(256))
    uri: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checksum: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64))


class IdempotencyRow(Base):
    __tablename__ = "run_idempotency"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    operation_type: Mapped[str] = mapped_column(String(32))
    payload_digest: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[str] = mapped_column(String(64))


class ExecutionAttemptRow(Base):
    __tablename__ = "execution_attempts"

    attempt_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(128), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[str] = mapped_column(String(128))
    claim_token_digest: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    lease_expires_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64))
    finished_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result_digest: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ClaimResult:
    """Result of a successful claim operation."""
    __slots__ = ("run", "attempt_id", "claim_token")

    def __init__(self, run: RunRecord, attempt_id: str, claim_token: str) -> None:
        self.run = run
        self.attempt_id = attempt_id
        self.claim_token = claim_token


class WorkRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # ── Projects ──────────────────────────────────────────────

    def create_project(self, payload: ProjectCreate, now: datetime) -> ProjectRecord:
        with self._session_factory() as session, session.begin():
            row = session.get(ProjectRow, payload.project_id)
            if row is None:
                row = ProjectRow(
                    project_id=payload.project_id,
                    name=payload.name,
                    description=payload.description,
                    created_at=now.isoformat(),
                )
                session.add(row)
            else:
                row.name = payload.name
                row.description = payload.description
            session.flush()
            return _to_project(row)

    def list_projects(self) -> list[ProjectRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ProjectRow).order_by(ProjectRow.created_at)
            ).all()
            return [_to_project(row) for row in rows]

    # ── Runs ──────────────────────────────────────────────────

    def create_run(self, payload: RunCreate, now: datetime) -> RunRecord:
        with self._session_factory() as session:
            metadata = dict(payload.metadata)
            has_requirements = payload.requirements.model_dump(exclude_defaults=True)
            if payload.workflow is not None or has_requirements:
                metadata[EXECUTION_CONTRACT_METADATA_KEY] = {
                    "workflow": payload.workflow.model_dump() if payload.workflow else None,
                    "step_name": payload.step_name,
                    "requirements": payload.requirements.model_dump(),
                    "workflow_invocation_id": payload.workflow_invocation_id,
                    "depends_on_run_ids": payload.depends_on_run_ids,
                }
            row = RunRow(
                run_id=payload.run_id or f"run_{uuid.uuid4().hex}",
                project_id=payload.project_id,
                job_name=payload.job_name,
                capabilities_json=_dump_json(payload.capabilities_required),
                input_json=_dump_json(payload.input),
                status=payload.initial_status,
                attempt_number=0,
                max_attempts=payload.max_attempts,
                priority=payload.priority,
                metadata_json=_dump_json(metadata),
                created_at=now.isoformat(),
            )
            session.add(row)
            session.add(
                EventRow(
                    event_id=f"evt_{uuid.uuid4().hex}",
                    run_id=row.run_id,
                    agent_id=None,
                    event_type="enqueued" if payload.initial_status == "pending" else "blocked",
                    body=(
                        "Run created"
                        if payload.initial_status == "pending"
                        else "Run waiting for workflow dependencies"
                    ),
                    created_at=now.isoformat(),
                )
            )
            session.commit()
            return _to_run(row)

    def get_run(self, run_id: str) -> RunRecord:
        with self._session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            return _to_run(row)

    def list_runs(
        self,
        project_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        with self._session_factory() as session:
            stmt = select(RunRow).order_by(RunRow.created_at.desc()).limit(limit)
            if project_id:
                stmt = stmt.where(RunRow.project_id == project_id)
            if status:
                stmt = stmt.where(RunRow.status == status)
            rows = session.scalars(stmt).all()
            return [_to_run(row) for row in rows]

    def find_next_pending(
        self,
        capabilities: list[str] | None,
        now: datetime,
    ) -> RunRecord | None:
        """Return the highest-priority pending run, expiring stale claims first."""
        with self._session_factory() as session:
            # Expire stale claimed runs
            stale = session.scalars(
                select(RunRow)
                .where(RunRow.status == "claimed")
                .where(RunRow.lease_expires_at <= now.isoformat())
            ).all()
            for row in stale:
                row.status = "pending"
                row.agent_id = None
                row.lease_expires_at = None
            if stale:
                session.commit()

            # Find highest-priority pending run
            stmt = (
                select(RunRow)
                .where(RunRow.status == "pending")
                .where(RunRow.attempt_number < RunRow.max_attempts)
                .order_by(RunRow.priority.desc(), RunRow.created_at)
                .limit(50)
            )
            if capabilities:
                # Filter runs whose required capabilities are a subset of agent capabilities
                candidates = session.scalars(stmt).all()
                matching = [
                    row
                    for row in candidates
                    if _capabilities_match(row.capabilities_json, capabilities)
                ]
                row = matching[0] if matching else None
            else:
                row = session.scalars(stmt).first()

            if row is None:
                return None

            return _to_run(row)


    def claim_next_atomic(
        self,
        agent_id: str,
        lease_expires_at: datetime,
        now: datetime,
        capabilities: list[str] | None = None,
        scheduling_profile: SchedulingProfile | None = None,
    ) -> RunRecord | None:
        """Atomically find + claim a pending run in a single transaction.

        Uses UPDATE … WHERE status = 'pending' as a concurrency guard so that
        two agents claiming simultaneously produce exactly one winner.
        """
        with self._session_factory() as session, session.begin():
            # Expire stale claims first.
            stale = session.scalars(
                select(RunRow)
                .where(RunRow.status == "claimed")
                .where(RunRow.lease_expires_at <= now.isoformat())
            ).all()
            for row in stale:
                previous_agent = row.agent_id
                if row.attempt_number >= row.max_attempts:
                    row.status = "failed"
                    row.error_message = "lease expired; attempts exhausted"
                    row.completed_at = now.isoformat()
                    event_type = "failed"
                    body = "Lease expired and all attempts were exhausted"
                else:
                    row.status = "pending"
                    event_type = "lease_expired"
                    body = "Lease expired; run returned to pending"
                row.agent_id = None
                row.lease_expires_at = None
                session.add(
                    EventRow(
                        event_id=f"evt_{uuid.uuid4().hex}",
                        run_id=row.run_id,
                        agent_id=previous_agent,
                        event_type=event_type,
                        body=body,
                        created_at=now.isoformat(),
                    )
                )

            # Find candidates (up to 50 to allow Python-side capability matching).
            stmt = (
                select(RunRow)
                .where(RunRow.status == "pending")
                .where(RunRow.attempt_number < RunRow.max_attempts)
                .order_by(RunRow.priority.desc(), RunRow.created_at)
                .limit(50)
            )
            candidates = list(session.scalars(stmt).all())

            effective_capabilities = capabilities or []
            matching = [
                row
                for row in candidates
                if _capabilities_match(row.capabilities_json, effective_capabilities)
                and _execution_requirements_match(row.metadata_json, scheduling_profile)
            ]

            if not matching:
                return None

            # Try to atomically claim the best match.
            target = matching[0]
            result = session.execute(
                update(RunRow)
                .where(RunRow.run_id == target.run_id)
                .where(RunRow.status == "pending")
                .values(
                    status="claimed",
                    agent_id=agent_id,
                    lease_expires_at=lease_expires_at.isoformat(),
                    attempt_number=RunRow.attempt_number + 1,
                    started_at=now.isoformat(),
                )
            )
            if result.rowcount == 0:
                # Another concurrent claim won the race.
                return None

            # Reload the updated row (the ORM identity map still has the old state).
            session.expire(target)
            claimed = session.get(RunRow, target.run_id)
            assert claimed is not None, "Run must exist after atomic claim"

            session.add(
                EventRow(
                    event_id=f"evt_{uuid.uuid4().hex}",
                    run_id=claimed.run_id,
                    agent_id=agent_id,
                    event_type="claimed",
                    body=f"Claimed by {agent_id}, attempt {claimed.attempt_number}",
                    created_at=now.isoformat(),
                )
            )

            # Supersede previous active attempts for this run.
            session.execute(
                update(ExecutionAttemptRow)
                .where(ExecutionAttemptRow.run_id == claimed.run_id)
                .where(ExecutionAttemptRow.status == "active")
                .values(status="superseded", finished_at=now.isoformat())
            )

            # Create execution attempt with claim token.
            claim_token = secrets.token_urlsafe(32)
            attempt_id = f"attempt_{uuid.uuid4().hex}"
            session.add(
                ExecutionAttemptRow(
                    attempt_id=attempt_id,
                    run_id=claimed.run_id,
                    attempt_number=claimed.attempt_number,
                    agent_id=agent_id,
                    claim_token_digest=_claim_token_digest(claim_token),
                    status="active",
                    lease_expires_at=lease_expires_at.isoformat(),
                    created_at=now.isoformat(),
                )
            )

            return ClaimResult(
                run=_to_run(claimed),
                attempt_id=attempt_id,
                claim_token=claim_token,
            )

    def claim_run(
        self,
        run_id: str,
        agent_id: str,
        lease_expires_at: datetime,
        now: datetime,
        capabilities: list[str],
        scheduling_profile: SchedulingProfile | None = None,
    ) -> ClaimResult:
        with self._session_factory() as session, session.begin():
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.status != "pending":
                raise ValueError(f"Run {run_id} is not pending (status={row.status})")
            if row.attempt_number >= row.max_attempts:
                raise ValueError(f"Run {run_id} has exhausted all attempts")
            if not _capabilities_match(row.capabilities_json, capabilities):
                raise PermissionError(f"Agent lacks capabilities required by run {run_id}")
            if not _execution_requirements_match(row.metadata_json, scheduling_profile):
                raise PermissionError(
                    f"Runner does not satisfy execution requirements for run {run_id}"
                )
            result = session.execute(
                update(RunRow)
                .where(RunRow.run_id == run_id)
                .where(RunRow.status == "pending")
                .where(RunRow.attempt_number < RunRow.max_attempts)
                .values(
                    status="claimed",
                    agent_id=agent_id,
                    lease_expires_at=lease_expires_at.isoformat(),
                    attempt_number=RunRow.attempt_number + 1,
                    started_at=now.isoformat(),
                )
            )
            if result.rowcount == 0:
                raise ValueError(f"Run {run_id} was claimed concurrently")
            session.expire(row)
            claimed = session.get(RunRow, run_id)
            assert claimed is not None
            session.add(
                EventRow(
                    event_id=f"evt_{uuid.uuid4().hex}",
                    run_id=run_id,
                    agent_id=agent_id,
                    event_type="claimed",
                    body=f"Claimed by {agent_id}, attempt {claimed.attempt_number}",
                    created_at=now.isoformat(),
                )
            )

            # Supersede previous active attempts for this run.
            session.execute(
                update(ExecutionAttemptRow)
                .where(ExecutionAttemptRow.run_id == run_id)
                .where(ExecutionAttemptRow.status == "active")
                .values(status="superseded", finished_at=now.isoformat())
            )

            # Create execution attempt with claim token.
            claim_token = secrets.token_urlsafe(32)
            attempt_id = f"attempt_{uuid.uuid4().hex}"
            session.add(
                ExecutionAttemptRow(
                    attempt_id=attempt_id,
                    run_id=run_id,
                    attempt_number=claimed.attempt_number,
                    agent_id=agent_id,
                    claim_token_digest=_claim_token_digest(claim_token),
                    status="active",
                    lease_expires_at=lease_expires_at.isoformat(),
                    created_at=now.isoformat(),
                )
            )

            return ClaimResult(
                run=_to_run(claimed),
                attempt_id=attempt_id,
                claim_token=claim_token,
            )

    def heartbeat_run(
        self,
        run_id: str,
        agent_id: str,
        attempt_id: str,
        claim_token: str,
        lease_expires_at: datetime,
        now: datetime,
    ) -> RunRecord:
        with self._session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.status != "claimed":
                raise ValueError(f"Run {run_id} is not claimed")
            if row.agent_id != agent_id:
                raise PermissionError(f"Run {run_id} is claimed by {row.agent_id}")
            if row.lease_expires_at is not None and row.lease_expires_at <= now.isoformat():
                raise PermissionError("lease expired")

            # Validate attempt ownership — only the claiming attempt's owner may heartbeat.
            attempt_row = session.get(ExecutionAttemptRow, attempt_id)
            if attempt_row is None:
                raise PermissionError(f"Attempt {attempt_id} not found for run {run_id}")
            if attempt_row.run_id != run_id:
                raise PermissionError(f"Attempt {attempt_id} does not belong to run {run_id}")
            if attempt_row.status != "active":
                raise PermissionError(f"Attempt {attempt_id} is {attempt_row.status}, not active")
            expected_digest = _claim_token_digest(claim_token)
            if not secrets.compare_digest(attempt_row.claim_token_digest, expected_digest):
                raise PermissionError("Invalid claim token")

            row.lease_expires_at = lease_expires_at.isoformat()
            session.commit()
            return _to_run(row)

    def complete_run(
        self,
        run_id: str,
        attempt_id: str,
        claim_token: str,
        agent_id: str,
        output: dict[str, Any],
        artifacts: list[ArtifactRefCreate],
        source_updates: list[SourceUpdate],
        resources: list[ResourceCreate],
        now: datetime,
        idempotency_key: str | None = None,
        payload_digest: str | None = None,
    ) -> RunRecord:
        with self._session_factory() as session:
            # M2.5 P0-1: idempotency detection.
            if idempotency_key and payload_digest:
                cached = session.get(IdempotencyRow, idempotency_key)
                if cached is not None:
                    if cached.run_id != run_id or cached.operation_type != "complete":
                        raise ValueError("Idempotency key already used for a different operation")
                    if cached.payload_digest == payload_digest:
                        # Replay — return the already-terminal run.
                        run_row = session.get(RunRow, run_id)
                        if run_row is None:
                            raise KeyError(run_id)
                        return _to_run(run_row)
                    raise ValueError("Idempotency key reused with a different payload")

            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            # M2.5: must be claimed by the reporting agent.
            if row.status != "claimed":
                raise ValueError(
                    f"Run {run_id} is not claimed (status={row.status}); "
                    "only claimed runs can complete"
                )
            if row.agent_id != agent_id:
                raise PermissionError(f"Run {run_id} is claimed by {row.agent_id}, not {agent_id}")
            # Verify claim token.
            attempt_row = session.get(ExecutionAttemptRow, attempt_id)
            if attempt_row is None:
                raise PermissionError(f"Attempt {attempt_id} not found for run {run_id}")
            if attempt_row.run_id != run_id:
                raise PermissionError(f"Attempt {attempt_id} does not belong to run {run_id}")
            if attempt_row.status != "active":
                raise PermissionError(f"Attempt {attempt_id} is {attempt_row.status}, not active")
            expected_digest = _claim_token_digest(claim_token)
            if not secrets.compare_digest(attempt_row.claim_token_digest, expected_digest):
                raise PermissionError("Invalid claim token")

            # RFC 0002: reject complete/fail on expired lease.
            if row.lease_expires_at is not None and row.lease_expires_at <= now.isoformat():
                raise PermissionError("lease expired")

            artifacts_by_name: dict[str, str] = {}
            for art in artifacts:
                artifact_id = f"art_{uuid.uuid4().hex}"
                artifacts_by_name[art.name] = artifact_id
                session.add(
                    ArtifactRow(
                        artifact_id=artifact_id,
                        run_id=run_id,
                        name=art.name,
                        uri=art.uri,
                        content_type=art.content_type,
                        size_bytes=art.size_bytes,
                        checksum=art.checksum,
                        created_at=now.isoformat(),
                    )
                )

            # RFC 0003: Source enrichment, ArtifactRefs, and Resource publication
            # are part of the same transaction as the terminal Run state.
            apply_source_updates(session, source_updates, now)
            publish_resources(session, run_id, artifacts_by_name, resources, now)

            row.status = "completed"
            row.agent_id = agent_id
            row.output_json = _dump_json(output)
            row.completed_at = now.isoformat()
            row.lease_expires_at = None

            session.add(
                EventRow(
                    event_id=f"evt_{uuid.uuid4().hex}",
                    run_id=run_id,
                    agent_id=agent_id,
                    event_type="completed",
                    body=(
                        f"Completed with {len(artifacts)} artifact(s) and "
                        f"{len(resources)} resource(s)"
                    ),
                    created_at=now.isoformat(),
                )
            )

            if idempotency_key and payload_digest:
                session.add(
                    IdempotencyRow(
                        idempotency_key=idempotency_key,
                        run_id=run_id,
                        operation_type="complete",
                        payload_digest=payload_digest,
                        created_at=now.isoformat(),
                    )
                )

            _unblock_ready_dependents(session, run_id, now)

            # Update execution attempt.
            result_digest = hashlib.sha256(
                json.dumps(output, sort_keys=True).encode()
            ).hexdigest()
            attempt_row.status = "accepted"
            attempt_row.finished_at = now.isoformat()
            attempt_row.result_digest = result_digest

            session.commit()
            return _to_run(row)

    def fail_run(
        self,
        run_id: str,
        attempt_id: str,
        claim_token: str,
        agent_id: str,
        error_code: str | None,
        error_message: str | None,
        retryable: bool,
        now: datetime,
        idempotency_key: str | None = None,
        payload_digest: str | None = None,
    ) -> RunRecord:
        with self._session_factory() as session:
            if idempotency_key and payload_digest:
                cached = session.get(IdempotencyRow, idempotency_key)
                if cached is not None:
                    if cached.run_id != run_id or cached.operation_type != "fail":
                        raise ValueError("Idempotency key already used for a different operation")
                    if cached.payload_digest == payload_digest:
                        run_row = session.get(RunRow, run_id)
                        if run_row is None:
                            raise KeyError(run_id)
                        return _to_run(run_row)
                    raise ValueError("Idempotency key reused with a different payload")

            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.status != "claimed":
                raise ValueError(
                    f"Run {run_id} is not claimed (status={row.status}); "
                    "only claimed runs can fail"
                )
            if row.agent_id != agent_id:
                raise PermissionError(f"Run {run_id} is claimed by {row.agent_id}, not {agent_id}")
            # Verify claim token.
            attempt_row = session.get(ExecutionAttemptRow, attempt_id)
            if attempt_row is None:
                raise PermissionError(f"Attempt {attempt_id} not found for run {run_id}")
            if attempt_row.run_id != run_id:
                raise PermissionError(f"Attempt {attempt_id} does not belong to run {run_id}")
            if attempt_row.status != "active":
                raise PermissionError(f"Attempt {attempt_id} is {attempt_row.status}, not active")
            expected_digest = _claim_token_digest(claim_token)
            if not secrets.compare_digest(attempt_row.claim_token_digest, expected_digest):
                raise PermissionError("Invalid claim token")

            # RFC 0002: reject complete/fail on expired lease.
            if row.lease_expires_at is not None and row.lease_expires_at <= now.isoformat():
                raise PermissionError("lease expired")

            should_retry = retryable and row.attempt_number < row.max_attempts
            row.status = "pending" if should_retry else "failed"
            row.agent_id = None if should_retry else agent_id
            prefix = f"[{error_code}] " if error_code else ""
            row.error_message = error_message
            row.completed_at = None if should_retry else now.isoformat()
            row.lease_expires_at = None
            session.add(
                EventRow(
                    event_id=f"evt_{uuid.uuid4().hex}",
                    run_id=run_id,
                    agent_id=agent_id,
                    event_type="retry_scheduled" if should_retry else "failed",
                    body=prefix + (error_message or "No error message"),
                    created_at=now.isoformat(),
                )
            )

            if idempotency_key and payload_digest:
                session.add(
                    IdempotencyRow(
                        idempotency_key=idempotency_key,
                        run_id=run_id,
                        operation_type="fail",
                        payload_digest=payload_digest,
                        created_at=now.isoformat(),
                    )
                )

            # Update execution attempt.
            result_digest = hashlib.sha256(
                f"fail:{error_message or ''}".encode()
            ).hexdigest()
            attempt_row.status = "failed"
            attempt_row.finished_at = now.isoformat()
            attempt_row.result_digest = result_digest

            session.commit()
            return _to_run(row)

    def cancel_run(self, run_id: str, now: datetime) -> RunRecord:
        with self._session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.status in ("completed", "failed", "cancelled"):
                raise ValueError(f"Run {run_id} is already terminal (status={row.status})")
            row.status = "cancelled"
            row.completed_at = now.isoformat()
            row.lease_expires_at = None
            session.add(
                EventRow(
                    event_id=f"evt_{uuid.uuid4().hex}",
                    run_id=run_id,
                    agent_id=row.agent_id,
                    event_type="cancelled",
                    body="Cancelled manually",
                    created_at=now.isoformat(),
                )
            )
            session.commit()
            return _to_run(row)

    # ── Events ────────────────────────────────────────────────

    def append_event(
        self,
        run_id: str,
        agent_id: str | None,
        event_type: str,
        body: str,
        now: datetime,
    ) -> EventRecord:
        with self._session_factory() as session:
            row = EventRow(
                event_id=f"evt_{uuid.uuid4().hex}",
                run_id=run_id,
                agent_id=agent_id,
                event_type=event_type,
                body=body,
                created_at=now.isoformat(),
            )
            session.add(row)
            session.commit()
            return _to_event(row)

    def list_attempts(self, run_id: str) -> list[ExecutionAttemptRecord]:
        """Return all execution attempts for a run, ordered by creation time."""
        with self._session_factory() as session:
            rows = session.scalars(
                select(ExecutionAttemptRow)
                .where(ExecutionAttemptRow.run_id == run_id)
                .order_by(ExecutionAttemptRow.created_at)
            ).all()
            return [_to_attempt(row) for row in rows]

    def list_events(self, run_id: str, limit: int = 200) -> list[EventRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(EventRow)
                .where(EventRow.run_id == run_id)
                .order_by(EventRow.created_at)
                .limit(limit)
            ).all()
            return [_to_event(row) for row in rows]

    # ── Artifacts ─────────────────────────────────────────────

    def list_artifacts(self, run_id: str) -> list[ArtifactRef]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(ArtifactRow)
                .where(ArtifactRow.run_id == run_id)
                .order_by(ArtifactRow.created_at)
            ).all()
            return [_to_artifact(row) for row in rows]


# ── JSON helpers ──────────────────────────────────────────


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: str | None, fallback: Any) -> Any:
    if value is None:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _capabilities_match(required_json: str, agent_capabilities: list[str]) -> bool:
    required = _load_json(required_json, [])
    if not required:
        return True
    agent_set = set(agent_capabilities)
    return all(c in agent_set for c in required)


def _execution_requirements_match(
    metadata_json: str,
    profile: SchedulingProfile | None,
) -> bool:
    metadata = _load_json(metadata_json, {})
    contract = metadata.get(EXECUTION_CONTRACT_METADATA_KEY)
    if not isinstance(contract, dict):
        return True
    requirements = contract.get("requirements") or {}
    if not any(requirements.get(key) for key in ("node_ids", "executors", "node_labels", "grants")):
        return True
    if profile is None or not profile.is_runner:
        return False
    node_ids = set(requirements.get("node_ids") or [])
    if node_ids and profile.node_id not in node_ids:
        return False
    executors = set(requirements.get("executors") or [])
    if executors and not executors.intersection(profile.executors):
        return False
    if not set(requirements.get("node_labels") or []).issubset(profile.node_labels):
        return False
    if not set(requirements.get("grants") or []).issubset(profile.available_grants):
        return False
    return True


def _claim_token_digest(token: str) -> str:
    """SHA256 digest of a claim token for database storage."""
    return hashlib.sha256(token.encode()).hexdigest()


def _to_attempt(row: ExecutionAttemptRow) -> ExecutionAttemptRecord:
    return ExecutionAttemptRecord(
        attempt_id=row.attempt_id,
        run_id=row.run_id,
        attempt_number=row.attempt_number,
        agent_id=row.agent_id,
        status=row.status,  # type: ignore[arg-type]
        lease_expires_at=_parse_datetime(row.lease_expires_at),
        created_at=datetime.fromisoformat(row.created_at),
        finished_at=_parse_datetime(row.finished_at),
        result_digest=row.result_digest,
    )


# ── Row → Record converters ───────────────────────────────


def _to_project(row: ProjectRow) -> ProjectRecord:
    return ProjectRecord(
        project_id=row.project_id,
        name=row.name,
        description=row.description,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _to_run(row: RunRow) -> RunRecord:
    stored_metadata = _load_json(row.metadata_json, {})
    contract = stored_metadata.pop(EXECUTION_CONTRACT_METADATA_KEY, {})
    return RunRecord(
        run_id=row.run_id,
        project_id=row.project_id,
        job_name=row.job_name,
        capabilities_required=_load_json(row.capabilities_json, []),
        input=_load_json(row.input_json, {}),
        output=_load_json(row.output_json, None),
        status=row.status,  # type: ignore[arg-type]
        agent_id=row.agent_id,
        lease_expires_at=_parse_datetime(row.lease_expires_at),
        attempt_number=row.attempt_number,
        max_attempts=row.max_attempts,
        priority=row.priority,
        metadata=stored_metadata,
        workflow=contract.get("workflow"),
        step_name=contract.get("step_name"),
        requirements=contract.get("requirements", {}),
        workflow_invocation_id=contract.get("workflow_invocation_id"),
        depends_on_run_ids=contract.get("depends_on_run_ids", []),
        error_message=row.error_message,
        created_at=datetime.fromisoformat(row.created_at),
        started_at=_parse_datetime(row.started_at),
        completed_at=_parse_datetime(row.completed_at),
    )


def _unblock_ready_dependents(session: Session, completed_run_id: str, now: datetime) -> None:
    blocked = session.scalars(select(RunRow).where(RunRow.status == "blocked")).all()
    for candidate in blocked:
        metadata = _load_json(candidate.metadata_json, {})
        contract = metadata.get(EXECUTION_CONTRACT_METADATA_KEY)
        if not isinstance(contract, dict):
            continue
        dependencies = contract.get("depends_on_run_ids") or []
        if completed_run_id not in dependencies:
            continue
        dependency_rows = [session.get(RunRow, dependency_id) for dependency_id in dependencies]
        if dependency_rows and all(row is not None and row.status == "completed" for row in dependency_rows):
            candidate.status = "pending"
            session.add(
                EventRow(
                    event_id=f"evt_{uuid.uuid4().hex}",
                    run_id=candidate.run_id,
                    agent_id=None,
                    event_type="unblocked",
                    body="Workflow dependencies completed",
                    created_at=now.isoformat(),
                )
            )


def _to_event(row: EventRow) -> EventRecord:
    return EventRecord(
        event_id=row.event_id,
        run_id=row.run_id,
        agent_id=row.agent_id,
        event_type=row.event_type,
        body=row.body,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _to_artifact(row: ArtifactRow) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=row.artifact_id,
        run_id=row.run_id,
        name=row.name,
        uri=row.uri,
        content_type=row.content_type,
        size_bytes=row.size_bytes,
        checksum=row.checksum,
        created_at=datetime.fromisoformat(row.created_at),
    )
