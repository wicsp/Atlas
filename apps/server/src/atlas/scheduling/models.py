from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScheduleRecord(BaseModel):
    schedule_id: str
    workflow_name: str
    workflow_version: str
    input: dict[str, Any]
    timezone: str
    hour: int
    minute: int
    enabled: bool
    last_occurrence_date: str | None = None
    last_invocation_id: str | None = None
    created_at: datetime
    updated_at: datetime


class FavoriteScanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bvid: str = Field(pattern=r"^BV[A-Za-z0-9]{10}$")
    aid: int = Field(gt=0)
    title: str | None = Field(default=None, max_length=1000)
    owner: str | None = Field(default=None, max_length=500)
    duration_seconds: int | None = Field(default=None, ge=0)

    @field_validator("title", "owner")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class FavoriteFanoutRecord(BaseModel):
    fanout_key: str
    scan_run_id: str
    bvid: str
    source_id: str
    disposition: Literal["invoked", "reused"]
    invocation_id: str | None = None
    created_at: datetime
