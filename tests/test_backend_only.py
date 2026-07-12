from fastapi.testclient import TestClient

from atlas.config import AuthSettings, Settings, Sub2ApiSettings
from atlas.main import create_app


def test_atlas_package_serves_backend_health() -> None:
    client = TestClient(create_app(Settings(sub2api=Sub2ApiSettings(enabled=False))))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unknown_frontend_path_is_not_served_by_backend() -> None:
    settings = Settings(
        auth=AuthSettings(
            admin_password="correct-password",
            session_secret="test-session-secret",
        ),
        sub2api=Sub2ApiSettings(enabled=False),
    )
    client = TestClient(create_app(settings))

    response = client.get("/dashboard")

    assert response.status_code == 404
