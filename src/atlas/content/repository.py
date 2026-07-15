from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from atlas.db.base import Base

from .models import (
    KnowledgeRefCreate,
    KnowledgeRefRecord,
    ResourceCreate,
    ResourceRecord,
    ReviewStatus,
    SourceRecord,
    SourceUpdate,
    SourceUpsert,
)


class ReferencedResourceDismissalError(ValueError):
    """Raised when a Resource is still evidence for human-authored Knowledge."""


class SourceRow(Base):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    canonical_uri: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_ids_json: Mapped[str] = mapped_column(Text, default="{}")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)


class ResourceRow(Base):
    __tablename__ = "resources"

    resource_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), index=True)
    produced_by_run_id: Mapped[str] = mapped_column(String(128), index=True)
    artifact_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    generator_json: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    review_status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)


class KnowledgeRefRow(Base):
    __tablename__ = "knowledge_refs"

    knowledge_ref_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    note_id: Mapped[str] = mapped_column(Text, unique=True)
    uri: Mapped[str] = mapped_column(Text)
    source_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    resource_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    revision_of: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)


class ContentRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def upsert_source(self, payload: SourceUpsert, now: datetime) -> SourceRecord:
        with self._session_factory() as session, session.begin():
            row = session.scalars(
                select(SourceRow).where(SourceRow.source_key == payload.source_key)
            ).first()
            if row is None:
                row = SourceRow(
                    source_id=f"src_{uuid.uuid4().hex}",
                    source_key=payload.source_key,
                    kind=payload.kind,
                    canonical_uri=payload.canonical_uri,
                    title=payload.title,
                    external_ids_json=_dump_json(payload.external_ids),
                    metadata_json=_dump_json(payload.metadata),
                    created_at=now.isoformat(),
                    updated_at=now.isoformat(),
                )
                session.add(row)
            else:
                if row.kind != payload.kind:
                    raise ValueError(
                        f"Source {payload.source_key} already exists with kind {row.kind}"
                    )
                row.canonical_uri = payload.canonical_uri
                if payload.title is not None:
                    row.title = payload.title
                external_ids = _load_json(row.external_ids_json, {})
                external_ids.update(payload.external_ids)
                row.external_ids_json = _dump_json(external_ids)
                metadata = _load_json(row.metadata_json, {})
                metadata.update(payload.metadata)
                row.metadata_json = _dump_json(metadata)
                row.updated_at = now.isoformat()
            session.flush()
            return _to_source(row)

    def get_source(self, source_id: str) -> SourceRecord:
        with self._session_factory() as session:
            row = session.get(SourceRow, source_id)
            if row is None:
                raise KeyError(source_id)
            return _to_source(row)

    def list_sources(self, kind: str | None = None, limit: int = 100) -> list[SourceRecord]:
        with self._session_factory() as session:
            stmt = select(SourceRow).order_by(SourceRow.created_at.desc()).limit(limit)
            if kind:
                stmt = stmt.where(SourceRow.kind == kind)
            return [_to_source(row) for row in session.scalars(stmt).all()]

    def get_resource(self, resource_id: str) -> ResourceRecord:
        with self._session_factory() as session:
            row = session.get(ResourceRow, resource_id)
            if row is None:
                raise KeyError(resource_id)
            return _to_resource(row)

    def list_resources(
        self,
        source_id: str | None = None,
        kind: str | None = None,
        review_status: ReviewStatus | None = None,
        limit: int = 100,
    ) -> list[ResourceRecord]:
        with self._session_factory() as session:
            stmt = select(ResourceRow).order_by(ResourceRow.created_at.desc()).limit(limit)
            if source_id:
                stmt = stmt.where(ResourceRow.source_id == source_id)
            if kind:
                stmt = stmt.where(ResourceRow.kind == kind)
            if review_status:
                stmt = stmt.where(ResourceRow.review_status == review_status)
            return [_to_resource(row) for row in session.scalars(stmt).all()]

    def update_resource_review(
        self,
        resource_id: str,
        review_status: ReviewStatus,
        now: datetime,
    ) -> ResourceRecord:
        with self._session_factory() as session, session.begin():
            row = session.get(ResourceRow, resource_id)
            if row is None:
                raise KeyError(resource_id)
            if review_status == "dismissed":
                referenced_by = next(
                    (
                        knowledge_ref
                        for knowledge_ref in session.scalars(select(KnowledgeRefRow)).all()
                        if resource_id
                        in _load_json(knowledge_ref.resource_ids_json, [])
                    ),
                    None,
                )
                if referenced_by is not None:
                    raise ReferencedResourceDismissalError(
                        f"Resource {resource_id} is referenced by KnowledgeRef "
                        f"{referenced_by.knowledge_ref_id}"
                    )
            row.review_status = review_status
            row.updated_at = now.isoformat()
            session.flush()
            return _to_resource(row)

    def upsert_knowledge_ref(
        self,
        payload: KnowledgeRefCreate,
        now: datetime,
    ) -> KnowledgeRefRecord:
        with self._session_factory() as session, session.begin():
            source_ids = list(payload.source_ids)
            for source_id in source_ids:
                if session.get(SourceRow, source_id) is None:
                    raise KeyError(source_id)

            for resource_id in payload.resource_ids:
                resource = session.get(ResourceRow, resource_id)
                if resource is None:
                    raise KeyError(resource_id)
                if resource.source_id not in source_ids:
                    source_ids.append(resource.source_id)

            if payload.revision_of and session.get(KnowledgeRefRow, payload.revision_of) is None:
                raise KeyError(payload.revision_of)

            row = session.scalars(
                select(KnowledgeRefRow).where(KnowledgeRefRow.note_id == payload.note_id)
            ).first()
            if row is None:
                row = KnowledgeRefRow(
                    knowledge_ref_id=f"kref_{uuid.uuid4().hex}",
                    note_id=payload.note_id,
                    uri=payload.uri,
                    source_ids_json=_dump_json(source_ids),
                    resource_ids_json=_dump_json(payload.resource_ids),
                    revision_of=payload.revision_of,
                    created_at=now.isoformat(),
                    updated_at=now.isoformat(),
                )
                session.add(row)
            else:
                row.uri = payload.uri
                row.source_ids_json = _dump_json(source_ids)
                row.resource_ids_json = _dump_json(payload.resource_ids)
                row.revision_of = payload.revision_of
                row.updated_at = now.isoformat()
            session.flush()
            return _to_knowledge_ref(row)

    def list_knowledge_refs(self, limit: int = 100) -> list[KnowledgeRefRecord]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(KnowledgeRefRow)
                .order_by(KnowledgeRefRow.created_at.desc())
                .limit(limit)
            ).all()
            return [_to_knowledge_ref(row) for row in rows]


def apply_source_updates(
    session: Session,
    updates: list[SourceUpdate],
    now: datetime,
) -> None:
    for update in updates:
        row = session.get(SourceRow, update.source_id)
        if row is None:
            raise ValueError(f"Source {update.source_id} does not exist")
        fields = update.model_fields_set
        if "canonical_uri" in fields and update.canonical_uri is not None:
            row.canonical_uri = update.canonical_uri
        if "title" in fields:
            row.title = update.title
        if "external_ids" in fields and update.external_ids is not None:
            external_ids = _load_json(row.external_ids_json, {})
            external_ids.update(update.external_ids)
            row.external_ids_json = _dump_json(external_ids)
        if "metadata" in fields and update.metadata is not None:
            metadata = _load_json(row.metadata_json, {})
            metadata.update(update.metadata)
            row.metadata_json = _dump_json(metadata)
        row.updated_at = now.isoformat()


def publish_resources(
    session: Session,
    run_id: str,
    artifacts_by_name: dict[str, str],
    resources: list[ResourceCreate],
    now: datetime,
) -> None:
    for resource in resources:
        expected_id = _resource_id(
            resource.source_id,
            resource.kind,
            resource.content_hash,
        )
        if resource.resource_id != expected_id:
            raise ValueError(
                f"Resource ID {resource.resource_id} does not match its Source, kind, and hash"
            )
        if session.get(SourceRow, resource.source_id) is None:
            raise ValueError(f"Source {resource.source_id} does not exist")
        artifact_id = artifacts_by_name.get(resource.artifact_name)
        if artifact_id is None:
            raise ValueError(
                f"Resource {resource.resource_id} references missing artifact "
                f"{resource.artifact_name}"
            )

        existing = session.get(ResourceRow, resource.resource_id)
        if existing is not None:
            same_identity = (
                existing.source_id == resource.source_id
                and existing.kind == resource.kind
                and existing.content_hash == resource.content_hash
                and existing.generator_json == _dump_json(resource.generator.model_dump())
            )
            if not same_identity:
                raise ValueError(f"Resource ID {resource.resource_id} conflicts with existing data")
            continue

        session.add(
            ResourceRow(
                resource_id=resource.resource_id,
                source_id=resource.source_id,
                produced_by_run_id=run_id,
                artifact_id=artifact_id,
                kind=resource.kind,
                title=resource.title,
                content_hash=resource.content_hash,
                generator_json=_dump_json(resource.generator.model_dump()),
                metadata_json=_dump_json(resource.metadata),
                review_status="pending",
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
        )


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _resource_id(source_id: str, kind: str, content_hash: str) -> str:
    digest = hashlib.sha256(f"{source_id}\0{kind}\0{content_hash}".encode()).hexdigest()
    return f"res_{digest[:32]}"


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _to_source(row: SourceRow) -> SourceRecord:
    return SourceRecord(
        source_id=row.source_id,
        source_key=row.source_key,
        kind=row.kind,  # type: ignore[arg-type]
        canonical_uri=row.canonical_uri,
        title=row.title,
        external_ids=_load_json(row.external_ids_json, {}),
        metadata=_load_json(row.metadata_json, {}),
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


def _to_resource(row: ResourceRow) -> ResourceRecord:
    return ResourceRecord(
        resource_id=row.resource_id,
        source_id=row.source_id,
        produced_by_run_id=row.produced_by_run_id,
        artifact_id=row.artifact_id,
        kind=row.kind,  # type: ignore[arg-type]
        title=row.title,
        content_hash=row.content_hash,
        generator=_load_json(row.generator_json, {}),
        metadata=_load_json(row.metadata_json, {}),
        review_status=row.review_status,  # type: ignore[arg-type]
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


def _to_knowledge_ref(row: KnowledgeRefRow) -> KnowledgeRefRecord:
    return KnowledgeRefRecord(
        knowledge_ref_id=row.knowledge_ref_id,
        note_id=row.note_id,
        uri=row.uri,
        source_ids=_load_json(row.source_ids_json, []),
        resource_ids=_load_json(row.resource_ids_json, []),
        revision_of=row.revision_of,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )
