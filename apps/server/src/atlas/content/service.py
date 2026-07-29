from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from atlas.db.session import create_sqlite_session_factory

from .models import (
    CommentCreate,
    CommentRecord,
    KnowledgeRefCreate,
    KnowledgeRefRecord,
    ResourceRecord,
    ResourceReviewUpdate,
    ReviewStatus,
    SourceRecord,
    SourceUpdate,
    SourceUpsert,
)
from .repository import ContentRepository


class ContentService:
    def __init__(self, repository: ContentRepository) -> None:
        self._repository = repository

    def upsert_source(self, payload: SourceUpsert) -> SourceRecord:
        return self._repository.upsert_source(payload, _now())

    def get_source(self, source_id: str) -> SourceRecord:
        return self._repository.get_source(source_id)

    def update_source(self, payload: SourceUpdate) -> SourceRecord:
        return self._repository.update_source(payload, _now())

    def list_sources(self, kind: str | None = None, limit: int = 100) -> list[SourceRecord]:
        return self._repository.list_sources(kind=kind, limit=limit)

    def get_resource(self, resource_id: str) -> ResourceRecord:
        return self._repository.get_resource(resource_id)

    def list_resources(
        self,
        source_id: str | None = None,
        kind: str | None = None,
        review_status: ReviewStatus | None = None,
        limit: int = 100,
    ) -> list[ResourceRecord]:
        return self._repository.list_resources(
            source_id=source_id,
            kind=kind,
            review_status=review_status,
            limit=limit,
        )

    def update_resource_review(
        self,
        resource_id: str,
        payload: ResourceReviewUpdate,
    ) -> ResourceRecord:
        return self._repository.update_resource_review(
            resource_id, payload.review_status, _now()
        )

    def upsert_knowledge_ref(self, payload: KnowledgeRefCreate) -> KnowledgeRefRecord:
        return self._repository.upsert_knowledge_ref(payload, _now())

    def list_knowledge_refs(self, limit: int = 100) -> list[KnowledgeRefRecord]:
        return self._repository.list_knowledge_refs(limit=limit)

    def complete_comment(
        self,
        payload: CommentCreate,
        note_id: str,
        uri: str,
    ) -> tuple[ResourceRecord, KnowledgeRefRecord, CommentRecord]:
        return self._repository.complete_comment(payload, note_id, uri, _now())

    def list_comments(
        self,
        resource_id: str | None = None,
        source_id: str | None = None,
        limit: int = 100,
    ) -> list[CommentRecord]:
        return self._repository.list_comments(
            resource_id=resource_id,
            source_id=source_id,
            limit=limit,
        )

    def find_knowledge_ref_for_resource(
        self,
        resource_id: str,
    ) -> KnowledgeRefRecord | None:
        return self._repository.find_knowledge_ref_for_resource(resource_id)


def _now() -> datetime:
    return datetime.now(UTC)


def create_content_service(database_path: Path) -> ContentService:
    session_factory = create_sqlite_session_factory(database_path)
    return ContentService(ContentRepository(session_factory))
