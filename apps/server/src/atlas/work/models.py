"""Work execution domain models.

Project, Run, Event, and ArtifactRef types for Milestone 2.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from atlas.content.models import ResourceCreate, SourceUpdate

MAX_INLINE_ARTIFACT_BYTES = 8 * 1024 * 1024

RunStatus = Literal["blocked", "pending", "claimed", "completed", "failed", "cancelled"]

AttemptStatus = Literal["active", "accepted", "failed", "superseded", "cancelled"]

EXECUTION_CONTRACT_METADATA_KEY = "_atlas_execution_contract"


class WorkflowRef(BaseModel):
    """Immutable identity of the workflow that produced a run."""

    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    digest: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("name", "version", "digest")
    @classmethod
    def normalize_fields(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("workflow fields cannot be empty")
        return normalized


class ExecutionRequirements(BaseModel):
    """Placement requirements, deliberately separate from business workflow names."""

    node_ids: list[str] = Field(default_factory=list, max_length=32)
    executors: list[str] = Field(default_factory=list, max_length=32)
    node_labels: list[str] = Field(default_factory=list, max_length=64)
    grants: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("node_ids", "executors", "node_labels", "grants")
    @classmethod
    def normalize_lists(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for item in value:
            stripped = item.strip()
            if stripped and stripped not in normalized:
                normalized.append(stripped)
        return normalized


class SchedulingProfile(BaseModel):
    """Server-derived placement facts for a registered runner or legacy agent."""

    identity_id: str
    legacy_capabilities: list[str] = Field(default_factory=list)
    is_runner: bool = False
    node_id: str | None = None
    executors: list[str] = Field(default_factory=list)
    node_labels: list[str] = Field(default_factory=list)
    available_grants: list[str] = Field(default_factory=list)



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
    run_id: str | None = Field(default=None, min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=128)
    job_name: str = Field(min_length=1, max_length=128)
    capabilities_required: list[str] = Field(default_factory=list, max_length=32)
    input: dict[str, Any] = Field(default_factory=dict)
    priority: int = Field(default=0, ge=-100, le=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    metadata: dict[str, Any] = Field(default_factory=dict)
    workflow: WorkflowRef | None = None
    step_name: str | None = Field(default=None, min_length=1, max_length=128)
    requirements: ExecutionRequirements = Field(default_factory=ExecutionRequirements)
    workflow_invocation_id: str | None = Field(default=None, min_length=1, max_length=128)
    depends_on_run_ids: list[str] = Field(default_factory=list, max_length=32)
    initial_status: Literal["blocked", "pending"] = "pending"

    @field_validator("project_id", "job_name", "run_id", "workflow_invocation_id")
    @classmethod
    def strip_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be empty")
        return normalized

    @field_validator("capabilities_required", "depends_on_run_ids")
    @classmethod
    def normalize_capabilities(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        for c in value:
            stripped = c.strip()
            if stripped and stripped not in normalized:
                normalized.append(stripped)
        return normalized

    @model_validator(mode="after")
    def reserve_execution_metadata_key(self) -> RunCreate:
        if EXECUTION_CONTRACT_METADATA_KEY in self.metadata:
            raise ValueError(f"metadata key {EXECUTION_CONTRACT_METADATA_KEY} is reserved")
        if self.workflow is not None and self.step_name is None:
            self.step_name = self.job_name
        if self.depends_on_run_ids and self.initial_status != "blocked":
            raise ValueError("dependent workflow runs must start blocked")
        return self


class ArtifactRefCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    uri: str = Field(min_length=1, max_length=4096)
    content_type: str | None = Field(default=None, max_length=128)
    size_bytes: int | None = Field(default=None, ge=0)
    checksum: str | None = Field(default=None, max_length=128)
    content: str | None = Field(default=None, max_length=MAX_INLINE_ARTIFACT_BYTES)

    @model_validator(mode="after")
    def validate_inline_content(self) -> ArtifactRefCreate:
        if self.content is None:
            return self
        encoded = self.content.encode()
        if len(encoded) > MAX_INLINE_ARTIFACT_BYTES:
            raise ValueError("inline artifact content exceeds 8 MiB")
        if self.size_bytes is not None and self.size_bytes != len(encoded):
            raise ValueError("inline artifact size does not match size_bytes")
        digest = f"sha256:{hashlib.sha256(encoded).hexdigest()}"
        if self.checksum is not None and self.checksum != digest:
            raise ValueError("inline artifact content does not match checksum")
        return self


class ArtifactContentUpsert(BaseModel):
    content: str = Field(max_length=MAX_INLINE_ARTIFACT_BYTES)

    @field_validator("content")
    @classmethod
    def bound_encoded_content(cls, value: str) -> str:
        if len(value.encode()) > MAX_INLINE_ARTIFACT_BYTES:
            raise ValueError("artifact content exceeds 8 MiB")
        return value


class ArtifactContentRecord(BaseModel):
    artifact_id: str
    content: str
    content_type: str | None = None
    size_bytes: int
    checksum: str


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
    model_config = ConfigDict(extra="forbid")

    attempt_id: str = Field(min_length=1, max_length=128)
    claim_token: str = Field(min_length=1, max_length=256)
    agent_id: str = Field(min_length=1, max_length=128)
    output: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRefCreate] = Field(default_factory=list, max_length=100)
    source_updates: list[SourceUpdate] = Field(default_factory=list, max_length=100)
    resources: list[ResourceCreate] = Field(default_factory=list, max_length=100)

    @field_validator("agent_id", "attempt_id", "claim_token")
    @classmethod
    def strip_fields(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def artifact_names_are_unique(self) -> RunComplete:
        names = [artifact.name for artifact in self.artifacts]
        if len(names) != len(set(names)):
            raise ValueError("artifact names must be unique within one completion")
        resource_ids = [resource.resource_id for resource in self.resources]
        if len(resource_ids) != len(set(resource_ids)):
            raise ValueError("resource IDs must be unique within one completion")
        return self


class HeartbeatCreate(BaseModel):
    attempt_id: str = Field(min_length=1, max_length=128)
    claim_token: str = Field(min_length=1, max_length=256)

    @field_validator("attempt_id", "claim_token")
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
    workflow: WorkflowRef | None = None
    step_name: str | None = None
    requirements: ExecutionRequirements = Field(default_factory=ExecutionRequirements)
    workflow_invocation_id: str | None = None
    depends_on_run_ids: list[str] = Field(default_factory=list)
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
