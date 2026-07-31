from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ProjectStatus = Literal["active", "on_hold", "completed", "archived"]
WorkItemStatus = Literal["todo", "in_progress", "blocked", "done", "cancelled"]
DocumentStatus = Literal["draft", "final", "archived"]

_PROJECT_ID = r"^prj_[0-9a-f]{32}$"
_WORK_ITEM_ID = r"^wi_[0-9a-f]{32}$"
_DOCUMENT_ID = r"^doc_[0-9a-f]{32}$"
_VERSION_ID = r"^dver_[0-9a-f]{32}$"
_HASH = r"^sha256:[0-9a-f]{64}$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _strip(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("value cannot be empty")
    return value


class ProjectCreate(StrictModel):
    title: str = Field(min_length=1, max_length=500)
    goal: str = Field(min_length=1, max_length=8_000)
    description: str = Field(default="", max_length=64 * 1024)
    audience: str = Field(default="", max_length=2_000)
    deadline: date | None = None

    _normalize = field_validator("title", "goal")(_strip)


class ProjectUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    goal: str | None = Field(default=None, min_length=1, max_length=8_000)
    description: str | None = Field(default=None, max_length=64 * 1024)
    audience: str | None = Field(default=None, max_length=2_000)
    deadline: date | None = None
    status: ProjectStatus | None = None

    @model_validator(mode="after")
    def require_change(self) -> ProjectUpdate:
        if self.model_fields_set == {"expected_revision"}:
            raise ValueError("Project update must change at least one field")
        return self


class ProjectRecord(StrictModel):
    project_id: str = Field(pattern=_PROJECT_ID)
    title: str
    goal: str
    description: str
    audience: str
    deadline: date | None
    status: ProjectStatus
    revision: int
    created_at: datetime
    updated_at: datetime


class WorkItemCreate(StrictModel):
    project_id: str = Field(pattern=_PROJECT_ID)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=32 * 1024)
    document_id: str | None = Field(default=None, pattern=_DOCUMENT_ID)
    due_at: datetime | None = None

    _normalize = field_validator("title")(_strip)


class WorkItemUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=32 * 1024)
    document_id: str | None = Field(default=None, pattern=_DOCUMENT_ID)
    due_at: datetime | None = None
    status: WorkItemStatus | None = None

    @model_validator(mode="after")
    def require_change(self) -> WorkItemUpdate:
        if self.model_fields_set == {"expected_revision"}:
            raise ValueError("WorkItem update must change at least one field")
        return self


class WorkItemRecord(StrictModel):
    work_item_id: str = Field(pattern=_WORK_ITEM_ID)
    project_id: str = Field(pattern=_PROJECT_ID)
    title: str
    description: str
    document_id: str | None
    due_at: datetime | None
    status: WorkItemStatus
    revision: int
    created_at: datetime
    updated_at: datetime


class DocumentCreate(StrictModel):
    project_id: str = Field(pattern=_PROJECT_ID)
    title: str = Field(min_length=1, max_length=500)
    body_markdown: str = Field(default="", max_length=2 * 1024 * 1024)

    _normalize = field_validator("title")(_strip)


class DocumentUpdate(StrictModel):
    expected_revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=500)
    body_markdown: str | None = Field(default=None, max_length=2 * 1024 * 1024)
    status: DocumentStatus | None = None

    @model_validator(mode="after")
    def require_change(self) -> DocumentUpdate:
        if self.model_fields_set == {"expected_revision"}:
            raise ValueError("Document update must change at least one field")
        return self


class DocumentRecord(StrictModel):
    document_id: str = Field(pattern=_DOCUMENT_ID)
    project_id: str = Field(pattern=_PROJECT_ID)
    title: str
    body_markdown: str
    status: DocumentStatus
    linked_knowledge_note_ids: list[str]
    content_hash: str = Field(pattern=_HASH)
    revision: int
    created_at: datetime
    updated_at: datetime


class RenderedDocument(StrictModel):
    document_id: str = Field(pattern=_DOCUMENT_ID)
    source_revision: int
    body_markdown: str
    embedded_knowledge_note_ids: list[str]


class DocumentVersionCreate(StrictModel):
    label: str = Field(default="", max_length=500)


class DocumentVersionRecord(StrictModel):
    document_version_id: str = Field(pattern=_VERSION_ID)
    document_id: str = Field(pattern=_DOCUMENT_ID)
    revision: int
    label: str
    title: str
    body_markdown: str
    content_hash: str = Field(pattern=_HASH)
    created_at: datetime


class ProjectDetail(StrictModel):
    project: ProjectRecord
    work_items: list[WorkItemRecord]
    documents: list[DocumentRecord]
