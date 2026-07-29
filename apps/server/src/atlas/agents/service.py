from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from atlas.db.session import create_sqlite_session_factory

from .models import (
    AgentRecord,
    AgentRegistration,
    AgentRegistrationResponse,
    RunnerRecord,
    RunnerRegistration,
    RunnerRegistrationResponse,
)
from .repository import AgentRepository


class AgentService:
    def __init__(self, repository: AgentRepository, heartbeat_ttl_seconds: int) -> None:
        self._repository = repository
        self._heartbeat_ttl = timedelta(seconds=heartbeat_ttl_seconds)

    def register_agent(
        self,
        registration: AgentRegistration,
        now: datetime | None = None,
    ) -> AgentRegistrationResponse:
        current_time = now or datetime.now(UTC)
        canonical_registration = registration.model_copy(
            update={"agent_id": _canonical_agent_id(registration)}
        )
        record, scoped_token = self._repository.upsert(canonical_registration, current_time)
        agent = self._with_online_status(record, now=current_time)
        return AgentRegistrationResponse(
            agent_id=agent.agent_id,
            scoped_token=scoped_token or "",
        )

    def record_heartbeat(self, agent_id: str, now: datetime | None = None) -> AgentRecord:
        current_time = now or datetime.now(UTC)
        return self._with_online_status(
            self._repository.touch(agent_id, current_time),
            now=current_time,
        )

    def register_runner(
        self,
        registration: RunnerRegistration,
        now: datetime | None = None,
    ) -> RunnerRegistrationResponse:
        """Persist runners through the v3 identity store during the compatibility phase."""
        metadata = {
            **registration.metadata,
            "identity_kind": "runner",
            "protocol_version": "atlas-runner-v1",
            "node": registration.node.model_dump(),
            "executors": [executor.model_dump() for executor in registration.executors],
            "available_grants": registration.available_grants,
        }
        response = self.register_agent(
            AgentRegistration(
                agent_id=registration.runner_id,
                name=registration.name,
                capabilities=registration.legacy_capabilities,
                metadata=metadata,
            ),
            now=now,
        )
        return RunnerRegistrationResponse(
            runner_id=response.agent_id,
            scoped_token=response.scoped_token,
        )

    def record_runner_heartbeat(
        self, runner_id: str, now: datetime | None = None
    ) -> RunnerRecord:
        return _to_runner(self.record_heartbeat(runner_id, now=now))

    def list_runners(self, now: datetime | None = None) -> list[RunnerRecord]:
        current_time = now or datetime.now(UTC)
        return [
            _to_runner(self._with_online_status(record, now=current_time))
            for record in self._repository.list_unarchived_runners()
        ]

    def archive_stale_runners(self, now: datetime | None = None) -> int:
        current_time = now or datetime.now(UTC)
        return self._repository.archive_stale_lumio_runners(
            current_time,
            older_than=self._heartbeat_ttl,
        )

    def resolve_agent(self, token: str) -> AgentRecord | None:
        return self._repository.find_by_scoped_token(token)

    def list_agents(self, now: datetime | None = None) -> list[AgentRecord]:
        current_time = now or datetime.now(UTC)
        return [
            self._with_online_status(agent, now=current_time)
            for agent in self._repository.list()
        ]

    def _with_online_status(self, agent: AgentRecord, now: datetime) -> AgentRecord:
        return agent.model_copy(
            update={"online": now - agent.last_seen_at <= self._heartbeat_ttl},
        )


def _canonical_agent_id(registration: AgentRegistration) -> str:
    """Derive an opaque v3 ID while keeping legacy registrations compatible."""
    metadata = registration.metadata
    identity = {
        "node_id": metadata.get("node_id"),
        "agent_kind": metadata.get("agent_kind"),
        "executor": metadata.get("executor"),
        "runtime": metadata.get("runtime"),
        "instance_id": metadata.get("instance_id"),
    }
    if metadata.get("protocol_version") != "atlas-agent-v3":
        return registration.agent_id
    if not all(isinstance(value, str) and value.strip() for value in identity.values()):
        return registration.agent_id
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"agt_{digest[:24]}"


def create_agent_service(database_path: Path, heartbeat_ttl_seconds: int) -> AgentService:
    session_factory = create_sqlite_session_factory(database_path)
    return AgentService(
        repository=AgentRepository(session_factory),
        heartbeat_ttl_seconds=heartbeat_ttl_seconds,
    )


def _to_runner(record: AgentRecord) -> RunnerRecord:
    if record.metadata.get("identity_kind") != "runner":
        raise ValueError(f"Identity {record.agent_id} is not a runner")
    return RunnerRecord(
        runner_id=record.agent_id,
        name=record.name,
        node=record.metadata.get("node", {}),
        executors=record.metadata.get("executors", []),
        available_grants=record.metadata.get("available_grants", []),
        metadata={
            key: value
            for key, value in record.metadata.items()
            if key
            not in {
                "identity_kind",
                "protocol_version",
                "node",
                "executors",
                "available_grants",
            }
        },
        registered_at=record.registered_at,
        last_seen_at=record.last_seen_at,
        online=record.online,
    )
