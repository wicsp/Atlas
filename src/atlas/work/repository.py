from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from atlas.db.base import Base

from .models import (
    ArtifactRef,
    ArtifactRefCreate,
    EventRecord,
    ProjectCreate,
    ProjectRecord,
    RunCreate,
    RunRecord,
    RunStatus,
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


class WorkRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # ── Projects ──────────────────────────────────────────────

    def create_project(self, payload: ProjectCreate, now: datetime) -> ProjectRecord:
        with self._session_factory() as session:
            row = ProjectRow(
                project_id=payload.project_id,
                name=payload.name,
                description=payload.description,
                created_at=now.isoformat(),
            )
            session.add(row)
            session.commit()
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
            row = RunRow(
                run_id=f"run_{uuid.uuid4().hex}",
                project_id=payload.project_id,
                job_name=payload.job_name,
                capabilities_json=_dump_json(payload.capabilities_required),
                input_json=_dump_json(payload.input),
                status="pending",
                attempt_number=0,
                max_attempts=payload.max_attempts,
                priority=payload.priority,
                metadata_json=_dump_json(payload.metadata),
                created_at=now.isoformat(),
            )
            session.add(row)
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


    def claim_run(
        self,
        run_id: str,
        agent_id: str,
        lease_expires_at: datetime,
        now: datetime,
    ) -> RunRecord:
        with self._session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.status != "pending":
                raise ValueError(f"Run {run_id} is not pending (status={row.status})")
            if row.attempt_number >= row.max_attempts:
                raise ValueError(f"Run {run_id} has exhausted all attempts")
            row.status = "claimed"
            row.agent_id = agent_id
            row.lease_expires_at = lease_expires_at.isoformat()
            row.attempt_number += 1
            row.started_at = now.isoformat()
            session.commit()
            return _to_run(row)

    def heartbeat_run(
        self,
        run_id: str,
        agent_id: str,
        lease_expires_at: datetime,
    ) -> RunRecord:
        with self._session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.status != "claimed":
                raise ValueError(f"Run {run_id} is not claimed")
            if row.agent_id != agent_id:
                raise PermissionError(f"Run {run_id} is claimed by {row.agent_id}")
            row.lease_expires_at = lease_expires_at.isoformat()
            session.commit()
            return _to_run(row)

    def complete_run(
        self,
        run_id: str,
        agent_id: str,
        output: dict[str, Any],
        artifacts: list[ArtifactRefCreate],
        now: datetime,
    ) -> RunRecord:
        with self._session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.status not in ("pending", "claimed"):
                raise ValueError(f"Run {run_id} is already terminal (status={row.status})")
            if row.agent_id is not None and row.agent_id != agent_id:
                raise PermissionError(f"Run {run_id} is claimed by {row.agent_id}")
            row.status = "completed"
            row.agent_id = agent_id
            row.output_json = _dump_json(output)
            row.completed_at = now.isoformat()
            row.lease_expires_at = None

            for art in artifacts:
                session.add(
                    ArtifactRow(
                        artifact_id=f"art_{uuid.uuid4().hex}",
                        run_id=run_id,
                        name=art.name,
                        uri=art.uri,
                        content_type=art.content_type,
                        size_bytes=art.size_bytes,
                        checksum=art.checksum,
                        created_at=now.isoformat(),
                    )
                )

            session.commit()
            return _to_run(row)

    def fail_run(
        self,
        run_id: str,
        agent_id: str,
        error_message: str | None,
        now: datetime,
    ) -> RunRecord:
        with self._session_factory() as session:
            row = session.get(RunRow, run_id)
            if row is None:
                raise KeyError(run_id)
            if row.status not in ("pending", "claimed"):
                raise ValueError(f"Run {run_id} is already terminal (status={row.status})")
            if row.agent_id is not None and row.agent_id != agent_id:
                raise PermissionError(f"Run {run_id} is claimed by {row.agent_id}")
            row.status = "failed"
            row.agent_id = agent_id
            row.error_message = error_message
            row.completed_at = now.isoformat()
            row.lease_expires_at = None
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


# ── Row → Record converters ───────────────────────────────


def _to_project(row: ProjectRow) -> ProjectRecord:
    return ProjectRecord(
        project_id=row.project_id,
        name=row.name,
        description=row.description,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _to_run(row: RunRow) -> RunRecord:
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
        metadata=_load_json(row.metadata_json, {}),
        error_message=row.error_message,
        created_at=datetime.fromisoformat(row.created_at),
        started_at=_parse_datetime(row.started_at),
        completed_at=_parse_datetime(row.completed_at),
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
