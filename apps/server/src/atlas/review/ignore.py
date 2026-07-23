from __future__ import annotations

import json
import uuid
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
from atlas.work.models import EXECUTION_CONTRACT_METADATA_KEY
from atlas.work.repository import (
    ArtifactContentRow,
    ArtifactRow,
    EventRow,
    ProjectRow,
    RunRow,
)
from atlas.work.service import WorkService
from atlas.workflows.catalog import builtin_step_contract

from .models import ResourceIgnoreResponse

IGNORED_RESOURCE_LIMIT = 10
REVIEW_PROJECT_ID = "resource-review"
CLEANUP_JOB_NAME = "vortex-resource-purge-v1"
_PREVIOUS_STATUS_KEY = "_atlas_review_status_before_ignore"


@dataclass(frozen=True)
class IgnoreMutation:
    resource: ResourceRecord
    evicted_resource_ids: list[str]
    cleanup_run_ids: list[str]


class ResourceIgnoreRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def ignore(self, resource_id: str, now: datetime) -> IgnoreMutation:
        with self._session_factory() as session, session.begin():
            resource = session.get(ResourceRow, resource_id)
            if resource is None:
                raise KeyError(resource_id)
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
            overflow = ignored[IGNORED_RESOURCE_LIMIT:]
            manifests_by_source: dict[str, list[dict[str, Any]]] = {}
            for expired in overflow:
                manifests_by_source.setdefault(expired.source_id, []).append(
                    _evict_resource(session, expired)
                )

            cleanup_run_ids = [
                _enqueue_cleanup(session, source_id, manifest, now)
                for source_id, manifest in sorted(manifests_by_source.items())
            ]
            session.flush()
            return IgnoreMutation(
                resource=_to_resource(resource),
                evicted_resource_ids=sorted(item.resource_id for item in overflow),
                cleanup_run_ids=cleanup_run_ids,
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
            return IgnoreMutation(
                resource=_to_resource(resource),
                evicted_resource_ids=[],
                cleanup_run_ids=[],
            )


class ResourceIgnoreService:
    def __init__(self, repository: ResourceIgnoreRepository, work: WorkService) -> None:
        self._repository = repository
        self._work = work

    def ignore(self, resource_id: str) -> ResourceIgnoreResponse:
        return self._response(self._repository.ignore(resource_id, datetime.now(UTC)))

    def restore(self, resource_id: str) -> ResourceIgnoreResponse:
        return self._response(self._repository.restore(resource_id, datetime.now(UTC)))

    def _response(self, mutation: IgnoreMutation) -> ResourceIgnoreResponse:
        return ResourceIgnoreResponse(
            resource=mutation.resource,
            evicted_resource_ids=mutation.evicted_resource_ids,
            cleanup_runs=[
                self._work.get_run(run_id) for run_id in mutation.cleanup_run_ids
            ],
        )


def create_resource_ignore_service(
    database_path: Path,
    work: WorkService,
) -> ResourceIgnoreService:
    session_factory = create_sqlite_session_factory(database_path)
    return ResourceIgnoreService(ResourceIgnoreRepository(session_factory), work)


def _evict_resource(session: Session, resource: ResourceRow) -> dict[str, Any]:
    remove_comment = False
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
            remove_comment = True
            session.delete(comment)
            session.delete(knowledge_ref)
            continue
        knowledge_ref.resource_ids_json = _dump_json(
            [item for item in resource_ids if item != resource.resource_id]
        )

    artifact = session.get(ArtifactRow, resource.artifact_id)
    artifact_manifest: dict[str, Any] | None = None
    if artifact is not None:
        shared = session.scalars(
            select(ResourceRow)
            .where(ResourceRow.artifact_id == artifact.artifact_id)
            .where(ResourceRow.resource_id != resource.resource_id)
        ).first()
        if shared is None:
            artifact_manifest = {
                "artifact_id": artifact.artifact_id,
                "uri": artifact.uri,
                "checksum": artifact.checksum,
                "size_bytes": artifact.size_bytes,
            }
            inline_content = session.get(ArtifactContentRow, artifact.artifact_id)
            if inline_content is not None:
                session.delete(inline_content)
            session.delete(artifact)

    manifest = {
        "resource_id": resource.resource_id,
        "kind": resource.kind,
        "artifact": artifact_manifest,
        "remove_comment": remove_comment,
    }
    session.delete(resource)
    return manifest


def _enqueue_cleanup(
    session: Session,
    source_id: str,
    resources: list[dict[str, Any]],
    now: datetime,
) -> str:
    project = session.get(ProjectRow, REVIEW_PROJECT_ID)
    if project is None:
        session.add(
            ProjectRow(
                project_id=REVIEW_PROJECT_ID,
                name="Resource Review",
                description="Operator-requested, Mac-local Resource review actions.",
                created_at=now.isoformat(),
            )
        )
    run_id = f"run_{uuid.uuid4().hex}"
    workflow, step, requirements = builtin_step_contract(
        "vortex.resource-purge", "1", "purge"
    )
    session.add(
        RunRow(
            run_id=run_id,
            project_id=REVIEW_PROJECT_ID,
            job_name=CLEANUP_JOB_NAME,
            capabilities_json=_dump_json([]),
            input_json=_dump_json({"source_id": source_id, "resources": resources}),
            status="pending",
            agent_id=None,
            lease_expires_at=None,
            attempt_number=0,
            max_attempts=step.max_attempts,
            priority=step.priority,
            metadata_json=_dump_json(
                {
                    "requested_via": "ignored-resource-retention",
                    EXECUTION_CONTRACT_METADATA_KEY: {
                        "workflow": workflow.model_dump(),
                        "step_name": step.name,
                        "requirements": requirements.model_dump(),
                        "workflow_invocation_id": None,
                        "depends_on_run_ids": [],
                    },
                }
            ),
            error_message=None,
            created_at=now.isoformat(),
            started_at=None,
            completed_at=None,
        )
    )
    session.add(
        EventRow(
            event_id=f"evt_{uuid.uuid4().hex}",
            run_id=run_id,
            agent_id=None,
            event_type="enqueued",
            body="Ignored Resource retention expired; local cleanup requested",
            created_at=now.isoformat(),
        )
    )
    return run_id


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback
