"""Work execution domain models.

Project, Run, Event, and ArtifactRef types for Milestone 2.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

RunStatus = Literal["pending", "claimed", "completed", "failed", "cancelled"]

AttemptStatus = Literal["active", "accepted", "failed", "superseded", "cancelled"]



class ProjectCreate(BaseModel):
    project_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=10_000)

    @field_validator("project_id", "name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be empty")
        return normalized


class ProjectRecord(BaseModel):
    project_id: str
    name: str
    description: str | None = None
    created_at: datetime


class RunCreate(BaseModel):
    project_id: str = Field(min_length=1, max_length=128)
    job_name: str = Field(min_length=1, max_length=128)
    capabilities_required: list[str] = Field(default_factory=list, max_length=32)
    input: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=-100, le=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("project_id", "job_name")
    @classmethod
    def strip_required(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be empty")
        return normalized

    @field_validator("capabilities_required")
    @classmethod
    def normalize_capabilities(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for c in value:
            stripped = c.strip()
            if stripped and stripped not in normalized:
                normalized.append(stripped)
        return normalized


class ArtifactRefCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    uri: str = Field(min_length=1, max_length=4096)
    content_type: str | None = Field(default=None, max_length=128)
    size_bytes: int | None = Field(default=None, ge=0)
    checksum: str | None = Field(default=None, max_length=128)


class ExecutionAttemptRecord(BaseModel):
    attempt_id: str
    run_id: str
    attempt_number: int
    agent_id: str
    status: AttemptStatus
    lease_expires_at: datetime | None = None
    created_at: datetime
    finished_at: datetime | None = None
    result_digest: str | None = None

class ArtifactRef(BaseModel):
    artifact_id: str
    run_id: str
    name: str
    uri: str
    content_type: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    created_at: datetime


class RunComplete(BaseModel):
    attempt_id: str = Field(min_length=1, max_length=128)
    claim_token: str = Field(min_length=1, max_length=256)
    agent_id: str = Field(min_length=1, max_length=128)
    output: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRefCreate] = Field(default_factory=list, max_length=100)

    @field_validator("agent_id", "attempt_id", "claim_token")
    @classmethod
    def strip_fields(cls, value: str) -> str:
        return value.strip()


class RunFail(BaseModel):
    attempt_id: str = Field(min_length=1, max_length=128)
    claim_token: str = Field(min_length=1, max_length=256)
    agent_id: str = Field(min_length=1, max_length=128)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=10_000)
    retryable: bool = False

    @field_validator("agent_id", "attempt_id", "claim_token")
    @classmethod
    def strip_fields(cls, value: str) -> str:
        return value.strip()


class ReconcileRequest(BaseModel):
    attempt_id: str = Field(min_length=1, max_length=128)
    claim_token: str = Field(min_length=1, max_length=256)
    result_digest: str = Field(min_length=1, max_length=128)
    bounded_output: dict[str, Any] = Field(default_factory=dict)
    artifact_refs: list[ArtifactRefCreate] = Field(default_factory=list, max_length=100)
    terminal_intent: Literal["complete", "fail"]
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=10_000)

    @field_validator("attempt_id", "claim_token", "result_digest", "terminal_intent")
    @classmethod
    def strip_fields(cls, value: str) -> str:
        return value.strip()


class RunCancel(BaseModel):
    agent_id: str | None = Field(default=None, max_length=128)


class RunRecord(BaseModel):
    run_id: str
    project_id: str
    job_name: str
    capabilities_required: list[str] = Field(default_factory=list)
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    status: RunStatus
    agent_id: str | None = None
    lease_expires_at: datetime | None = None
    attempt_number: int
    max_attempts: int
    priority: int
    metadata: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None


class EventRecord(BaseModel):
    event_id: str
    run_id: str
    agent_id: str | None = None
    event_type: str
    body: str
    created_at: datetime


class ClaimRunResponse(RunRecord):
    attempt_id: str
    claim_token: str
