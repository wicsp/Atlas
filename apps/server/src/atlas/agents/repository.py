from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from atlas.db.base import Base
from atlas.security import generate_scoped_token, hash_token

from .models import AgentRecord, AgentRegistration


class AgentRow(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    scoped_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    registered_at: Mapped[str] = mapped_column(String(64))
    last_seen_at: Mapped[str] = mapped_column(String(64))


class RunnerArchiveRow(Base):
    __tablename__ = "runner_archives"

    runner_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    reason: Mapped[str] = mapped_column(String(128))
    archived_at: Mapped[str] = mapped_column(String(64))


class AgentRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert(
        self, registration: AgentRegistration, now: datetime
    ) -> tuple[AgentRecord, str | None]:
        with self._session_factory() as session:
            row = session.get(AgentRow, registration.agent_id)
            scoped_token: str | None = None
            if row is None:
                # New agent: generate a scoped credential.
                scoped_token = generate_scoped_token()
                token_hash = hash_token(scoped_token)
                row = AgentRow(
                    agent_id=registration.agent_id,
                    name=registration.name,
                    capabilities_json=_dump_json(registration.capabilities),
                    metadata_json=_dump_json(registration.metadata),
                    scoped_token_hash=token_hash,
                    registered_at=now.isoformat(),
                    last_seen_at=now.isoformat(),
                )
                session.add(row)
            else:
                # Re-registration: always rotate the scoped credential.
                # Prevents response-loss holes where a new agent gets token=.
                scoped_token = generate_scoped_token()
                token_hash = hash_token(scoped_token)
                row.name = registration.name
                row.capabilities_json = _dump_json(registration.capabilities)
                row.metadata_json = _dump_json(registration.metadata)
                row.scoped_token_hash = token_hash
                row.last_seen_at = now.isoformat()
            if registration.metadata.get("identity_kind") == "runner":
                archived = session.get(RunnerArchiveRow, registration.agent_id)
                if archived is not None:
                    session.delete(archived)
            session.commit()
            return _to_record(row, online=True), scoped_token

    def touch(self, agent_id: str, now: datetime) -> AgentRecord:
        with self._session_factory() as session:
            row = session.get(AgentRow, agent_id)
            if row is None:
                raise KeyError(agent_id)
            row.last_seen_at = now.isoformat()
            session.commit()
            return _to_record(row, online=True)

    def find_by_scoped_token(self, token: str) -> AgentRecord | None:
        token_hash = hash_token(token)
        with self._session_factory() as session:
            row = session.scalars(
                select(AgentRow).where(AgentRow.scoped_token_hash == token_hash)
            ).first()
            if row is None:
                # Fall back: check shared token for migration compatibility.
                return None
            return _to_record(row, online=False)

    def list(self) -> list[AgentRecord]:
        with self._session_factory() as session:
            rows = session.scalars(select(AgentRow).order_by(AgentRow.agent_id)).all()
            return [_to_record(row, online=False) for row in rows]

    def list_unarchived_runners(self) -> list[AgentRecord]:
        with self._session_factory() as session:
            archived_ids = set(session.scalars(select(RunnerArchiveRow.runner_id)).all())
            rows = session.scalars(select(AgentRow).order_by(AgentRow.agent_id)).all()
            return [
                _to_record(row, online=False)
                for row in rows
                if row.agent_id not in archived_ids
                and _load_json(row.metadata_json, {}).get("identity_kind") == "runner"
            ]

    def archive_stale_lumio_runners(self, now: datetime, older_than: timedelta) -> int:
        archived_count = 0
        with self._session_factory() as session, session.begin():
            archived_ids = set(session.scalars(select(RunnerArchiveRow.runner_id)).all())
            rows = session.scalars(select(AgentRow)).all()
            for row in rows:
                if row.agent_id in archived_ids:
                    continue
                metadata = _load_json(row.metadata_json, {})
                if (
                    metadata.get("identity_kind") != "runner"
                    or metadata.get("distribution") != "lumio"
                ):
                    continue
                last_seen_at = datetime.fromisoformat(row.last_seen_at)
                if now - last_seen_at <= older_than:
                    continue
                session.add(
                    RunnerArchiveRow(
                        runner_id=row.agent_id,
                        reason="stale-ephemeral-lumio-session",
                        archived_at=now.isoformat(),
                    )
                )
                archived_count += 1
        return archived_count


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _to_record(row: AgentRow, online: bool) -> AgentRecord:
    return AgentRecord(
        agent_id=row.agent_id,
        name=row.name,
        capabilities=_load_json(row.capabilities_json, []),
        metadata=_load_json(row.metadata_json, {}),
        registered_at=datetime.fromisoformat(row.registered_at),
        last_seen_at=datetime.fromisoformat(row.last_seen_at),
        scoped_token_hash=row.scoped_token_hash,
        online=online,
    )
