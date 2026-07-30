from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from atlas.content.models import ResourceRecord
from atlas.content.repository import (
    CommentRow,
    KnowledgeRefRow,
    ResourceRow,
    _to_resource,
)
from atlas.db.session import create_sqlite_session_factory
from atlas.knowledge.repository import KnowledgeNoteEvidenceRow, KnowledgeNoteRow
from atlas.work.repository import ArtifactContentRow, ArtifactRow

from .models import ResourceIgnoreResponse

IGNORED_RESOURCE_LIMIT = 10
_PREVIOUS_STATUS_KEY = "_atlas_review_status_before_ignore"


@dataclass(frozen=True)
class IgnoreMutation:
    resource: ResourceRecord
    evicted_resource_ids: list[str]


class ResourceIgnoreRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ignore(self, resource_id: str, now: datetime) -> IgnoreMutation:
        with self._session_factory() as session, session.begin():
            resource = session.get(ResourceRow, resource_id)
            if resource is None:
                raise KeyError(resource_id)
            protected_note = _protecting_note(session, resource_id)
            if protected_note is not None:
                raise ValueError(
                    "Resource is evidence for Knowledge Note "
                    f"{protected_note.knowledge_note_id}; archive or relink the note first"
                )
            if resource.review_status != "dismissed":
                metadata = _load_json(resource.metadata_json, {})
                metadata[_PREVIOUS_STATUS_KEY] = resource.review_status
                resource.metadata_json = _dump_json(metadata)
                resource.review_status = "dismissed"
                resource.updated_at = now.isoformat()
                session.flush()

            ignored = session.scalars(
                select(ResourceRow)
                .where(ResourceRow.review_status == "dismissed")
                .order_by(ResourceRow.updated_at.desc(), ResourceRow.resource_id.desc())
            ).all()
            evictable = [
                item
                for item in ignored
                if _protecting_note(session, item.resource_id) is None
            ]
            overflow = evictable[IGNORED_RESOURCE_LIMIT:]
            for expired in overflow:
                _evict_resource(session, expired)
            session.flush()
            return IgnoreMutation(
                resource=_to_resource(resource),
                evicted_resource_ids=sorted(item.resource_id for item in overflow),
            )

    def restore(self, resource_id: str, now: datetime) -> IgnoreMutation:
        with self._session_factory() as session, session.begin():
            resource = session.get(ResourceRow, resource_id)
            if resource is None:
                raise KeyError(resource_id)
            if resource.review_status == "dismissed":
                metadata = _load_json(resource.metadata_json, {})
                previous = metadata.pop(_PREVIOUS_STATUS_KEY, "pending")
                resource.metadata_json = _dump_json(metadata)
                resource.review_status = (
                    previous if previous in {"pending", "reviewed"} else "pending"
                )
                resource.updated_at = now.isoformat()
                session.flush()
            return IgnoreMutation(resource=_to_resource(resource), evicted_resource_ids=[])


class ResourceIgnoreService:
    def __init__(self, repository: ResourceIgnoreRepository) -> None:
        self._repository = repository

    def ignore(self, resource_id: str) -> ResourceIgnoreResponse:
        return self._response(self._repository.ignore(resource_id, datetime.now(UTC)))

    def restore(self, resource_id: str) -> ResourceIgnoreResponse:
        return self._response(self._repository.restore(resource_id, datetime.now(UTC)))

    @staticmethod
    def _response(mutation: IgnoreMutation) -> ResourceIgnoreResponse:
        return ResourceIgnoreResponse(
            resource=mutation.resource,
            evicted_resource_ids=mutation.evicted_resource_ids,
        )


def create_resource_ignore_service(database_path: Path) -> ResourceIgnoreService:
    session_factory = create_sqlite_session_factory(database_path)
    return ResourceIgnoreService(ResourceIgnoreRepository(session_factory))


def _evict_resource(session: Session, resource: ResourceRow) -> None:
    for knowledge_ref in session.scalars(select(KnowledgeRefRow)).all():
        resource_ids = _load_json(knowledge_ref.resource_ids_json, [])
        if resource.resource_id not in resource_ids:
            continue
        comment = session.scalars(
            select(CommentRow).where(
                CommentRow.knowledge_ref_id == knowledge_ref.knowledge_ref_id
            )
        ).first()
        if comment is not None:
            session.delete(comment)
            session.delete(knowledge_ref)
            continue
        knowledge_ref.resource_ids_json = _dump_json(
            [item for item in resource_ids if item != resource.resource_id]
        )

    artifact = session.get(ArtifactRow, resource.artifact_id)
    if artifact is not None:
        shared = session.scalars(
            select(ResourceRow)
            .where(ResourceRow.artifact_id == artifact.artifact_id)
            .where(ResourceRow.resource_id != resource.resource_id)
        ).first()
        if shared is None:
            inline_content = session.get(ArtifactContentRow, artifact.artifact_id)
            if inline_content is not None:
                session.delete(inline_content)
            session.delete(artifact)

    session.delete(resource)


def _protecting_note(
    session: Session, resource_id: str
) -> KnowledgeNoteRow | None:
    return session.scalars(
        select(KnowledgeNoteRow)
        .join(
            KnowledgeNoteEvidenceRow,
            KnowledgeNoteEvidenceRow.knowledge_note_id
            == KnowledgeNoteRow.knowledge_note_id,
        )
        .where(
            KnowledgeNoteEvidenceRow.evidence_type == "resource",
            KnowledgeNoteEvidenceRow.target_id == resource_id,
            KnowledgeNoteRow.status != "archived",
        )
    ).first()


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback
