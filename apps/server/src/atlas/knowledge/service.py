from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from atlas.db.session import create_sqlite_session_factory

from .models import (
    KnowledgeNeighborhood,
    KnowledgeNoteCreate,
    KnowledgeNoteRecord,
    KnowledgeNoteStatus,
    KnowledgeNoteUpdate,
    KnowledgeRelationCreate,
    KnowledgeRelationRecord,
    KnowledgeRelationStatus,
    KnowledgeRelationType,
    KnowledgeRelationUpdate,
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

    def update_note(
        self, note_id: str, payload: KnowledgeNoteUpdate
    ) -> KnowledgeNoteRecord:
        return self._repository.update_note(note_id, payload, _now())

    def create_relation(
        self, payload: KnowledgeRelationCreate
    ) -> KnowledgeRelationRecord:
        return self._repository.create_relation(payload, _now())

    def get_relation(self, relation_id: str) -> KnowledgeRelationRecord:
        return self._repository.get_relation(relation_id)

    def list_relations(
        self,
        *,
        note_id: str | None = None,
        status: KnowledgeRelationStatus | None = None,
        relation_type: KnowledgeRelationType | None = None,
        limit: int = 100,
    ) -> list[KnowledgeRelationRecord]:
        return self._repository.list_relations(
            note_id=note_id,
            status=status,
            relation_type=relation_type,
            limit=limit,
        )

    def update_relation(
        self, relation_id: str, payload: KnowledgeRelationUpdate
    ) -> KnowledgeRelationRecord:
        return self._repository.update_relation(relation_id, payload, _now())

    def neighborhood(
        self, note_id: str, include_suggested: bool = False
    ) -> KnowledgeNeighborhood:
        return self._repository.neighborhood(note_id, include_suggested)


def create_knowledge_service(database_path: Path) -> KnowledgeService:
    return KnowledgeService(
        KnowledgeRepository(create_sqlite_session_factory(database_path))
    )


def _now() -> datetime:
    return datetime.now(UTC)
