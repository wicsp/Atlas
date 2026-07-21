from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

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


class NodeDescriptor(BaseModel):
    """Scheduling facts about a host, separate from any agent session."""

    node_id: str = Field(min_length=1, max_length=128)
    os: str | None = Field(default=None, max_length=64)
    arch: str | None = Field(default=None, max_length=64)
    labels: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("node_id")
    @classmethod
    def normalize_node_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("node_id cannot be empty")
        return normalized

    @field_validator("labels")
    @classmethod
    def normalize_labels(cls, value: list[str]) -> list[str]:
        return _normalize_unique_strings(value)


class ExecutorDescriptor(BaseModel):
    """One runtime a runner can launch; this is not a business capability."""

    name: str = Field(min_length=1, max_length=128)
    kind: Literal["agent", "script", "process"]
    version: str | None = Field(default=None, max_length=128)

    @field_validator("name")
    @classmethod
    def normalize_executor_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("executor name cannot be empty")
        return normalized


class RunnerRegistration(BaseModel):
    """Register a node-local execution plane without assigning business skills to it."""

    runner_id: str = Field(min_length=1, max_length=128)
    name: str | None = Field(default=None, max_length=200)
    node: NodeDescriptor
    executors: list[ExecutorDescriptor] = Field(min_length=1, max_length=32)
    available_grants: list[str] = Field(default_factory=list, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    legacy_capabilities: list[str] = Field(default_factory=list, max_length=64)

    @field_validator("runner_id")
    @classmethod
    def normalize_runner_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("runner_id cannot be empty")
        return normalized

    @field_validator("available_grants", "legacy_capabilities")
    @classmethod
    def normalize_string_lists(cls, value: list[str]) -> list[str]:
        return _normalize_unique_strings(value)


class RunnerRecord(BaseModel):
    runner_id: str
    name: str | None = None
    node: NodeDescriptor
    executors: list[ExecutorDescriptor]
    available_grants: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    registered_at: datetime
    last_seen_at: datetime
    online: bool


class RunnerRegistrationResponse(BaseModel):
    runner_id: str
    scoped_token: str
    protocol_version: str = "atlas-runner-v1"


def _normalize_unique_strings(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        stripped = value.strip()
        if stripped and stripped not in normalized:
            normalized.append(stripped)
    return normalized
