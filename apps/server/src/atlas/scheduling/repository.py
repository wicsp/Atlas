from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from atlas.db.base import Base

from .models import FavoriteFanoutRecord, ScheduleRecord


class ScheduleRow(Base):
    __tablename__ = "schedules"

    schedule_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    workflow_name: Mapped[str] = mapped_column(String(128))
    workflow_version: Mapped[str] = mapped_column(String(64))
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    timezone: Mapped[str] = mapped_column(String(128))
    hour: Mapped[int] = mapped_column(Integer)
    minute: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_occurrence_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_invocation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64))
    updated_at: Mapped[str] = mapped_column(String(64))


class FavoriteFanoutRow(Base):
    __tablename__ = "favorite_scan_fanouts"

    fanout_key: Mapped[str] = mapped_column(String(256), primary_key=True)
    scan_run_id: Mapped[str] = mapped_column(String(128), index=True)
    bvid: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[str] = mapped_column(String(128))
    disposition: Mapped[str] = mapped_column(String(32))
    invocation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64))


class ScheduleRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ensure_daily_schedule(
        self,
        schedule_id: str,
        workflow_name: str,
        workflow_version: str,
        input: dict,
        timezone: str,
        hour: int,
        minute: int,
        now: datetime,
    ) -> ScheduleRecord:
        with self._session_factory() as session, session.begin():
            row = session.get(ScheduleRow, schedule_id)
            if row is None:
                row = ScheduleRow(
                    schedule_id=schedule_id,
                    workflow_name=workflow_name,
                    workflow_version=workflow_version,
                    input_json=json.dumps(input, ensure_ascii=False, sort_keys=True),
                    timezone=timezone,
                    hour=hour,
                    minute=minute,
                    enabled=True,
                    created_at=now.isoformat(),
                    updated_at=now.isoformat(),
                )
                session.add(row)
            return _schedule_record(row)

    def list_schedules(self) -> list[ScheduleRecord]:
        with self._session_factory() as session:
            rows = session.scalars(select(ScheduleRow).order_by(ScheduleRow.schedule_id)).all()
            return [_schedule_record(row) for row in rows]

    def mark_occurrence(
        self,
        schedule_id: str,
        occurrence_date: str,
        invocation_id: str,
        now: datetime,
    ) -> ScheduleRecord:
        with self._session_factory() as session, session.begin():
            row = session.get(ScheduleRow, schedule_id)
            if row is None:
                raise KeyError(schedule_id)
            row.last_occurrence_date = occurrence_date
            row.last_invocation_id = invocation_id
            row.updated_at = now.isoformat()
            return _schedule_record(row)

    def get_fanout(self, fanout_key: str) -> FavoriteFanoutRecord | None:
        with self._session_factory() as session:
            row = session.get(FavoriteFanoutRow, fanout_key)
            return _fanout_record(row) if row is not None else None

    def record_fanout(
        self,
        fanout_key: str,
        scan_run_id: str,
        bvid: str,
        source_id: str,
        disposition: str,
        invocation_id: str | None,
        now: datetime,
    ) -> FavoriteFanoutRecord:
        with self._session_factory() as session, session.begin():
            row = session.get(FavoriteFanoutRow, fanout_key)
            if row is None:
                row = FavoriteFanoutRow(
                    fanout_key=fanout_key,
                    scan_run_id=scan_run_id,
                    bvid=bvid,
                    source_id=source_id,
                    disposition=disposition,
                    invocation_id=invocation_id,
                    created_at=now.isoformat(),
                )
                session.add(row)
            return _fanout_record(row)


def _schedule_record(row: ScheduleRow) -> ScheduleRecord:
    return ScheduleRecord(
        schedule_id=row.schedule_id,
        workflow_name=row.workflow_name,
        workflow_version=row.workflow_version,
        input=json.loads(row.input_json),
        timezone=row.timezone,
        hour=row.hour,
        minute=row.minute,
        enabled=row.enabled,
        last_occurrence_date=row.last_occurrence_date,
        last_invocation_id=row.last_invocation_id,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


def _fanout_record(row: FavoriteFanoutRow) -> FavoriteFanoutRecord:
    return FavoriteFanoutRecord(
        fanout_key=row.fanout_key,
        scan_run_id=row.scan_run_id,
        bvid=row.bvid,
        source_id=row.source_id,
        disposition=row.disposition,  # type: ignore[arg-type]
        invocation_id=row.invocation_id,
        created_at=datetime.fromisoformat(row.created_at),
    )
