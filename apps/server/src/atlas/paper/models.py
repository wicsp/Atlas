from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atlas.content.models import ResourceRecord
from atlas.workflows.models import WorkflowInvocationRecord

_ID_PATTERN = r"^[a-z]{3}_[A-Za-z0-9._-]{8,120}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperIngestRequest(StrictModel):
    source_id: str = Field(pattern=_ID_PATTERN)

    @field_validator("source_id")
    @classmethod
    def strip_source_id(cls, value: str) -> str:
        return value.strip()


class PaperIngestResponse(StrictModel):
    invocation: WorkflowInvocationRecord | None = None
    reused: bool
    preview_resource: ResourceRecord | None = None


class PaperFulltextRequest(StrictModel):
    source_id: str = Field(pattern=_ID_PATTERN)
    preview_resource_id: str = Field(pattern=_ID_PATTERN)

    @field_validator("source_id", "preview_resource_id")
    @classmethod
    def strip_ids(cls, value: str) -> str:
        return value.strip()


class PaperFulltextResponse(StrictModel):
    invocation: WorkflowInvocationRecord | None = None
    reused: bool
    fulltext_resource: ResourceRecord | None = None
