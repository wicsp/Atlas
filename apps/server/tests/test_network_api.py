from fastapi.testclient import TestClient

from atlas import dashboard, main
from atlas.config import AuthSettings, Settings
from atlas.network import ConnectivityResult, NetworkConnectivity


def make_client() -> TestClient:
    settings = Settings(
        auth=AuthSettings(
            admin_password="correct-password",
            session_secret="test-session-secret",
        ),
    )
    return TestClient(main.create_app(settings))


def test_network_connectivity_requires_login() -> None:
    client = make_client()

    response = client.get("/api/network/connectivity")

    assert response.status_code == 401


def test_network_connectivity_returns_domestic_and_international(monkeypatch) -> None:
    async def fake_connectivity() -> NetworkConnectivity:
        return NetworkConnectivity(
            domestic=ConnectivityResult(
                label="Domestic",
                target="https://domestic.example.test",
                status="up",
                latency_ms=12.3,
            ),
            international=ConnectivityResult(
                label="International",
                target="https://international.example.test",
                status="down",
                error="connection failed",
            ),
        )

    monkeypatch.setattr(dashboard, "get_network_connectivity", fake_connectivity)
    client = make_client()

    login_response = client.post("/api/auth/login", json={"password": "correct-password"})
    response = client.get("/api/network/connectivity")

    assert login_response.status_code == 200
    assert response.status_code == 200
    assert response.json()["domestic"]["status"] == "up"
    assert response.json()["international"]["status"] == "down"
