from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from atlas.db.base import Base
from atlas.knowledge.repository import KnowledgeNoteRow, extract_knowledge_note_ids

from .models import (
    DocumentCreate,
    DocumentRecord,
    DocumentUpdate,
    DocumentVersionCreate,
    DocumentVersionRecord,
    ProjectCreate,
    ProjectDetail,
    ProjectRecord,
    ProjectStatus,
    ProjectUpdate,
    WorkItemCreate,
    WorkItemRecord,
    WorkItemUpdate,
)


class AuthoringProjectRow(Base):
    __tablename__ = "authoring_projects"

    project_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    goal: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    audience: Mapped[str] = mapped_column(Text, default="")
    deadline: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)


class WorkItemRow(Base):
    __tablename__ = "work_items"

    work_item_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    due_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)


class DocumentRow(Base):
    __tablename__ = "documents"

    document_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(128), index=True)
    title: Mapped[str] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), index=True)
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(64), index=True)
    updated_at: Mapped[str] = mapped_column(String(64), index=True)


class DocumentKnowledgeLinkRow(Base):
    __tablename__ = "document_knowledge_links"

    link_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(128), index=True)
    knowledge_note_id: Mapped[str] = mapped_column(String(128), index=True)


class DocumentVersionRow(Base):
    __tablename__ = "document_versions"

    document_version_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    document_id: Mapped[str] = mapped_column(String(128), index=True)
    revision: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(Text)
    body_markdown: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[str] = mapped_column(String(64), index=True)


class AuthoringRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_project(self, payload: ProjectCreate, now: datetime) -> ProjectRecord:
        with self._session_factory() as session, session.begin():
            row = AuthoringProjectRow(
                project_id=f"prj_{uuid.uuid4().hex}",
                title=payload.title,
                goal=payload.goal,
                description=payload.description,
                audience=payload.audience,
                deadline=payload.deadline.isoformat() if payload.deadline else None,
                status="active",
                revision=1,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
            session.add(row)
            session.flush()
            return _project(row)

    def list_projects(
        self, status: ProjectStatus | None = None, limit: int = 100
    ) -> list[ProjectRecord]:
        with self._session_factory() as session:
            statement = select(AuthoringProjectRow)
            if status is not None:
                statement = statement.where(AuthoringProjectRow.status == status)
            rows = session.scalars(
                statement.order_by(AuthoringProjectRow.updated_at.desc()).limit(limit)
            ).all()
            return [_project(row) for row in rows]

    def get_project(self, project_id: str) -> ProjectDetail:
        with self._session_factory() as session:
            row = _require_project(session, project_id)
            work_items = session.scalars(
                select(WorkItemRow)
                .where(WorkItemRow.project_id == project_id)
                .order_by(WorkItemRow.created_at)
            ).all()
            documents = session.scalars(
                select(DocumentRow)
                .where(DocumentRow.project_id == project_id)
                .order_by(DocumentRow.updated_at.desc())
            ).all()
            return ProjectDetail(
                project=_project(row),
                work_items=[_work_item(item) for item in work_items],
                documents=[_document(session, item) for item in documents],
            )

    def update_project(
        self, project_id: str, payload: ProjectUpdate, now: datetime
    ) -> ProjectRecord:
        with self._session_factory() as session, session.begin():
            row = _require_project(session, project_id)
            _check_revision("Project", row.revision, payload.expected_revision)
            for field in ("title", "goal", "description", "audience", "status"):
                if field in payload.model_fields_set:
                    value = getattr(payload, field)
                    if value is not None:
                        setattr(row, field, value)
            if "deadline" in payload.model_fields_set:
                row.deadline = payload.deadline.isoformat() if payload.deadline else None
            row.revision += 1
            row.updated_at = now.isoformat()
            session.flush()
            return _project(row)

    def create_work_item(self, payload: WorkItemCreate, now: datetime) -> WorkItemRecord:
        with self._session_factory() as session, session.begin():
            _require_project(session, payload.project_id)
            if payload.document_id:
                _require_document(session, payload.document_id, payload.project_id)
            row = WorkItemRow(
                work_item_id=f"wi_{uuid.uuid4().hex}",
                project_id=payload.project_id,
                title=payload.title,
                description=payload.description,
                document_id=payload.document_id,
                due_at=payload.due_at.isoformat() if payload.due_at else None,
                status="todo",
                revision=1,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
            session.add(row)
            session.flush()
            return _work_item(row)

    def update_work_item(
        self, work_item_id: str, payload: WorkItemUpdate, now: datetime
    ) -> WorkItemRecord:
        with self._session_factory() as session, session.begin():
            row = session.get(WorkItemRow, work_item_id)
            if row is None:
                raise KeyError(work_item_id)
            _check_revision("WorkItem", row.revision, payload.expected_revision)
            for field in ("title", "description", "status"):
                if field in payload.model_fields_set:
                    value = getattr(payload, field)
                    if value is not None:
                        setattr(row, field, value)
            if "document_id" in payload.model_fields_set:
                if payload.document_id:
                    _require_document(session, payload.document_id, row.project_id)
                row.document_id = payload.document_id
            if "due_at" in payload.model_fields_set:
                row.due_at = payload.due_at.isoformat() if payload.due_at else None
            row.revision += 1
            row.updated_at = now.isoformat()
            session.flush()
            return _work_item(row)

    def create_document(self, payload: DocumentCreate, now: datetime) -> DocumentRecord:
        with self._session_factory() as session, session.begin():
            project = _require_project(session, payload.project_id)
            row = DocumentRow(
                document_id=f"doc_{uuid.uuid4().hex}",
                project_id=payload.project_id,
                title=payload.title,
                body_markdown=payload.body_markdown,
                status="draft",
                content_hash=_hash_document(payload.title, payload.body_markdown),
                revision=1,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
            )
            session.add(row)
            project.updated_at = now.isoformat()
            session.flush()
            _sync_document_links(session, row)
            return _document(session, row)

    def get_document(self, document_id: str) -> DocumentRecord:
        with self._session_factory() as session:
            return _document(session, _require_document(session, document_id))

    def update_document(
        self, document_id: str, payload: DocumentUpdate, now: datetime
    ) -> DocumentRecord:
        with self._session_factory() as session, session.begin():
            row = _require_document(session, document_id)
            _check_revision("Document", row.revision, payload.expected_revision)
            for field in ("title", "body_markdown", "status"):
                if field in payload.model_fields_set:
                    value = getattr(payload, field)
                    if value is not None:
                        setattr(row, field, value)
            row.content_hash = _hash_document(row.title, row.body_markdown)
            row.revision += 1
            row.updated_at = now.isoformat()
            session.flush()
            if "body_markdown" in payload.model_fields_set:
                _sync_document_links(session, row)
            return _document(session, row)

    def create_version(
        self, document_id: str, payload: DocumentVersionCreate, now: datetime
    ) -> DocumentVersionRecord:
        with self._session_factory() as session, session.begin():
            document = _require_document(session, document_id)
            row = DocumentVersionRow(
                document_version_id=f"dver_{uuid.uuid4().hex}",
                document_id=document_id,
                revision=document.revision,
                label=payload.label.strip(),
                title=document.title,
                body_markdown=document.body_markdown,
                content_hash=document.content_hash,
                created_at=now.isoformat(),
            )
            session.add(row)
            session.flush()
            return _version(row)

    def list_versions(self, document_id: str) -> list[DocumentVersionRecord]:
        with self._session_factory() as session:
            _require_document(session, document_id)
            rows = session.scalars(
                select(DocumentVersionRow)
                .where(DocumentVersionRow.document_id == document_id)
                .order_by(DocumentVersionRow.created_at.desc())
            ).all()
            return [_version(row) for row in rows]


def _require_project(session: Session, project_id: str) -> AuthoringProjectRow:
    row = session.get(AuthoringProjectRow, project_id)
    if row is None:
        raise KeyError(project_id)
    return row


def _require_document(
    session: Session, document_id: str, project_id: str | None = None
) -> DocumentRow:
    row = session.get(DocumentRow, document_id)
    if row is None or (project_id is not None and row.project_id != project_id):
        raise KeyError(document_id)
    return row


def _check_revision(label: str, current: int, expected: int) -> None:
    if current != expected:
        raise ValueError(f"{label} revision conflict: expected {expected}, current {current}")


def _sync_document_links(session: Session, document: DocumentRow) -> None:
    existing = session.scalars(
        select(DocumentKnowledgeLinkRow).where(
            DocumentKnowledgeLinkRow.document_id == document.document_id
        )
    ).all()
    for row in existing:
        session.delete(row)
    for note_id in extract_knowledge_note_ids(document.body_markdown):
        if session.get(KnowledgeNoteRow, note_id) is not None:
            session.add(
                DocumentKnowledgeLinkRow(
                    link_id=f"dkl_{uuid.uuid4().hex}",
                    document_id=document.document_id,
                    knowledge_note_id=note_id,
                )
            )
    session.flush()


def _linked_note_ids(session: Session, document_id: str) -> list[str]:
    return list(
        session.scalars(
            select(DocumentKnowledgeLinkRow.knowledge_note_id)
            .where(DocumentKnowledgeLinkRow.document_id == document_id)
            .order_by(DocumentKnowledgeLinkRow.knowledge_note_id)
        ).all()
    )


def _hash_document(title: str, body: str) -> str:
    canonical = title.encode() + b"\0" + body.encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _project(row: AuthoringProjectRow) -> ProjectRecord:
    from datetime import date

    return ProjectRecord(
        project_id=row.project_id,
        title=row.title,
        goal=row.goal,
        description=row.description,
        audience=row.audience,
        deadline=date.fromisoformat(row.deadline) if row.deadline else None,
        status=row.status,  # type: ignore[arg-type]
        revision=row.revision,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


def _work_item(row: WorkItemRow) -> WorkItemRecord:
    return WorkItemRecord(
        work_item_id=row.work_item_id,
        project_id=row.project_id,
        title=row.title,
        description=row.description,
        document_id=row.document_id,
        due_at=datetime.fromisoformat(row.due_at) if row.due_at else None,
        status=row.status,  # type: ignore[arg-type]
        revision=row.revision,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


def _document(session: Session, row: DocumentRow) -> DocumentRecord:
    return DocumentRecord(
        document_id=row.document_id,
        project_id=row.project_id,
        title=row.title,
        body_markdown=row.body_markdown,
        status=row.status,  # type: ignore[arg-type]
        linked_knowledge_note_ids=_linked_note_ids(session, row.document_id),
        content_hash=row.content_hash,
        revision=row.revision,
        created_at=datetime.fromisoformat(row.created_at),
        updated_at=datetime.fromisoformat(row.updated_at),
    )


def _version(row: DocumentVersionRow) -> DocumentVersionRecord:
    return DocumentVersionRecord(
        document_version_id=row.document_version_id,
        document_id=row.document_id,
        revision=row.revision,
        label=row.label,
        title=row.title,
        body_markdown=row.body_markdown,
        content_hash=row.content_hash,
        created_at=datetime.fromisoformat(row.created_at),
    )
