from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from atlas.db.session import create_sqlite_session_factory

from .models import (
    KnowledgeRefCreate,
    KnowledgeRefRecord,
    ResourceRecord,
    ResourceReviewUpdate,
    ReviewStatus,
    SourceRecord,
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


def _now() -> datetime:
    return datetime.now(UTC)


def create_content_service(database_path: Path) -> ContentService:
    session_factory = create_sqlite_session_factory(database_path)
    return ContentService(ContentRepository(session_factory))
