from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KnowledgeNoteStatus = Literal["draft", "active", "superseded", "archived"]
KnowledgeOrigin = Literal["human", "ai"]
KnowledgeLinkKind = Literal["related", "supersedes"]
KnowledgeLinkOrigin = Literal["markdown", "human"]
KnowledgeAssessmentType = Literal["supports", "tension", "duplicate"]

_KNOWLEDGE_NOTE_ID_PATTERN = r"^kn_[0-9a-f]{32}$"
_KNOWLEDGE_LINK_ID_PATTERN = r"^kln_[0-9a-f]{32}$"
_KNOWLEDGE_ASSESSMENT_ID_PATTERN = r"^kas_[0-9a-f]{32}$"
_SOURCE_ID_PATTERN = r"^src_[A-Za-z0-9._-]{8,120}$"
_RESOURCE_ID_PATTERN = r"^res_[A-Za-z0-9._-]{8,120}$"
_COMMENT_ID_PATTERN = r"^cmt_[A-Za-z0-9._-]{8,120}$"
_HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"
_MAX_TAGS = 50
_MAX_TAG_BYTES = 8 * 1024


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _strip_required(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value cannot be empty")
    return normalized


def _normalize_tags(value: list[str]) -> list[str]:
    normalized: list[str] = []
    for tag in value:
        cleaned = tag.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    if len(normalized) > _MAX_TAGS:
        raise ValueError(f"knowledge note cannot have more than {_MAX_TAGS} tags")
    if len(json.dumps(normalized, ensure_ascii=False).encode()) > _MAX_TAG_BYTES:
        raise ValueError(f"knowledge note tags exceed {_MAX_TAG_BYTES} bytes")
    return normalized


def _normalize_ids(value: list[str]) -> list[str]:
    normalized: list[str] = []
    for item in value:
        cleaned = item.strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


class KnowledgeNoteCreate(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    claim: str = Field(min_length=1, max_length=8_000)
    body_markdown: str = Field(default="", max_length=256 * 1024)
    tags: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list, max_length=100)
    resource_ids: list[str] = Field(default_factory=list, max_length=100)
    comment_ids: list[str] = Field(default_factory=list, max_length=100)
    status: KnowledgeNoteStatus = "draft"
    origin: KnowledgeOrigin = "human"

    _strip_text = field_validator("title", "claim")(_strip_required)
    _normalize_tags = field_validator("tags")(_normalize_tags)
    _normalize_sources = field_validator("source_ids")(_normalize_ids)
    _normalize_resources = field_validator("resource_ids")(_normalize_ids)
    _normalize_comments = field_validator("comment_ids")(_normalize_ids)

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, value: list[str]) -> list[str]:
        return _validate_ids(value, _SOURCE_ID_PATTERN, "Source")

    @field_validator("resource_ids")
    @classmethod
    def validate_resource_ids(cls, value: list[str]) -> list[str]:
        return _validate_ids(value, _RESOURCE_ID_PATTERN, "Resource")

    @field_validator("comment_ids")
    @classmethod
    def validate_comment_ids(cls, value: list[str]) -> list[str]:
        return _validate_ids(value, _COMMENT_ID_PATTERN, "Comment")

    @model_validator(mode="after")
    def ai_notes_start_as_drafts(self) -> KnowledgeNoteCreate:
        if self.origin == "ai" and self.status != "draft":
            raise ValueError("AI-origin Knowledge Notes must start as drafts")
        return self


class KnowledgeNoteUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    claim: str | None = Field(default=None, min_length=1, max_length=8_000)
    body_markdown: str | None = Field(default=None, max_length=256 * 1024)
    tags: list[str] | None = None
    source_ids: list[str] | None = Field(default=None, max_length=100)
    resource_ids: list[str] | None = Field(default=None, max_length=100)
    comment_ids: list[str] | None = Field(default=None, max_length=100)
    status: KnowledgeNoteStatus | None = None

    @field_validator("title", "claim")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        return _strip_required(value) if value is not None else None

    @field_validator("tags")
    @classmethod
    def normalize_optional_tags(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_tags(value) if value is not None else None

    @field_validator("source_ids", "resource_ids", "comment_ids")
    @classmethod
    def normalize_optional_ids(cls, value: list[str] | None) -> list[str] | None:
        return _normalize_ids(value) if value is not None else None

    @field_validator("source_ids")
    @classmethod
    def validate_source_ids(cls, value: list[str] | None) -> list[str] | None:
        return _validate_ids(value, _SOURCE_ID_PATTERN, "Source") if value is not None else None

    @field_validator("resource_ids")
    @classmethod
    def validate_resource_ids(cls, value: list[str] | None) -> list[str] | None:
        return _validate_ids(value, _RESOURCE_ID_PATTERN, "Resource") if value is not None else None

    @field_validator("comment_ids")
    @classmethod
    def validate_comment_ids(cls, value: list[str] | None) -> list[str] | None:
        return _validate_ids(value, _COMMENT_ID_PATTERN, "Comment") if value is not None else None

    @model_validator(mode="after")
    def require_change(self) -> KnowledgeNoteUpdate:
        if self.model_fields_set == {"expected_revision"}:
            raise ValueError("Knowledge Note update must change at least one field")
        for field in self.model_fields_set - {"expected_revision"}:
            if getattr(self, field) is None:
                raise ValueError(f"Knowledge Note field {field} cannot be null")
        return self


class KnowledgeNoteRecord(StrictModel):
    knowledge_note_id: str = Field(pattern=_KNOWLEDGE_NOTE_ID_PATTERN)
    title: str
    claim: str
    body_markdown: str
    tags: list[str]
    source_ids: list[str]
    resource_ids: list[str]
    comment_ids: list[str]
    status: KnowledgeNoteStatus
    origin: KnowledgeOrigin
    content_hash: str = Field(pattern=_HASH_PATTERN)
    revision: int
    created_at: datetime
    updated_at: datetime


class KnowledgeLinkCreate(StrictModel):
    from_note_id: str = Field(pattern=_KNOWLEDGE_NOTE_ID_PATTERN)
    to_note_id: str = Field(pattern=_KNOWLEDGE_NOTE_ID_PATTERN)
    kind: KnowledgeLinkKind = "related"
    origin: KnowledgeLinkOrigin = "human"

    _strip_ids = field_validator("from_note_id", "to_note_id")(_strip_required)

    @model_validator(mode="after")
    def validate_link(self) -> KnowledgeLinkCreate:
        if self.from_note_id == self.to_note_id:
            raise ValueError("Knowledge Link cannot connect a note to itself")
        if self.kind == "supersedes" and self.origin != "human":
            raise ValueError("supersedes must be explicitly confirmed by a human")
        return self


class KnowledgeLinkRecord(StrictModel):
    knowledge_link_id: str = Field(pattern=_KNOWLEDGE_LINK_ID_PATTERN)
    from_note_id: str = Field(pattern=_KNOWLEDGE_NOTE_ID_PATTERN)
    to_note_id: str = Field(pattern=_KNOWLEDGE_NOTE_ID_PATTERN)
    kind: KnowledgeLinkKind
    origin: KnowledgeLinkOrigin
    created_at: datetime


class KnowledgeAssessmentCreate(StrictModel):
    from_note_id: str = Field(pattern=_KNOWLEDGE_NOTE_ID_PATTERN)
    to_note_id: str = Field(pattern=_KNOWLEDGE_NOTE_ID_PATTERN)
    assessment_type: KnowledgeAssessmentType
    explanation_markdown: str = Field(min_length=1, max_length=64 * 1024)
    confidence: float = Field(ge=0, le=1)
    model_id: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def prevent_self_assessment(self) -> KnowledgeAssessmentCreate:
        if self.from_note_id == self.to_note_id:
            raise ValueError("Knowledge Assessment cannot compare a note with itself")
        return self


class KnowledgeAssessmentRecord(KnowledgeAssessmentCreate):
    knowledge_assessment_id: str = Field(pattern=_KNOWLEDGE_ASSESSMENT_ID_PATTERN)
    created_at: datetime
    updated_at: datetime


class KnowledgeNeighborhood(StrictModel):
    center: KnowledgeNoteRecord
    notes: list[KnowledgeNoteRecord]
    links: list[KnowledgeLinkRecord]
    assessments: list[KnowledgeAssessmentRecord]


def _validate_ids(value: list[str], pattern: str, label: str) -> list[str]:
    import re

    compiled = re.compile(pattern)
    invalid = [item for item in value if compiled.fullmatch(item) is None]
    if invalid:
        raise ValueError(f"{label} IDs are invalid: {', '.join(invalid[:3])}")
    return value
