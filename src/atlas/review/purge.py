from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from atlas.content.repository import KnowledgeRefRow, ResourceRow, SourceRow
from atlas.db.session import create_sqlite_session_factory
from atlas.work.repository import ArtifactRow, EventRow, ProjectRow, RunRow
from atlas.work.service import WorkService

from .models import PurgeSourceResponse

REVIEW_PROJECT_ID = "resource-review"
PURGE_JOB_NAME = "vortex-resource-purge-v1"
COMMENT_JOB_NAME = "vortex-comment-v1"


class ResourcePurgeConflictError(ValueError):
    """The Source's machine Resources cannot currently be purged."""


class NoResourcesToPurgeError(ValueError):
    """The Source exists but has no machine Resources."""


@dataclass(frozen=True)
class PurgeRequestResult:
    run_id: str
    resource_ids: list[str]
    reused: bool


class ResourcePurgeRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def request(self, source_id: str, now: datetime) -> PurgeRequestResult:
        with self._session_factory() as session, session.begin():
            if session.get(SourceRow, source_id) is None:
                raise KeyError(source_id)

            active_purge = next(
                (
                    row
                    for row in session.scalars(
                        select(RunRow)
                        .where(RunRow.job_name == PURGE_JOB_NAME)
                        .where(RunRow.status.in_(["pending", "claimed"]))
                        .order_by(RunRow.created_at.desc())
                    ).all()
                    if _load_json(row.input_json, {}).get("source_id") == source_id
                ),
                None,
            )
            if active_purge is not None:
                resource_ids = [
                    item["resource_id"]
                    for item in _load_json(active_purge.input_json, {}).get("resources", [])
                    if isinstance(item, dict) and isinstance(item.get("resource_id"), str)
                ]
                return PurgeRequestResult(active_purge.run_id, resource_ids, True)

            resources = session.scalars(
                select(ResourceRow)
                .where(ResourceRow.source_id == source_id)
                .order_by(ResourceRow.created_at)
            ).all()
            if not resources:
                raise NoResourcesToPurgeError(
                    f"Source {source_id} has no machine Resources to purge"
                )
            resource_ids = {resource.resource_id for resource in resources}

            referenced_by = next(
                (
                    row
                    for row in session.scalars(select(KnowledgeRefRow)).all()
                    if resource_ids.intersection(
                        _load_json(row.resource_ids_json, [])
                    )
                ),
                None,
            )
            if referenced_by is not None:
                raise ResourcePurgeConflictError(
                    f"Source {source_id} contains Resource evidence referenced by "
                    f"KnowledgeRef {referenced_by.knowledge_ref_id}"
                )

            active_comment = next(
                (
                    row
                    for row in session.scalars(
                        select(RunRow)
                        .where(RunRow.job_name == COMMENT_JOB_NAME)
                        .where(RunRow.status.in_(["pending", "claimed"]))
                    ).all()
                    if _load_json(row.input_json, {}).get("resource_id") in resource_ids
                ),
                None,
            )
            if active_comment is not None:
                raise ResourcePurgeConflictError(
                    f"Source {source_id} has active comment Run {active_comment.run_id}"
                )

            active_producer = next(
                (
                    row
                    for row in session.scalars(
                        select(RunRow).where(RunRow.status.in_(["pending", "claimed"]))
                    ).all()
                    if _load_json(row.input_json, {}).get("source_id") == source_id
                ),
                None,
            )
            if active_producer is not None:
                raise ResourcePurgeConflictError(
                    f"Source {source_id} has active producer Run {active_producer.run_id}"
                )

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

            manifest: list[dict[str, Any]] = []
            for resource in resources:
                artifact = session.get(ArtifactRow, resource.artifact_id)
                artifact_manifest: dict[str, Any] | None = None
                if artifact is not None:
                    shared = session.scalars(
                        select(ResourceRow)
                        .where(ResourceRow.artifact_id == artifact.artifact_id)
                        .where(ResourceRow.resource_id.not_in(resource_ids))
                    ).first()
                    if shared is None:
                        artifact_manifest = {
                            "artifact_id": artifact.artifact_id,
                            "uri": artifact.uri,
                            "checksum": artifact.checksum,
                            "size_bytes": artifact.size_bytes,
                        }
                        session.delete(artifact)
                manifest.append(
                    {
                        "resource_id": resource.resource_id,
                        "kind": resource.kind,
                        "artifact": artifact_manifest,
                    }
                )
                session.delete(resource)

            run_id = f"run_{uuid.uuid4().hex}"
            run_input = {"source_id": source_id, "resources": manifest}
            session.add(
                RunRow(
                    run_id=run_id,
                    project_id=REVIEW_PROJECT_ID,
                    job_name=PURGE_JOB_NAME,
                    capabilities_json=_dump_json([PURGE_JOB_NAME]),
                    input_json=_dump_json(run_input),
                    status="pending",
                    agent_id=None,
                    lease_expires_at=None,
                    attempt_number=0,
                    max_attempts=3,
                    priority=10,
                    metadata_json=_dump_json({"requested_via": "atlas-console"}),
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
                    body="Source machine Resources purged; local byte cleanup requested",
                    created_at=now.isoformat(),
                )
            )
            session.flush()
            return PurgeRequestResult(run_id, sorted(resource_ids), False)


class ResourcePurgeService:
    def __init__(self, repository: ResourcePurgeRepository, work: WorkService) -> None:
        self._repository = repository
        self._work = work

    def request(self, source_id: str) -> PurgeSourceResponse:
        result = self._repository.request(source_id, datetime.now(UTC))
        return PurgeSourceResponse(
            run=self._work.get_run(result.run_id),
            resource_ids=result.resource_ids,
            reused=result.reused,
        )


def create_resource_purge_service(
    database_path: Path,
    work: WorkService,
) -> ResourcePurgeService:
    session_factory = create_sqlite_session_factory(database_path)
    return ResourcePurgeService(ResourcePurgeRepository(session_factory), work)


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _load_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback
