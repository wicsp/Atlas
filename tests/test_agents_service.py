from datetime import UTC, datetime, timedelta
from pathlib import Path

from atlas.agents.models import AgentRegistration
from atlas.agents.service import create_agent_service


def make_service(tmp_path: Path, heartbeat_ttl_seconds: int = 60):
    return create_agent_service(
        database_path=tmp_path / "atlas.sqlite3",
        heartbeat_ttl_seconds=heartbeat_ttl_seconds,
    )


def test_register_agent_upserts_existing_agent(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    now = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)

    first = service.register_agent(
        AgentRegistration(
            agent_id="mac-dev",
            name="Mac Dev",
            capabilities=["messages:send"],
            metadata={"host": "mac"},
        ),
        now=now,
    )
    # M2.5: register returns AgentRegistrationResponse with scoped_token.
    assert first.agent_id == "mac-dev"
    assert first.scoped_token.startswith("at2_")

    updated = service.register_agent(
        AgentRegistration(
            agent_id="mac-dev",
            name="Mac Development",
            capabilities=["messages:send", "tasks:claim"],
            metadata={"host": "mac", "role": "dev"},
        ),
        now=now + timedelta(seconds=10),
    )
    # Re-registration returns the same scoped_token (None update, so no new token).
    assert updated.agent_id == "mac-dev"

    # Verify the updated agent via list_agents (returns full AgentRecord).
    agents = service.list_agents(now=now + timedelta(seconds=10))
    agent = agents[0]
    assert agent.agent_id == "mac-dev"
    assert agent.name == "Mac Development"
    assert agent.capabilities == ["messages:send", "tasks:claim"]
    assert agent.metadata == {"host": "mac", "role": "dev"}
    assert agent.registered_at == now
    assert agent.last_seen_at == now + timedelta(seconds=10)


def test_heartbeat_refreshes_last_seen_at(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    registered_at = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)
    heartbeat_at = registered_at + timedelta(seconds=30)
    service.register_agent(
        AgentRegistration(agent_id="amax-prod", name="Amax Prod"),
        now=registered_at,
    )

    agent = service.record_heartbeat("amax-prod", now=heartbeat_at)

    assert agent.agent_id == "amax-prod"
    assert agent.registered_at == registered_at
    assert agent.last_seen_at == heartbeat_at
    assert agent.online is True


def test_agents_are_offline_after_heartbeat_ttl(tmp_path: Path) -> None:
    service = make_service(tmp_path, heartbeat_ttl_seconds=60)
    registered_at = datetime(2026, 7, 6, 9, 0, tzinfo=UTC)
    service.register_agent(
        AgentRegistration(agent_id="amax-prod", name="Amax Prod"),
        now=registered_at,
    )

    agents = service.list_agents(now=registered_at + timedelta(seconds=61))

    assert agents[0].online is False


def test_heartbeat_unknown_agent_raises_not_found(tmp_path: Path) -> None:
    service = make_service(tmp_path)

    try:
        service.record_heartbeat("missing-agent", now=datetime(2026, 7, 6, tzinfo=UTC))
    except KeyError as exc:
        assert exc.args == ("missing-agent",)
    else:
        raise AssertionError("Expected missing heartbeat target to raise KeyError")
