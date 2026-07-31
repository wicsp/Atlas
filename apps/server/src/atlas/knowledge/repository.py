from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime

from sqlalchemy import Float, Integer, String, Text, UniqueConstraint, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from atlas.content.repository import CommentRow, KnowledgeRefRow, ResourceRow, SourceRow
from atlas.db.base import Base

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


class KnowledgeNoteRow(Base):
    __tablename__ = "knowledge_notes"

    knowledge_note_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    claim: Mapped[str] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text, default="")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(32), index=True)
    origin: Mapped[str] = mapped_column(String(16), index=True)
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)


class KnowledgeNoteEvidenceRow(Base):
    __tablename__ = "knowledge_note_evidence"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_note_id",
            "evidence_type",
            "target_id",
            name="uq_knowledge_note_evidence",
        ),
    )

    evidence_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    knowledge_note_id: Mapped[str] = mapped_column(String(128), index=True)
    evidence_type: Mapped[str] = mapped_column(String(32), index=True)
    target_id: Mapped[str] = mapped_column(String(128), index=True)


class KnowledgeLinkRow(Base):
    __tablename__ = "knowledge_links"
    __table_args__ = (
        UniqueConstraint(
            "from_note_id",
            "to_note_id",
            "kind",
            name="uq_knowledge_link",
        ),
    )

    knowledge_link_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    from_note_id: Mapped[str] = mapped_column(String(128), index=True)
    to_note_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    origin: Mapped[str] = mapped_column(String(16), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)


class KnowledgeAssessmentRow(Base):
    __tablename__ = "knowledge_assessments"
    __table_args__ = (
        UniqueConstraint(
            "from_note_id",
            "to_note_id",
            "assessment_type",
            "model_id",
            name="uq_knowledge_assessment",
        ),
    )

    knowledge_assessment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    from_note_id: Mapped[str] = mapped_column(String(128), index=True)
    to_note_id: Mapped[str] = mapped_column(String(128), index=True)
    assessment_type: Mapped[str] = mapped_column(String(32), index=True)
    explanation_markdown: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    model_id: Mapped[str] = mapped_column(String(200), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)


class KnowledgeRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_note(self, payload: KnowledgeNoteCreate, now: datetime) -> KnowledgeNoteRecord:
        with self._session_factory() as session, session.begin():
            _validate_evidence(
                session,
                payload.source_ids,
                payload.resource_ids,
                payload.comment_ids,
            )
            source_ids, resource_ids, comment_ids = _expand_evidence(
                session,
                payload.source_ids,
                payload.resource_ids,
                payload.comment_ids,
            )
            row = KnowledgeNoteRow(
                knowledge_note_id=f"kn_{uuid.uuid4().hex}",
                title=payload.title,
                claim=payload.claim,
                body_markdown=payload.body_markdown,
                tags_json=_dump_json(payload.tags),
                status=payload.status,
                origin=payload.origin,
                content_hash=_note_hash(
                    payload.title, payload.claim, payload.body_markdown, payload.tags
                ),
                revision=1,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
            session.add(row)
            session.flush()
            _sync_markdown_links(session, row.knowledge_note_id, row.body_markdown, now)
            _replace_evidence(
                session,
                row.knowledge_note_id,
                source_ids,
                resource_ids,
                comment_ids,
            )
            return _to_note(session, row)

    def get_note(self, note_id: str) -> KnowledgeNoteRecord:
        with self._session_factory() as session:
            row = session.get(KnowledgeNoteRow, note_id)
            if row is None:
                raise KeyError(note_id)
            return _to_note(session, row)

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
        with self._session_factory() as session:
            statement = select(KnowledgeNoteRow)
            if status is not None:
                statement = statement.where(KnowledgeNoteRow.status == status)
            for evidence_type, target_id in (
                ("source", source_id),
                ("resource", resource_id),
                ("comment", comment_id),
            ):
                if target_id is None:
                    continue
                matching_note_ids = select(KnowledgeNoteEvidenceRow.knowledge_note_id).where(
                    KnowledgeNoteEvidenceRow.evidence_type == evidence_type,
                    KnowledgeNoteEvidenceRow.target_id == target_id,
                )
                statement = statement.where(
                    KnowledgeNoteRow.knowledge_note_id.in_(matching_note_ids)
                )
            if query and query.strip():
                pattern = f"%{query.strip()}%"
                statement = statement.where(
                    or_(
                        KnowledgeNoteRow.title.ilike(pattern),
                        KnowledgeNoteRow.claim.ilike(pattern),
                        KnowledgeNoteRow.body_markdown.ilike(pattern),
                    )
                )
            rows = session.scalars(
                statement.order_by(KnowledgeNoteRow.updated_at.desc()).limit(limit)
            ).all()
            return [_to_note(session, row) for row in rows]

    def update_note(
        self, note_id: str, payload: KnowledgeNoteUpdate, now: datetime
    ) -> KnowledgeNoteRecord:
        with self._session_factory() as session, session.begin():
            row = session.get(KnowledgeNoteRow, note_id)
            if row is None:
                raise KeyError(note_id)
            if row.revision != payload.expected_revision:
                raise ValueError(
                    f"Knowledge Note revision conflict: expected {payload.expected_revision}, "
                    f"current {row.revision}"
                )
            fields = payload.model_fields_set
            if "title" in fields and payload.title is not None:
                row.title = payload.title
            if "claim" in fields and payload.claim is not None:
                row.claim = payload.claim
            if "body_markdown" in fields and payload.body_markdown is not None:
                row.body_markdown = payload.body_markdown
            if "tags" in fields and payload.tags is not None:
                row.tags_json = _dump_json(payload.tags)
            if "status" in fields and payload.status is not None:
                row.status = payload.status

            evidence = _evidence_by_type(session, note_id)
            source_ids = (
                payload.source_ids
                if "source_ids" in fields and payload.source_ids is not None
                else evidence["source"]
            )
            resource_ids = (
                payload.resource_ids
                if "resource_ids" in fields and payload.resource_ids is not None
                else evidence["resource"]
            )
            comment_ids = (
                payload.comment_ids
                if "comment_ids" in fields and payload.comment_ids is not None
                else evidence["comment"]
            )
            _validate_evidence(session, source_ids, resource_ids, comment_ids)
            source_ids, resource_ids, comment_ids = _expand_evidence(
                session, source_ids, resource_ids, comment_ids
            )
            if fields.intersection({"source_ids", "resource_ids", "comment_ids"}):
                _replace_evidence(session, note_id, source_ids, resource_ids, comment_ids)

            tags = json.loads(row.tags_json)
            row.content_hash = _note_hash(row.title, row.claim, row.body_markdown, tags)
            row.revision += 1
            row.updated_at = now.isoformat()
            session.flush()
            if "body_markdown" in fields:
                _sync_markdown_links(session, row.knowledge_note_id, row.body_markdown, now)
            return _to_note(session, row)

    def create_link(self, payload: KnowledgeLinkCreate, now: datetime) -> KnowledgeLinkRecord:
        with self._session_factory() as session, session.begin():
            _require_note(session, payload.from_note_id)
            target = _require_note(session, payload.to_note_id)
            existing = session.scalars(
                select(KnowledgeLinkRow).where(
                    KnowledgeLinkRow.from_note_id == payload.from_note_id,
                    KnowledgeLinkRow.to_note_id == payload.to_note_id,
                    KnowledgeLinkRow.kind == payload.kind,
                )
            ).first()
            if existing is not None:
                return _to_link(existing)
            row = KnowledgeLinkRow(
                knowledge_link_id=f"kln_{uuid.uuid4().hex}",
                from_note_id=payload.from_note_id,
                to_note_id=payload.to_note_id,
                kind=payload.kind,
                origin=payload.origin,
                created_at=now.isoformat(),
            )
            session.add(row)
            if payload.kind == "supersedes":
                target.status = "superseded"
                target.revision += 1
                target.updated_at = now.isoformat()
            session.flush()
            return _to_link(row)

    def list_links(
        self,
        *,
        note_id: str | None = None,
        kind: KnowledgeLinkKind | None = None,
        limit: int = 100,
    ) -> list[KnowledgeLinkRecord]:
        with self._session_factory() as session:
            statement = select(KnowledgeLinkRow)
            if note_id is not None:
                statement = statement.where(
                    or_(
                        KnowledgeLinkRow.from_note_id == note_id,
                        KnowledgeLinkRow.to_note_id == note_id,
                    )
                )
            if kind is not None:
                statement = statement.where(KnowledgeLinkRow.kind == kind)
            rows = session.scalars(
                statement.order_by(KnowledgeLinkRow.created_at.desc()).limit(limit)
            ).all()
            return [_to_link(row) for row in rows]

    def upsert_assessment(
        self, payload: KnowledgeAssessmentCreate, now: datetime
    ) -> KnowledgeAssessmentRecord:
        with self._session_factory() as session, session.begin():
            _require_note(session, payload.from_note_id)
            _require_note(session, payload.to_note_id)
            row = session.scalars(
                select(KnowledgeAssessmentRow).where(
                    KnowledgeAssessmentRow.from_note_id == payload.from_note_id,
                    KnowledgeAssessmentRow.to_note_id == payload.to_note_id,
                    KnowledgeAssessmentRow.assessment_type == payload.assessment_type,
                    KnowledgeAssessmentRow.model_id == payload.model_id,
                )
            ).first()
            if row is None:
                row = KnowledgeAssessmentRow(
                    knowledge_assessment_id=f"kas_{uuid.uuid4().hex}",
                    from_note_id=payload.from_note_id,
                    to_note_id=payload.to_note_id,
                    assessment_type=payload.assessment_type,
                    explanation_markdown=payload.explanation_markdown,
                    confidence=payload.confidence,
                    model_id=payload.model_id,
                    created_at=now.isoformat(),
                    updated_at=now.isoformat(),
                )
                session.add(row)
            else:
                row.explanation_markdown = payload.explanation_markdown
                row.confidence = payload.confidence
            row.updated_at = now.isoformat()
            session.flush()
            return _to_assessment(row)

    def list_assessments(
        self,
        *,
        note_id: str | None = None,
        assessment_type: KnowledgeAssessmentType | None = None,
        limit: int = 100,
    ) -> list[KnowledgeAssessmentRecord]:
        with self._session_factory() as session:
            statement = select(KnowledgeAssessmentRow)
            if note_id is not None:
                statement = statement.where(
                    or_(
                        KnowledgeAssessmentRow.from_note_id == note_id,
                        KnowledgeAssessmentRow.to_note_id == note_id,
                    )
                )
            if assessment_type is not None:
                statement = statement.where(
                    KnowledgeAssessmentRow.assessment_type == assessment_type
                )
            rows = session.scalars(
                statement.order_by(KnowledgeAssessmentRow.updated_at.desc()).limit(limit)
            ).all()
            return [_to_assessment(row) for row in rows]

    def neighborhood(self, note_id: str) -> KnowledgeNeighborhood:
        with self._session_factory() as session:
            center_row = _require_note(session, note_id)
            link_rows = session.scalars(
                select(KnowledgeLinkRow).where(
                    or_(
                        KnowledgeLinkRow.from_note_id == note_id,
                        KnowledgeLinkRow.to_note_id == note_id,
                    )
                )
            ).all()
            assessment_rows = session.scalars(
                select(KnowledgeAssessmentRow).where(
                    or_(
                        KnowledgeAssessmentRow.from_note_id == note_id,
                        KnowledgeAssessmentRow.to_note_id == note_id,
                    )
                )
            ).all()
            neighbor_ids = {
                row.to_note_id if row.from_note_id == note_id else row.from_note_id
                for row in [*link_rows, *assessment_rows]
            }
            note_rows = (
                session.scalars(
                    select(KnowledgeNoteRow).where(
                        KnowledgeNoteRow.knowledge_note_id.in_(neighbor_ids)
                    )
                ).all()
                if neighbor_ids
                else []
            )
            return KnowledgeNeighborhood(
                center=_to_note(session, center_row),
                notes=[_to_note(session, row) for row in note_rows],
                links=[_to_link(row) for row in link_rows],
                assessments=[_to_assessment(row) for row in assessment_rows],
            )


def _validate_evidence(
    session: Session,
    source_ids: list[str],
    resource_ids: list[str],
    comment_ids: list[str],
) -> None:
    for source_id in source_ids:
        if session.get(SourceRow, source_id) is None:
            raise ValueError(f"Source {source_id} does not exist")
    for resource_id in resource_ids:
        if session.get(ResourceRow, resource_id) is None:
            raise ValueError(f"Resource {resource_id} does not exist")
    for comment_id in comment_ids:
        if session.get(CommentRow, comment_id) is None:
            raise ValueError(f"Comment {comment_id} does not exist")


def _replace_evidence(
    session: Session,
    note_id: str,
    source_ids: list[str],
    resource_ids: list[str],
    comment_ids: list[str],
) -> None:
    rows = session.scalars(
        select(KnowledgeNoteEvidenceRow).where(
            KnowledgeNoteEvidenceRow.knowledge_note_id == note_id
        )
    ).all()
    for row in rows:
        session.delete(row)
    for evidence_type, target_ids in (
        ("source", source_ids),
        ("resource", resource_ids),
        ("comment", comment_ids),
    ):
        for target_id in target_ids:
            session.add(
                KnowledgeNoteEvidenceRow(
                    evidence_id=f"knev_{uuid.uuid4().hex}",
                    knowledge_note_id=note_id,
                    evidence_type=evidence_type,
                    target_id=target_id,
                )
            )
    session.flush()


def _expand_evidence(
    session: Session,
    source_ids: list[str],
    resource_ids: list[str],
    comment_ids: list[str],
) -> tuple[list[str], list[str], list[str]]:
    expanded_sources = list(source_ids)
    expanded_resources = list(resource_ids)
    for comment_id in comment_ids:
        comment = session.get(CommentRow, comment_id)
        if comment is None:
            continue
        reference = session.get(KnowledgeRefRow, comment.knowledge_ref_id)
        if reference is None:
            continue
        for source_id in json.loads(reference.source_ids_json):
            if source_id not in expanded_sources:
                expanded_sources.append(source_id)
        for resource_id in json.loads(reference.resource_ids_json):
            if resource_id not in expanded_resources:
                expanded_resources.append(resource_id)
    for resource_id in expanded_resources:
        resource = session.get(ResourceRow, resource_id)
        if resource is not None and resource.source_id not in expanded_sources:
            expanded_sources.append(resource.source_id)
    return expanded_sources, expanded_resources, list(comment_ids)


def _evidence_by_type(session: Session, note_id: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {"source": [], "resource": [], "comment": []}
    rows = session.scalars(
        select(KnowledgeNoteEvidenceRow)
        .where(KnowledgeNoteEvidenceRow.knowledge_note_id == note_id)
        .order_by(
            KnowledgeNoteEvidenceRow.evidence_type,
            KnowledgeNoteEvidenceRow.target_id,
        )
    ).all()
    for row in rows:
        result[row.evidence_type].append(row.target_id)
    return result


def _require_note(session: Session, note_id: str) -> KnowledgeNoteRow:
    row = session.get(KnowledgeNoteRow, note_id)
    if row is None:
        raise KeyError(note_id)
    return row


def _note_hash(title: str, claim: str, body_markdown: str, tags: list[str]) -> str:
    canonical = json.dumps(
        {
            "title": title,
            "claim": claim,
            "body_markdown": body_markdown,
            "tags": tags,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"


def _to_note(session: Session, row: KnowledgeNoteRow) -> KnowledgeNoteRecord:
    evidence = _evidence_by_type(session, row.knowledge_note_id)
    return KnowledgeNoteRecord(
        knowledge_note_id=row.knowledge_note_id,
        title=row.title,
        claim=row.claim,
        body_markdown=row.body_markdown,
        tags=json.loads(row.tags_json),
        source_ids=evidence["source"],
        resource_ids=evidence["resource"],
        comment_ids=evidence["comment"],
        status=row.status,  # type: ignore[arg-type]
        origin=row.origin,  # type: ignore[arg-type]
        content_hash=row.content_hash,
        revision=row.revision,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


def _to_link(row: KnowledgeLinkRow) -> KnowledgeLinkRecord:
    return KnowledgeLinkRecord(
        knowledge_link_id=row.knowledge_link_id,
        from_note_id=row.from_note_id,
        to_note_id=row.to_note_id,
        kind=row.kind,  # type: ignore[arg-type]
        origin=row.origin,  # type: ignore[arg-type]
        created_at=datetime.fromisoformat(row.created_at),
    )


def _to_assessment(row: KnowledgeAssessmentRow) -> KnowledgeAssessmentRecord:
    return KnowledgeAssessmentRecord(
        knowledge_assessment_id=row.knowledge_assessment_id,
        from_note_id=row.from_note_id,
        to_note_id=row.to_note_id,
        assessment_type=row.assessment_type,  # type: ignore[arg-type]
        explanation_markdown=row.explanation_markdown,
        confidence=row.confidence,
        model_id=row.model_id,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


_WIKILINK_PATTERN = re.compile(r"\[\[(kn_[0-9a-f]{32})(?:\|[^\]]+)?\]\]")
_PAGE_EMBED_PATTERN = re.compile(r"\{\{knowledge-page:(kn_[0-9a-f]{32})\}\}")


def extract_knowledge_note_ids(markdown: str) -> list[str]:
    """Extract stable Atlas links and live embeds without a desktop-vault dependency."""
    return list(
        dict.fromkeys(
            [*_WIKILINK_PATTERN.findall(markdown), *_PAGE_EMBED_PATTERN.findall(markdown)]
        )
    )


def _sync_markdown_links(session: Session, from_note_id: str, markdown: str, now: datetime) -> None:
    target_ids = {
        note_id
        for note_id in extract_knowledge_note_ids(markdown)
        if note_id != from_note_id and session.get(KnowledgeNoteRow, note_id) is not None
    }
    existing = session.scalars(
        select(KnowledgeLinkRow).where(
            KnowledgeLinkRow.from_note_id == from_note_id,
            KnowledgeLinkRow.kind == "related",
            KnowledgeLinkRow.origin == "markdown",
        )
    ).all()
    existing_by_target = {row.to_note_id: row for row in existing}
    for target_id, row in existing_by_target.items():
        if target_id not in target_ids:
            session.delete(row)
    for target_id in target_ids - existing_by_target.keys():
        session.add(
            KnowledgeLinkRow(
                knowledge_link_id=f"kln_{uuid.uuid4().hex}",
                from_note_id=from_note_id,
                to_note_id=target_id,
                kind="related",
                origin="markdown",
                created_at=now.isoformat(),
            )
        )
    session.flush()


def _dump_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)
