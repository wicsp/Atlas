from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from atlas.work.models import ExecutionRequirements


class WorkflowStepDefinition(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    depends_on: list[str] = Field(default_factory=list, max_length=32)
    requirements: ExecutionRequirements = Field(default_factory=ExecutionRequirements)
    max_attempts: int = Field(default=3, ge=1, le=10)
    priority: int = Field(default=0, ge=-100, le=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()


class WorkflowDefinitionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=10_000)
    steps: list[WorkflowStepDefinition] = Field(min_length=1, max_length=64)

    @field_validator("name", "version", "project_id")
    @classmethod
    def normalize_fields(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def validate_graph(self) -> WorkflowDefinitionCreate:
        names = [step.name for step in self.steps]
        if len(names) != len(set(names)):
            raise ValueError("workflow step names must be unique")
        known: set[str] = set()
        for step in self.steps:
            missing = set(step.depends_on) - known
            if missing:
                raise ValueError(
                    f"step {step.name} depends on missing or later steps: {sorted(missing)}"
                )
            known.add(step.name)
        return self


class WorkflowDefinitionRecord(WorkflowDefinitionCreate):
    digest: str
    created_at: datetime


class WorkflowInvocationCreate(BaseModel):
    workflow_name: str = Field(min_length=1, max_length=128)
    workflow_version: str = Field(min_length=1, max_length=64)
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowInvocationRecord(BaseModel):
    invocation_id: str
    workflow_name: str
    workflow_version: str
    workflow_digest: str
    status: Literal["running", "completed", "failed", "cancelled"]
    input: dict[str, Any]
    step_runs: dict[str, str]
    created_at: datetime
    completed_at: datetime | None = None
