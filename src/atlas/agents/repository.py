from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from atlas.db.base import Base

from .models import AgentRecord, AgentRegistration


class AgentRow(Base):
    __tablename__ = "agents"

    agent_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    capabilities_json: Mapped[str] = mapped_column(Text, default="[]")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    registered_at: Mapped[str] = mapped_column(String(64))
    last_seen_at: Mapped[str] = mapped_column(String(64))


class AgentRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert(self, registration: AgentRegistration, now: datetime) -> AgentRecord:
        with self._session_factory() as session:
            row = session.get(AgentRow, registration.agent_id)
            if row is None:
                row = AgentRow(
                    agent_id=registration.agent_id,
                    name=registration.name,
                    capabilities_json=_dump_json(registration.capabilities),
                    metadata_json=_dump_json(registration.metadata),
                    registered_at=now.isoformat(),
                    last_seen_at=now.isoformat(),
                )
                session.add(row)
            else:
                row.name = registration.name
                row.capabilities_json = _dump_json(registration.capabilities)
                row.metadata_json = _dump_json(registration.metadata)
                row.last_seen_at = now.isoformat()
            session.commit()
            return _to_record(row, online=True)

    def touch(self, agent_id: str, now: datetime) -> AgentRecord:
        with self._session_factory() as session:
            row = session.get(AgentRow, agent_id)
            if row is None:
                raise KeyError(agent_id)
            row.last_seen_at = now.isoformat()
            session.commit()
            return _to_record(row, online=True)

    def list(self) -> list[AgentRecord]:
        with self._session_factory() as session:
            rows = session.scalars(select(AgentRow).order_by(AgentRow.agent_id)).all()
            return [_to_record(row, online=False) for row in rows]


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
        online=online,
    )
