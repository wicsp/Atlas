from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from atlas.db.session import create_sqlite_session_factory

from .models import (
    KnowledgeAssessmentCreate,
    KnowledgeAssessmentRecord,
    KnowledgeAssessmentType,
    KnowledgeLinkCreate,
    KnowledgeLinkKind,
    KnowledgeLinkRecord,
    KnowledgeNeighborhood,
    KnowledgeNoteCreate,
    KnowledgeNoteRecord,
    KnowledgeNoteStatus,
    KnowledgeNoteUpdate,
)
from .repository import KnowledgeRepository


class KnowledgeService:
    def __init__(self, repository: KnowledgeRepository) -> None:
        self._repository = repository

    def create_note(self, payload: KnowledgeNoteCreate) -> KnowledgeNoteRecord:
        return self._repository.create_note(payload, _now())

    def get_note(self, note_id: str) -> KnowledgeNoteRecord:
        return self._repository.get_note(note_id)

    def list_notes(
        self,
        *,
        status: KnowledgeNoteStatus | None = None,
        source_id: str | None = None,
        resource_id: str | None = None,
        comment_id: str | None = None,
        query: str | None = None,
        limit: int = 100,
    ) -> list[KnowledgeNoteRecord]:
        return self._repository.list_notes(
            status=status,
            source_id=source_id,
            resource_id=resource_id,
            comment_id=comment_id,
            query=query,
            limit=limit,
        )

    def update_note(self, note_id: str, payload: KnowledgeNoteUpdate) -> KnowledgeNoteRecord:
        return self._repository.update_note(note_id, payload, _now())

    def create_link(self, payload: KnowledgeLinkCreate) -> KnowledgeLinkRecord:
        return self._repository.create_link(payload, _now())

    def list_links(
        self,
        *,
        note_id: str | None = None,
        kind: KnowledgeLinkKind | None = None,
        limit: int = 100,
    ) -> list[KnowledgeLinkRecord]:
        return self._repository.list_links(
            note_id=note_id,
            kind=kind,
            limit=limit,
        )

    def upsert_assessment(self, payload: KnowledgeAssessmentCreate) -> KnowledgeAssessmentRecord:
        return self._repository.upsert_assessment(payload, _now())

    def list_assessments(
        self,
        *,
        note_id: str | None = None,
        assessment_type: KnowledgeAssessmentType | None = None,
        limit: int = 100,
    ) -> list[KnowledgeAssessmentRecord]:
        return self._repository.list_assessments(
            note_id=note_id,
            assessment_type=assessment_type,
            limit=limit,
        )

    def neighborhood(self, note_id: str) -> KnowledgeNeighborhood:
        return self._repository.neighborhood(note_id)


def create_knowledge_service(database_path: Path) -> KnowledgeService:
    return KnowledgeService(KnowledgeRepository(create_sqlite_session_factory(database_path)))


def _now() -> datetime:
    return datetime.now(UTC)
