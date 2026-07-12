from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from atlas.db.session import create_sqlite_session_factory

from .models import AgentRecord, AgentRegistration, AgentRegistrationResponse
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
        record, scoped_token = self._repository.upsert(registration, current_time)
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


def create_agent_service(database_path: Path, heartbeat_ttl_seconds: int) -> AgentService:
    session_factory = create_sqlite_session_factory(database_path)
    return AgentService(
        repository=AgentRepository(session_factory),
        heartbeat_ttl_seconds=heartbeat_ttl_seconds,
    )
