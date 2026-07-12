from fastapi.testclient import TestClient

from atlas.config import AuthSettings, Settings, Sub2ApiSettings, get_settings
from atlas.main import create_app
from atlas.sub2api import Sub2ApiAccountsResponse, save_sub2api_snapshot


def make_client(sub2api: Sub2ApiSettings | None = None) -> TestClient:
    get_settings.cache_clear()
    settings = Settings(
        auth=AuthSettings(
            admin_password="correct-password",
            session_secret="test-session-secret",
        ),
        sub2api=sub2api or Sub2ApiSettings(enabled=False),
    )
    return TestClient(create_app(settings))


def test_protected_endpoint_requires_login() -> None:
    client = make_client()

    response = client.get("/api/system/summary")

    assert response.status_code == 401


def test_login_allows_access_to_system_summary() -> None:
    client = make_client()

    login_response = client.post("/api/auth/login", json={"password": "correct-password"})
    summary_response = client.get("/api/system/summary")

    assert login_response.status_code == 200
    assert login_response.json() == {"authenticated": True}
    assert summary_response.status_code == 200
    assert "cpu" in summary_response.json()


def test_wrong_password_is_rejected() -> None:
    client = make_client()

    response = client.post("/api/auth/login", json={"password": "wrong-password"})

    assert response.status_code == 401
    assert client.get("/api/system/summary").status_code == 401


def test_missing_password_uses_locked_default() -> None:
    client = TestClient(create_app(Settings()))

    login_response = client.post("/api/auth/login", json={"password": "anything"})
    protected_response = client.get("/api/system/summary")

    assert login_response.status_code == 503
    assert protected_response.status_code == 401


def test_sub2api_accounts_requires_login() -> None:
    client = make_client()

    response = client.get("/api/sub2api/accounts")

    assert response.status_code == 401


def test_sub2api_accounts_returns_disabled_when_configured() -> None:
    client = make_client()

    client.post("/api/auth/login", json={"password": "correct-password"})
    response = client.get("/api/sub2api/accounts")

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"



def test_sub2api_accounts_reads_snapshot_without_live_collection(tmp_path, monkeypatch) -> None:
    snapshot_path = tmp_path / "snapshots.sqlite3"
    save_sub2api_snapshot(
        snapshot_path,
        Sub2ApiAccountsResponse(
            status="ok",
            source="sub2api-postgres",
            summary={"total": 0, "ready": 0, "attention": 0},
            accounts=[],
        ),
    )

    async def fail_live_collection(_settings):
        raise AssertionError("GET should read the local snapshot, not collect live data")

    monkeypatch.setattr("atlas.sub2api.collect_sub2api_accounts", fail_live_collection)
    client = make_client(Sub2ApiSettings(snapshot_database_path=snapshot_path))
    client.post("/api/auth/login", json={"password": "correct-password"})

    response = client.get("/api/sub2api/accounts")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_sub2api_refresh_requires_login(tmp_path) -> None:
    client = make_client(Sub2ApiSettings(snapshot_database_path=tmp_path / "snapshots.sqlite3"))

    response = client.post("/api/sub2api/accounts/refresh")

    assert response.status_code == 401


def test_sub2api_refresh_returns_disabled_when_configured() -> None:
    client = make_client()
    client.post("/api/auth/login", json={"password": "correct-password"})

    response = client.post("/api/sub2api/accounts/refresh")

    assert response.status_code == 200
    assert response.json() == {"status": "disabled", "scheduled": False, "refreshing": False}


def test_login_rate_limiter_blocks_after_max_failures() -> None:
    from atlas.rate_limit import LoginRateLimiter

    client = make_client()
    # Patch the module-level singleton with a low threshold for testing.
    import atlas.main as main_mod

    original = main_mod.login_rate_limiter
    main_mod.login_rate_limiter = LoginRateLimiter(max_failures=3, block_seconds=600)
    try:
        for _ in range(3):
            client.post("/api/auth/login", json={"password": "wrong"})

        response = client.post("/api/auth/login", json={"password": "wrong"})
        assert response.status_code == 429
        assert "Too many" in response.json()["detail"]
    finally:
        main_mod.login_rate_limiter = original


def test_login_rate_limiter_allows_after_success() -> None:
    from atlas.rate_limit import LoginRateLimiter

    client = make_client()
    import atlas.main as main_mod

    original = main_mod.login_rate_limiter
    main_mod.login_rate_limiter = LoginRateLimiter(max_failures=3, block_seconds=600)
    try:
        # Two failures (below threshold)
        client.post("/api/auth/login", json={"password": "wrong"})
        client.post("/api/auth/login", json={"password": "wrong"})
        # Successful login resets the counter
        client.post("/api/auth/login", json={"password": "correct-password"})
        # Two more failures should not trigger block
        client.post("/api/auth/login", json={"password": "wrong"})
        response = client.post("/api/auth/login", json={"password": "wrong"})
        assert response.status_code == 401  # not 429
    finally:
        main_mod.login_rate_limiter = original
