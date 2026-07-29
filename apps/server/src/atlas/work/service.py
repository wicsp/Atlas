from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from atlas.agents.models import AgentRecord
from atlas.db.session import create_sqlite_session_factory

from .models import (
    ArtifactContentRecord,
    ArtifactRef,
    EventRecord,
    ExecutionAttemptRecord,
    ProjectCreate,
    ProjectRecord,
    RunCancel,
    RunComplete,
    RunCreate,
    RunFail,
    RunRecord,
    RunStatus,
    SchedulingProfile,
)
from .repository import WorkRepository


class WorkService:
    def __init__(
        self,
        repository: WorkRepository,
        lease_ttl_seconds: int = 120,
    ) -> None:
        self._repository = repository
        self._lease_ttl = timedelta(seconds=lease_ttl_seconds)

    # ── Projects ──────────────────────────────────────────────

    def create_project(self, payload: ProjectCreate) -> ProjectRecord:
        return self._repository.create_project(payload, _now())

    def list_projects(self) -> list[ProjectRecord]:
        return self._repository.list_projects()

    # ── Runs ──────────────────────────────────────────────────

    def enqueue_run(self, payload: RunCreate) -> RunRecord:
        return self._repository.create_run(payload, _now())

    def claim_next(self, agent: AgentRecord) -> (
        tuple[RunRecord, str, str] | None
    ):
        now = _now()
        lease = now + self._lease_ttl
        result = self._repository.claim_next_atomic(
            agent.agent_id,
            lease,
            now,
            agent.capabilities,
            _scheduling_profile(agent),
        )
        if result is None:
            return None
        return result.run, result.attempt_id, result.claim_token

    def claim_by_id(
        self, run_id: str, agent: AgentRecord
    ) -> tuple[RunRecord, str, str]:
        now = _now()
        lease = now + self._lease_ttl
        result = self._repository.claim_run(
            run_id,
            agent.agent_id,
            lease,
            now,
            agent.capabilities,
            _scheduling_profile(agent),
        )
        return result.run, result.attempt_id, result.claim_token

    def heartbeat(self, run_id: str, agent_id: str, attempt_id: str, claim_token: str) -> RunRecord:
        lease = _now() + self._lease_ttl
        return self._repository.heartbeat_run(
            run_id, agent_id, attempt_id, claim_token, lease, _now()
        )

    def complete(
        self,
        run_id: str,
        payload: RunComplete,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        return self._repository.complete_run(
            run_id,
            payload.attempt_id,
            payload.claim_token,
            payload.agent_id,
            payload.output,
            payload.artifacts,
            payload.source_updates,
            payload.resources,
            _now(),
            idempotency_key=idempotency_key,
            payload_digest=_payload_digest(payload) if idempotency_key else None,
        )

    def fail(
        self,
        run_id: str,
        payload: RunFail,
        idempotency_key: str | None = None,
    ) -> RunRecord:
        return self._repository.fail_run(
            run_id,
            payload.attempt_id,
            payload.claim_token,
            payload.agent_id,
            payload.error_code,
            payload.error_message,
            payload.retryable,
            _now(),
            idempotency_key=idempotency_key,
            payload_digest=_payload_digest(payload) if idempotency_key else None,
        )

    def cancel(self, run_id: str, payload: RunCancel) -> RunRecord:
        return self._repository.cancel_run(run_id, _now())

    def get_run(self, run_id: str) -> RunRecord:
        return self._repository.get_run(run_id)

    def list_runs(
        self,
        project_id: str | None = None,
        status: RunStatus | None = None,
        limit: int = 100,
    ) -> list[RunRecord]:
        return self._repository.list_runs(project_id=project_id, status=status, limit=limit)

    # ── Events ────────────────────────────────────────────────

    def list_events(self, run_id: str, limit: int = 200) -> list[EventRecord]:
        return self._repository.list_events(run_id, limit=limit)

    # ── Artifacts ─────────────────────────────────────────────

    def list_attempts(self, run_id: str) -> list[ExecutionAttemptRecord]:
        return self._repository.list_attempts(run_id)

    def list_artifacts(self, run_id: str) -> list[ArtifactRef]:
        return self._repository.list_artifacts(run_id)

    def get_artifact_content(self, artifact_id: str) -> ArtifactContentRecord:
        return self._repository.get_artifact_content(artifact_id)

    def upsert_artifact_content(
        self, artifact_id: str, content: str
    ) -> ArtifactContentRecord:
        return self._repository.upsert_artifact_content(artifact_id, content, _now())

    def upstream_context(self, run: RunRecord) -> dict[str, dict[str, Any]]:
        context: dict[str, dict[str, Any]] = {}
        for dependency_id in run.depends_on_run_ids:
            dependency = self.get_run(dependency_id)
            if dependency.status != "completed":
                raise ValueError(f"workflow dependency {dependency_id} is not completed")
            context[dependency_id] = {
                "output": dependency.output or {},
                "artifacts": [],
            }
            for artifact in self.list_artifacts(dependency_id):
                manifest = artifact.model_dump(mode="json")
                content = self._repository.find_artifact_content(artifact.artifact_id)
                if content is not None:
                    manifest["content"] = content.content
                context[dependency_id]["artifacts"].append(manifest)
        return context


def _now() -> datetime:
    return datetime.now(UTC)


def _payload_digest(payload: Any) -> str:
    """Produce a stable digest of a Pydantic model for idempotency."""
    raw = payload.model_dump_json()
    return hashlib.sha256(raw.encode()).hexdigest()


def _scheduling_profile(agent: AgentRecord) -> SchedulingProfile:
    metadata = agent.metadata
    node = metadata.get("node") if isinstance(metadata.get("node"), dict) else {}
    raw_executors = metadata.get("executors") if isinstance(metadata.get("executors"), list) else []
    executors = [
        descriptor.get("name")
        for descriptor in raw_executors
        if isinstance(descriptor, dict) and isinstance(descriptor.get("name"), str)
    ]
    return SchedulingProfile(
        identity_id=agent.agent_id,
        legacy_capabilities=agent.capabilities,
        is_runner=metadata.get("identity_kind") == "runner",
        node_id=node.get("node_id") if isinstance(node.get("node_id"), str) else None,
        executors=executors,
        node_labels=node.get("labels", []) if isinstance(node.get("labels"), list) else [],
        available_grants=(
            metadata.get("available_grants", [])
            if isinstance(metadata.get("available_grants"), list)
            else []
        ),
    )


def create_work_service(
    database_path: Path,
    lease_ttl_seconds: int = 120,
) -> WorkService:
    session_factory = create_sqlite_session_factory(database_path)
    return WorkService(
        repository=WorkRepository(session_factory),
        lease_ttl_seconds=lease_ttl_seconds,
    )
