from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

MessageStatus = Literal["pending", "claimed", "acknowledged"]


class MessageCreate(BaseModel):
    from_agent_id: str = Field(min_length=1, max_length=128)
    to_agent_id: str = Field(min_length=1, max_length=128)
    kind: str = Field(default="prompt", min_length=1, max_length=64)
    body: str = Field(min_length=1, max_length=20_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("from_agent_id", "to_agent_id", "kind", "body")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be empty")
        return normalized


class MessageClaim(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)

    @field_validator("agent_id")
    @classmethod
    def strip_agent_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("agent_id cannot be empty")
        return normalized


class MessageAck(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    result: str | None = Field(default=None, max_length=20_000)

    @field_validator("agent_id")
    @classmethod
    def strip_agent_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("agent_id cannot be empty")
        return normalized

    @field_validator("result")
    @classmethod
    def strip_result(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class MessageRecord(BaseModel):
    message_id: str
    from_agent_id: str
    to_agent_id: str
    kind: str
    body: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: MessageStatus
    created_at: datetime
    claimed_at: datetime | None = None
    claimed_by: str | None = None
    acknowledged_at: datetime | None = None
    result: str | None = None
