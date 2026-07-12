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


def register_agent(client: TestClient, agent_id: str) -> None:
    response = client.post(
        "/api/agents/register",
        headers=agent_headers(),
        json={"agent_id": agent_id, "name": agent_id},
    )
    assert response.status_code == 200


def send_message(client: TestClient, from_agent_id: str, to_agent_id: str) -> dict:
    response = client.post(
        "/api/messages",
        headers=agent_headers(),
        json={
            "from_agent_id": from_agent_id,
            "to_agent_id": to_agent_id,
            "kind": "prompt",
            "body": "please inspect the failing job",
            "metadata": {"priority": "normal"},
        },
    )
    assert response.status_code == 200
    return response.json()


def test_message_send_requires_bearer_token(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/messages",
        json={
            "from_agent_id": "mac-dev",
            "to_agent_id": "amax-prod",
            "body": "hello",
        },
    )

    assert response.status_code == 401


def test_agent_can_send_message_and_target_can_poll_inbox(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    register_agent(client, "mac-dev")
    register_agent(client, "amax-prod")

    created = send_message(client, "mac-dev", "amax-prod")
    inbox_response = client.get(
        "/api/agents/amax-prod/messages/inbox",
        headers=agent_headers(),
    )

    assert created["from_agent_id"] == "mac-dev"
    assert created["to_agent_id"] == "amax-prod"
    assert created["status"] == "pending"
    assert created["body"] == "please inspect the failing job"
    assert created["metadata"] == {"priority": "normal"}
    assert inbox_response.status_code == 200
    inbox = inbox_response.json()
    assert [message["message_id"] for message in inbox] == [created["message_id"]]


def test_target_agent_can_claim_and_ack_message(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    register_agent(client, "mac-dev")
    register_agent(client, "amax-prod")
    created = send_message(client, "mac-dev", "amax-prod")

    claim_response = client.post(
        f"/api/messages/{created['message_id']}/claim",
        headers=agent_headers(),
        json={"agent_id": "amax-prod"},
    )
    ack_response = client.post(
        f"/api/messages/{created['message_id']}/ack",
        headers=agent_headers(),
        json={"agent_id": "amax-prod", "result": "investigation queued"},
    )

    assert claim_response.status_code == 200
    assert claim_response.json()["status"] == "claimed"
    assert claim_response.json()["claimed_by"] == "amax-prod"
    assert ack_response.status_code == 200
    assert ack_response.json()["status"] == "acknowledged"
    assert ack_response.json()["result"] == "investigation queued"


def test_non_target_agent_cannot_claim_message(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    register_agent(client, "mac-dev")
    register_agent(client, "amax-prod")
    created = send_message(client, "mac-dev", "amax-prod")

    response = client.post(
        f"/api/messages/{created['message_id']}/claim",
        headers=agent_headers(),
        json={"agent_id": "mac-dev"},
    )

    assert response.status_code == 403


def test_dashboard_can_read_message_after_login(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    register_agent(client, "mac-dev")
    register_agent(client, "amax-prod")
    created = send_message(client, "mac-dev", "amax-prod")
    login(client)

    response = client.get(f"/api/messages/{created['message_id']}")

    assert response.status_code == 200
    assert response.json()["message_id"] == created["message_id"]


def test_dashboard_message_read_requires_login(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/messages/missing")

    assert response.status_code == 401
