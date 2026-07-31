from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from atlas.db.session import create_sqlite_session_factory

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
    RenderedDocument,
    WorkItemCreate,
    WorkItemRecord,
    WorkItemUpdate,
)
from .repository import AuthoringRepository


class AuthoringService:
    def __init__(self, repository: AuthoringRepository) -> None:
        self._repository = repository

    def create_project(self, payload: ProjectCreate) -> ProjectRecord:
        return self._repository.create_project(payload, _now())

    def list_projects(
        self, status: ProjectStatus | None = None, limit: int = 100
    ) -> list[ProjectRecord]:
        return self._repository.list_projects(status, limit)

    def get_project(self, project_id: str) -> ProjectDetail:
        return self._repository.get_project(project_id)

    def update_project(self, project_id: str, payload: ProjectUpdate) -> ProjectRecord:
        return self._repository.update_project(project_id, payload, _now())

    def create_work_item(self, payload: WorkItemCreate) -> WorkItemRecord:
        return self._repository.create_work_item(payload, _now())

    def update_work_item(self, work_item_id: str, payload: WorkItemUpdate) -> WorkItemRecord:
        return self._repository.update_work_item(work_item_id, payload, _now())

    def create_document(self, payload: DocumentCreate) -> DocumentRecord:
        return self._repository.create_document(payload, _now())

    def get_document(self, document_id: str) -> DocumentRecord:
        return self._repository.get_document(document_id)

    def render_document(self, document_id: str) -> RenderedDocument:
        return self._repository.render_document(document_id)

    def update_document(self, document_id: str, payload: DocumentUpdate) -> DocumentRecord:
        return self._repository.update_document(document_id, payload, _now())

    def create_version(
        self, document_id: str, payload: DocumentVersionCreate
    ) -> DocumentVersionRecord:
        return self._repository.create_version(document_id, payload, _now())

    def list_versions(self, document_id: str) -> list[DocumentVersionRecord]:
        return self._repository.list_versions(document_id)


def create_authoring_service(database_path: Path) -> AuthoringService:
    return AuthoringService(AuthoringRepository(create_sqlite_session_factory(database_path)))


def _now() -> datetime:
    return datetime.now(UTC)
