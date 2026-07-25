from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from atlas.db.session import create_sqlite_session_factory
from atlas.work.models import ProjectCreate, RunCancel, RunCreate, WorkflowRef
from atlas.work.service import WorkService

from .catalog import BUILTIN_WORKFLOWS
from .models import (
    WorkflowDefinitionCreate,
    WorkflowDefinitionRecord,
    WorkflowInvocationCreate,
    WorkflowInvocationRecord,
)
from .repository import WorkflowRepository


class WorkflowService:
    def __init__(self, repository: WorkflowRepository, work: WorkService) -> None:
        self._repository = repository
        self._work = work
        for definition in BUILTIN_WORKFLOWS:
            self.register_definition(definition)

    def register_definition(
        self, definition: WorkflowDefinitionCreate
    ) -> WorkflowDefinitionRecord:
        digest = hashlib.sha256(
            definition.model_dump_json().encode()
        ).hexdigest()
        return self._repository.register_definition(definition, f"sha256:{digest}", _now())

    def list_definitions(self) -> list[WorkflowDefinitionRecord]:
        return self._repository.list_definitions()

    def invoke(self, payload: WorkflowInvocationCreate) -> WorkflowInvocationRecord:
        return self._invoke(payload, f"wfi_{uuid.uuid4().hex}", deterministic=False)

    def invoke_once(
        self,
        payload: WorkflowInvocationCreate,
        idempotency_key: str,
    ) -> WorkflowInvocationRecord:
        """Invoke a workflow once for one deterministic control-plane occurrence."""
        digest = hashlib.sha256(idempotency_key.encode()).hexdigest()
        return self._invoke(payload, f"wfi_{digest[:32]}", deterministic=True)

    def _invoke(
        self,
        payload: WorkflowInvocationCreate,
        invocation_id: str,
        *,
        deterministic: bool,
    ) -> WorkflowInvocationRecord:
        existing = self._repository.find_invocation(invocation_id)
        if existing is not None:
            if (
                existing.workflow_name != payload.workflow_name
                or existing.workflow_version != payload.workflow_version
                or existing.input != payload.input
            ):
                raise ValueError("workflow invocation idempotency key conflicts with existing data")
            return existing
        definition = self._repository.get_definition(
            payload.workflow_name, payload.workflow_version
        )
        self._work.create_project(
            ProjectCreate(
                project_id=definition.project_id,
                name=definition.project_id.replace("-", " ").title(),
                description=f"Runs for {definition.name}@{definition.version}.",
            )
        )
        run_ids = {
            step.name: (
                "run_"
                + hashlib.sha256(f"{invocation_id}:{step.name}".encode()).hexdigest()[:32]
                if deterministic
                else f"run_{uuid.uuid4().hex}"
            )
            for step in definition.steps
        }
        for step in definition.steps:
            if deterministic:
                try:
                    self._work.get_run(run_ids[step.name])
                    continue
                except KeyError:
                    pass
            dependencies = [run_ids[name] for name in step.depends_on]
            self._work.enqueue_run(
                RunCreate(
                    run_id=run_ids[step.name],
                    project_id=definition.project_id,
                    job_name=step.name,
                    input={
                        "workflow_input": payload.input,
                        "upstream_runs": {
                            name: run_ids[name] for name in step.depends_on
                        },
                    },
                    max_attempts=step.max_attempts,
                    priority=step.priority,
                    workflow=WorkflowRef(
                        name=definition.name,
                        version=definition.version,
                        digest=definition.digest,
                    ),
                    step_name=step.name,
                    requirements=step.requirements,
                    workflow_invocation_id=invocation_id,
                    depends_on_run_ids=dependencies,
                    initial_status="blocked" if dependencies else "pending",
                )
            )
        return self._repository.create_invocation_with_id(
            invocation_id, payload, definition, run_ids, _now()
        )

    def get_invocation(self, invocation_id: str) -> WorkflowInvocationRecord:
        invocation = self._repository.get_invocation(invocation_id)
        if invocation.status != "running":
            return invocation
        statuses = [
            self._work.get_run(run_id).status for run_id in invocation.step_runs.values()
        ]
        if statuses and all(status == "completed" for status in statuses):
            return self._repository.set_invocation_status(invocation_id, "completed", _now())
        if any(status in {"failed", "cancelled"} for status in statuses):
            invocation = self._repository.set_invocation_status(invocation_id, "failed", _now())
            for run_id in invocation.step_runs.values():
                try:
                    run = self._work.get_run(run_id)
                    if run.status in ("blocked", "pending"):
                        self._work.cancel(run_id, RunCancel())
                except Exception:
                    pass
            return invocation
        return invocation


def create_workflow_service(database_path: Path, work: WorkService) -> WorkflowService:
    return WorkflowService(
        WorkflowRepository(create_sqlite_session_factory(database_path)),
        work,
    )


def _now() -> datetime:
    return datetime.now(UTC)
