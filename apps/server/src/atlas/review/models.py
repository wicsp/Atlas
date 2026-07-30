from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atlas.content.models import CommentRecord, KnowledgeRefRecord, ResourceRecord
from atlas.work.models import RunRecord

_RESOURCE_ID_PATTERN = r"^res_[A-Za-z0-9._-]{8,120}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceActionRequest(StrictModel):
    resource_id: str = Field(pattern=_RESOURCE_ID_PATTERN)

    @field_validator("resource_id")
    @classmethod
    def strip_resource_id(cls, value: str) -> str:
        return value.strip()


class ComparisonRequestResponse(StrictModel):
    run: RunRecord
    reused: bool


class CommentCompleteRequest(StrictModel):
    resource_id: str = Field(pattern=_RESOURCE_ID_PATTERN)
    body_markdown: str = Field(min_length=1, max_length=256 * 1024)
    content_hash: str | None = Field(
        default=None,
        pattern=r"^sha256:[0-9a-f]{64}$",
    )

    @field_validator("resource_id")
    @classmethod
    def strip_resource_id(cls, value: str) -> str:
        return value.strip()


class CommentCompleteResponse(StrictModel):
    resource: ResourceRecord
    knowledge_ref: KnowledgeRefRecord
    comment: CommentRecord


class ResourceIgnoreResponse(StrictModel):
    resource: ResourceRecord
    evicted_resource_ids: list[str]


class ResourceIgnoreRequest(StrictModel):
    resource_id: str = Field(pattern=_RESOURCE_ID_PATTERN)

    @field_validator("resource_id")
    @classmethod
    def strip_resource_id(cls, value: str) -> str:
        return value.strip()
