from pathlib import Path

from fastapi.testclient import TestClient

from atlas.config import AgentSettings, AuthSettings, Settings, Sub2ApiSettings
from atlas.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        auth=AuthSettings(
            admin_password="correct-password",
            session_secret="test-session-secret",
        ),
        agents=AgentSettings(
            database_path=tmp_path / "atlas.sqlite3",
            shared_token="agent-secret",
            heartbeat_ttl_seconds=60,
        ),
        sub2api=Sub2ApiSettings(enabled=False),
    )
    return TestClient(create_app(settings))


def agent_headers(token: str = "agent-secret") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"password": "correct-password"})
    assert response.status_code == 200


def test_agent_registration_requires_bearer_token(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/agents/register",
        json={"agent_id": "mac-dev", "name": "Mac Dev"},
    )

    assert response.status_code == 401


def test_agent_registration_rejects_wrong_bearer_token(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/agents/register",
        headers=agent_headers("wrong-token"),
        json={"agent_id": "mac-dev", "name": "Mac Dev"},
    )

    assert response.status_code == 401


def test_agent_can_register_and_heartbeat(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    register_response = client.post(
        "/api/agents/register",
        headers=agent_headers(),
        json={
            "agent_id": "mac-dev",
            "name": "Mac Dev",
            "capabilities": ["messages:send", "tasks:claim"],
            "metadata": {"host": "mac"},
        },
    )
    heartbeat_response = client.post(
        "/api/agents/mac-dev/heartbeat",
        headers=agent_headers(),
    )

    assert register_response.status_code == 200
    # M2.5: registration returns agent_id + scoped_token.
    registered = register_response.json()
    assert registered["agent_id"] == "mac-dev"
    assert "scoped_token" in registered
    assert registered["scoped_token"].startswith("at2_")
    assert registered["protocol_version"] == "atlas-agent-v3"

    assert heartbeat_response.status_code == 200
    # Heartbeat returns full AgentRecord.
    hb = heartbeat_response.json()
    assert hb["agent_id"] == "mac-dev"
    assert hb["name"] == "Mac Dev"
    assert hb["capabilities"] == ["messages:send", "tasks:claim"]
    assert hb["metadata"] == {"host": "mac"}
    assert hb["online"] is True


def test_dashboard_can_list_registered_agents_after_login(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    client.post(
        "/api/agents/register",
        headers=agent_headers(),
        json={"agent_id": "amax-prod", "name": "Amax Prod"},
    )
    login(client)

    response = client.get("/api/agents")

    assert response.status_code == 200
    assert response.json()[0]["agent_id"] == "amax-prod"
    assert response.json()[0]["online"] is True


def test_agent_list_requires_dashboard_login(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/agents")

    assert response.status_code == 401


def test_runner_registration_separates_node_and_executors_from_business_capabilities(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    response = client.post(
        "/api/runners/register",
        headers=agent_headers(),
        json={
            "runner_id": "macsp.runner.pi-session",
            "name": "Pi runner on macsp",
            "node": {
                "node_id": "macsp",
                "os": "darwin",
                "labels": ["desktop", "local-data"],
            },
            "executors": [{"name": "pi", "kind": "agent", "version": "1.0"}],
            "available_grants": ["bilibili-cookie:read"],
            "legacy_capabilities": ["bilibili-summary-v4"],
            "metadata": {"distribution": "lumio"},
        },
    )

    assert response.status_code == 200, response.text
    registered = response.json()
    assert registered["runner_id"] == "macsp.runner.pi-session"
    assert registered["protocol_version"] == "atlas-runner-v1"
    assert registered["scoped_token"].startswith("at2_")

    heartbeat = client.post(
        "/api/runners/macsp.runner.pi-session/heartbeat",
        headers=agent_headers(),
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["node"]["node_id"] == "macsp"
    assert heartbeat.json()["executors"][0]["name"] == "pi"

    login(client)
    runners = client.get("/api/runners")
    assert runners.status_code == 200
    assert runners.json()[0]["metadata"] == {"distribution": "lumio"}
