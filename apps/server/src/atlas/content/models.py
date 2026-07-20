from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SourceKind = Literal["video", "paper", "webpage", "dataset", "code", "other"]
ResourceKind = Literal["transcript", "summary", "extraction", "comparison"]
ReviewStatus = Literal["pending", "reviewed", "dismissed"]
GeneratorMode = Literal["deterministic", "ai"]
CommentFormat = Literal["text/markdown"]

_HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"
_RESOURCE_ID_PATTERN = r"^res_[A-Za-z0-9._-]{8,120}$"
_MAX_METADATA_BYTES = 32 * 1024


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _strip_required(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value cannot be empty")
    return normalized


def _bounded_mapping(value: dict[str, Any]) -> dict[str, Any]:
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
    except (TypeError, ValueError) as exc:
        raise ValueError("metadata must be JSON serializable") from exc
    if len(encoded) > _MAX_METADATA_BYTES:
        raise ValueError(f"metadata exceeds {_MAX_METADATA_BYTES} bytes")
    return value


def _normalize_ids(value: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in value:
        item = item.strip()
        if item and item not in normalized:
            normalized.append(item)
    return normalized


class SourceUpsert(StrictModel):
    source_key: str = Field(min_length=1, max_length=256)
    kind: SourceKind
    canonical_uri: str = Field(min_length=1, max_length=4096)
    title: str | None = Field(default=None, max_length=1000)
    external_ids: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _strip_key = field_validator("source_key", "canonical_uri")(_strip_required)
    _bound_external_ids = field_validator("external_ids")(_bounded_mapping)
    _bound_metadata = field_validator("metadata")(_bounded_mapping)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class SourceUpdate(StrictModel):
    source_id: str = Field(min_length=1, max_length=128)
    canonical_uri: str | None = Field(default=None, min_length=1, max_length=4096)
    title: str | None = Field(default=None, max_length=1000)
    external_ids: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    _strip_id = field_validator("source_id")(_strip_required)

    @field_validator("canonical_uri")
    @classmethod
    def normalize_uri(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("external_ids", "metadata")
    @classmethod
    def bound_optional_mapping(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        return _bounded_mapping(value) if value is not None else None


class SourceRecord(StrictModel):
    source_id: str
    source_key: str
    kind: SourceKind
    canonical_uri: str
    title: str | None = None
    external_ids: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class ResourceGenerator(StrictModel):
    mode: GeneratorMode
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=64)
    model_provider: str | None = Field(default=None, max_length=128)
    model_id: str | None = Field(default=None, max_length=256)
    prompt_version: str | None = Field(default=None, max_length=128)

    _strip_required_fields = field_validator("name", "version")(_strip_required)

    @field_validator("model_provider", "model_id", "prompt_version")
    @classmethod
    def normalize_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_ai_provenance(self) -> ResourceGenerator:
        if self.mode == "ai":
            if not self.model_provider or not self.model_id or not self.prompt_version:
                raise ValueError(
                    "AI generators require model_provider, model_id, and prompt_version"
                )
        elif self.model_provider or self.model_id or self.prompt_version:
            raise ValueError("deterministic generators cannot declare AI model fields")
        return self


class ResourceCreate(StrictModel):
    resource_id: str = Field(pattern=_RESOURCE_ID_PATTERN)
    source_id: str = Field(min_length=1, max_length=128)
    kind: ResourceKind
    title: str = Field(min_length=1, max_length=1000)
    artifact_name: str = Field(min_length=1, max_length=256)
    content_hash: str = Field(pattern=_HASH_PATTERN)
    generator: ResourceGenerator
    metadata: dict[str, Any] = Field(default_factory=dict)

    _strip_fields = field_validator(
        "resource_id", "source_id", "title", "artifact_name", "content_hash"
    )(_strip_required)
    _bound_metadata = field_validator("metadata")(_bounded_mapping)


class ResourceRecord(StrictModel):
    resource_id: str
    source_id: str
    produced_by_run_id: str
    artifact_id: str
    kind: ResourceKind
    title: str
    content_hash: str
    generator: ResourceGenerator
    metadata: dict[str, Any] = Field(default_factory=dict)
    review_status: ReviewStatus
    created_at: datetime
    updated_at: datetime


class ResourceReviewUpdate(StrictModel):
    review_status: ReviewStatus


class KnowledgeRefCreate(StrictModel):
    note_id: str = Field(min_length=1, max_length=1024)
    uri: str = Field(min_length=1, max_length=4096)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    resource_ids: list[str] = Field(default_factory=list, max_length=100)
    revision_of: str | None = Field(default=None, max_length=128)

    _strip_fields = field_validator("note_id", "uri")(_strip_required)
    _normalize_source_ids = field_validator("source_ids")(_normalize_ids)
    _normalize_resource_ids = field_validator("resource_ids")(_normalize_ids)

    @field_validator("revision_of")
    @classmethod
    def normalize_revision(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def require_evidence(self) -> KnowledgeRefCreate:
        if not self.source_ids and not self.resource_ids:
            raise ValueError("KnowledgeRef must reference at least one Source or Resource")
        return self


class KnowledgeRefRecord(StrictModel):
    knowledge_ref_id: str
    note_id: str
    uri: str
    source_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    revision_of: str | None = None
    created_at: datetime
    updated_at: datetime


class CommentCreate(StrictModel):
    resource_id: str = Field(pattern=_RESOURCE_ID_PATTERN)
    body_markdown: str = Field(min_length=1, max_length=256 * 1024)
    content_hash: str = Field(pattern=_HASH_PATTERN)
    format: CommentFormat = "text/markdown"

    _strip_resource_id = field_validator("resource_id")(_strip_required)

    @field_validator("body_markdown")
    @classmethod
    def require_body(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("comment body cannot be blank")
        return value


class CommentRecord(StrictModel):
    comment_id: str
    knowledge_ref_id: str
    note_id: str
    source_ids: list[str] = Field(default_factory=list)
    resource_ids: list[str] = Field(default_factory=list)
    body_markdown: str
    content_hash: str
    format: CommentFormat
    created_at: datetime
    updated_at: datetime
