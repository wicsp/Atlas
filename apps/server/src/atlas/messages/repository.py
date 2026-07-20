from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from atlas.db.base import Base

from .models import MessageCreate, MessageRecord


class MessageRow(Base):
    __tablename__ = "messages"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    from_agent_id: Mapped[str] = mapped_column(String(128), index=True)
    to_agent_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    claimed_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    acknowledged_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)


class MessageRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create(self, payload: MessageCreate, now: datetime) -> MessageRecord:
        with self._session_factory() as session:
            row = MessageRow(
                message_id=f"msg_{uuid.uuid4().hex}",
                from_agent_id=payload.from_agent_id,
                to_agent_id=payload.to_agent_id,
                kind=payload.kind,
                body=payload.body,
                metadata_json=_dump_json(payload.metadata),
                status="pending",
                created_at=now.isoformat(),
            )
            session.add(row)
            session.commit()
            return _to_record(row)

    def get(self, message_id: str) -> MessageRecord:
        with self._session_factory() as session:
            row = session.get(MessageRow, message_id)
            if row is None:
                raise KeyError(message_id)
            return _to_record(row)

    def list_pending_for_agent(self, agent_id: str, limit: int = 50) -> list[MessageRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(MessageRow)
                .where(MessageRow.to_agent_id == agent_id)
                .where(MessageRow.status == "pending")
                .order_by(MessageRow.created_at)
                .limit(limit)
            ).all()
            return [_to_record(row) for row in rows]

    def claim(self, message_id: str, agent_id: str, now: datetime) -> MessageRecord:
        with self._session_factory() as session:
            row = session.get(MessageRow, message_id)
            if row is None:
                raise KeyError(message_id)
            row.status = "claimed"
            row.claimed_by = agent_id
            row.claimed_at = now.isoformat()
            session.commit()
            return _to_record(row)

    def acknowledge(self, message_id: str, result: str | None, now: datetime) -> MessageRecord:
        with self._session_factory() as session:
            row = session.get(MessageRow, message_id)
            if row is None:
                raise KeyError(message_id)
            row.status = "acknowledged"
            row.result = result
            row.acknowledged_at = now.isoformat()
            session.commit()
            return _to_record(row)


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _to_record(row: MessageRow) -> MessageRecord:
    return MessageRecord(
        message_id=row.message_id,
        from_agent_id=row.from_agent_id,
        to_agent_id=row.to_agent_id,
        kind=row.kind,
        body=row.body,
        metadata=_load_json(row.metadata_json, {}),
        status=row.status,  # type: ignore[arg-type]
        created_at=datetime.fromisoformat(row.created_at),
        claimed_at=_parse_datetime(row.claimed_at),
        claimed_by=row.claimed_by,
        acknowledged_at=_parse_datetime(row.acknowledged_at),
        result=row.result,
    )
