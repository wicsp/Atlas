from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from atlas.db.base import Base

from .models import (
    WorkflowDefinitionCreate,
    WorkflowDefinitionRecord,
    WorkflowInvocationCreate,
    WorkflowInvocationRecord,
)


class WorkflowDefinitionRow(Base):
    __tablename__ = "workflow_definitions"

    workflow_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    version: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(128))
    definition_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(64))


class WorkflowInvocationRow(Base):
    __tablename__ = "workflow_invocations"

    invocation_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workflow_name: Mapped[str] = mapped_column(String(128), index=True)
    workflow_version: Mapped[str] = mapped_column(String(64))
    workflow_digest: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    input_json: Mapped[str] = mapped_column(Text)
    step_runs_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(64))
    completed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)


class WorkflowRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def register_definition(
        self,
        definition: WorkflowDefinitionCreate,
        digest: str,
        now: datetime,
    ) -> WorkflowDefinitionRecord:
        key = _workflow_key(definition.name, definition.version)
        encoded = definition.model_dump_json()
        with self._session_factory() as session:
            row = session.get(WorkflowDefinitionRow, key)
            if row is not None:
                if row.digest != digest:
                    raise ValueError(
                        f"workflow {definition.name}@{definition.version} is immutable"
                    )
                return _definition_record(row)
            row = WorkflowDefinitionRow(
                workflow_key=key,
                name=definition.name,
                version=definition.version,
                digest=digest,
                definition_json=encoded,
                created_at=now.isoformat(),
            )
            session.add(row)
            session.commit()
            return _definition_record(row)

    def get_definition(self, name: str, version: str) -> WorkflowDefinitionRecord:
        with self._session_factory() as session:
            row = session.get(WorkflowDefinitionRow, _workflow_key(name, version))
            if row is None:
                raise KeyError(f"{name}@{version}")
            return _definition_record(row)

    def list_definitions(self) -> list[WorkflowDefinitionRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(WorkflowDefinitionRow).order_by(
                    WorkflowDefinitionRow.name, WorkflowDefinitionRow.version
                )
            ).all()
            return [_definition_record(row) for row in rows]

    def create_invocation_with_id(
        self,
        invocation_id: str,
        payload: WorkflowInvocationCreate,
        definition: WorkflowDefinitionRecord,
        step_runs: dict[str, str],
        now: datetime,
    ) -> WorkflowInvocationRecord:
        row = WorkflowInvocationRow(
            invocation_id=invocation_id,
            workflow_name=payload.workflow_name,
            workflow_version=payload.workflow_version,
            workflow_digest=definition.digest,
            status="running",
            input_json=json.dumps(payload.input, ensure_ascii=False, sort_keys=True),
            step_runs_json=json.dumps(step_runs, sort_keys=True),
            created_at=now.isoformat(),
        )
        with self._session_factory() as session:
            session.add(row)
            session.commit()
            return _invocation_record(row)

    def get_invocation(self, invocation_id: str) -> WorkflowInvocationRecord:
        with self._session_factory() as session:
            row = session.get(WorkflowInvocationRow, invocation_id)
            if row is None:
                raise KeyError(invocation_id)
            return _invocation_record(row)

    def find_invocation(self, invocation_id: str) -> WorkflowInvocationRecord | None:
        with self._session_factory() as session:
            row = session.get(WorkflowInvocationRow, invocation_id)
            return _invocation_record(row) if row is not None else None

    def list_invocations(
        self,
        status: str | None = None,
    ) -> list[WorkflowInvocationRecord]:
        with self._session_factory() as session:
            statement = select(WorkflowInvocationRow).order_by(
                WorkflowInvocationRow.created_at
            )
            if status is not None:
                statement = statement.where(WorkflowInvocationRow.status == status)
            return [
                _invocation_record(row)
                for row in session.scalars(statement).all()
            ]

    def set_invocation_status(
        self,
        invocation_id: str,
        status: str,
        now: datetime,
    ) -> WorkflowInvocationRecord:
        with self._session_factory() as session:
            row = session.get(WorkflowInvocationRow, invocation_id)
            if row is None:
                raise KeyError(invocation_id)
            row.status = status
            if status in {"completed", "failed", "cancelled"}:
                row.completed_at = now.isoformat()
            session.commit()
            return _invocation_record(row)


def _workflow_key(name: str, version: str) -> str:
    return f"{name}@{version}"


def _definition_record(row: WorkflowDefinitionRow) -> WorkflowDefinitionRecord:
    definition = WorkflowDefinitionCreate.model_validate_json(row.definition_json)
    return WorkflowDefinitionRecord(
        **definition.model_dump(),
        digest=row.digest,
        created_at=datetime.fromisoformat(row.created_at),
    )


def _invocation_record(row: WorkflowInvocationRow) -> WorkflowInvocationRecord:
    return WorkflowInvocationRecord(
        invocation_id=row.invocation_id,
        workflow_name=row.workflow_name,
        workflow_version=row.workflow_version,
        workflow_digest=row.workflow_digest,
        status=row.status,  # type: ignore[arg-type]
        input=json.loads(row.input_json),
        step_runs=json.loads(row.step_runs_json),
        created_at=datetime.fromisoformat(row.created_at),
        completed_at=datetime.fromisoformat(row.completed_at) if row.completed_at else None,
    )
