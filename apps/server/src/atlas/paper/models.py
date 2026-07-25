from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atlas.content.models import ResourceRecord
from atlas.workflows.models import WorkflowInvocationRecord

_RESOURCE_ID_PATTERN = r"^res_[A-Za-z0-9._-]{8,120}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PaperAcceptRequest(StrictModel):
    resource_id: str = Field(pattern=_RESOURCE_ID_PATTERN)

    @field_validator("resource_id")
    @classmethod
    def strip_resource_id(cls, value: str) -> str:
        return value.strip()


class PaperAcceptResponse(StrictModel):
    invocation: WorkflowInvocationRecord | None = None
    reused: bool
    fulltext_resource: ResourceRecord | None = None
