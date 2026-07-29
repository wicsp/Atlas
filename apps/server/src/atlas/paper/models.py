from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

from atlas.content.models import ResourceRecord, SourceRecord
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


def _normalize_labels(values: list[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        label = value.strip()
        if label and label.casefold() not in {item.casefold() for item in normalized}:
            normalized.append(label)
    return normalized


class PaperLibraryUpdate(StrictModel):
    tags: list[str] = Field(default_factory=list, max_length=50)
    categories: list[str] = Field(default_factory=list, max_length=20)
    citation_source_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("tags", "categories")
    @classmethod
    def normalize_labels(cls, values: list[str]) -> list[str]:
        normalized = _normalize_labels(values)
        if any(len(value) > 64 for value in normalized):
            raise ValueError("paper labels cannot exceed 64 characters")
        return normalized

    @field_validator("citation_source_ids")
    @classmethod
    def normalize_citations(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if any(not value.startswith("src_") for value in normalized):
            raise ValueError("citation_source_ids must contain Source IDs")
        return normalized


class PaperLibraryRecord(StrictModel):
    source: SourceRecord
    tags: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    citation_source_ids: list[str] = Field(default_factory=list)
    summary_resource_ids: list[str] = Field(default_factory=list)
    summary_excerpt: str | None = None


class PaperComparisonRequest(StrictModel):
    source_ids: list[str] = Field(min_length=2, max_length=8)

    @field_validator("source_ids")
    @classmethod
    def normalize_source_ids(cls, values: list[str]) -> list[str]:
        normalized = list(dict.fromkeys(value.strip() for value in values if value.strip()))
        if not 2 <= len(normalized) <= 8:
            raise ValueError("paper comparison requires 2-8 unique Source IDs")
        if any(not value.startswith("src_") for value in normalized):
            raise ValueError("paper comparison requires Source IDs")
        return normalized


class PaperCitationEdge(StrictModel):
    citing_source_id: str
    cited_source_id: str


class PaperComparisonResponse(StrictModel):
    papers: list[PaperLibraryRecord]
    shared_tags: list[str] = Field(default_factory=list)
    shared_categories: list[str] = Field(default_factory=list)
    citation_edges: list[PaperCitationEdge] = Field(default_factory=list)
