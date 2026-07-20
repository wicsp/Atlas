from pathlib import Path

from fastapi.testclient import TestClient

from atlas.config import AuthSettings, Settings, Sub2ApiSettings
from atlas.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        auth=AuthSettings(
            admin_password="correct-password",
            session_secret="test-session-secret",
        ),
        sub2api=Sub2ApiSettings(enabled=False),
    )
    client = TestClient(create_app(settings))
    client.app.state.todo_store_path = tmp_path / "todos.json"
    return client


def login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"password": "correct-password"})
    assert response.status_code == 200


def test_todos_require_login(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/todos")

    assert response.status_code == 401


def test_todo_crud_is_persisted_to_backend_store(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    store_path = client.app.state.todo_store_path
    login(client)

    create_response = client.post("/api/todos", json={"text": "  check atlas panel  "})
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["text"] == "check atlas panel"
    assert created["done"] is False
    assert store_path.exists()

    list_response = client.get("/api/todos")
    assert list_response.status_code == 200
    assert list_response.json() == [created]

    update_response = client.patch(f"/api/todos/{created['id']}", json={"done": True})
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["done"] is True
    assert updated["text"] == "check atlas panel"

    persisted_response = client.get("/api/todos")
    assert persisted_response.status_code == 200
    assert persisted_response.json()[0]["done"] is True

    delete_response = client.delete(f"/api/todos/{created['id']}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"deleted": True}
    assert client.get("/api/todos").json() == []


def test_todo_missing_id_returns_404(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    patch_response = client.patch("/api/todos/missing", json={"done": True})
    delete_response = client.delete("/api/todos/missing")

    assert patch_response.status_code == 404
    assert delete_response.status_code == 404


def test_empty_todo_text_is_rejected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    response = client.post("/api/todos", json={"text": "   "})

    assert response.status_code == 422
