from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AgentRegistration(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=200)
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("agent_id")
    @classmethod
    def normalize_agent_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("agent_id cannot be empty")
        return normalized

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for capability in value:
            stripped = capability.strip()
            if stripped and stripped not in normalized:
                normalized.append(stripped)
        return normalized


class AgentRecord(BaseModel):
    agent_id: str
    name: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    registered_at: datetime
    last_seen_at: datetime
    scoped_token_hash: str | None = None
    online: bool


class AgentRegistrationResponse(BaseModel):
    agent_id: str
    scoped_token: str
    protocol_version: str = "atlas-agent-v3"
