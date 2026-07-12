from fastapi.testclient import TestClient

from atlas import dashboard, main
from atlas.config import AuthSettings, ProbeHistorySettings, ProbeTarget, Settings
from atlas.probes import ProbeHistorySummary
from atlas.system import CpuSummary, MemorySummary, SystemGlanceSummary


def make_client(settings: Settings | None = None) -> TestClient:
    if settings is None:
        settings = Settings(
            auth=AuthSettings(
                admin_password="correct-password",
                session_secret="test-session-secret",
            ),
        )
    return TestClient(main.create_app(settings))


def test_system_glance_requires_login() -> None:
    client = make_client()

    response = client.get("/api/system/glance")

    assert response.status_code == 401


def test_system_gpus_requires_login() -> None:
    client = make_client()

    response = client.get("/api/system/gpus")

    assert response.status_code == 401


def test_system_glance_returns_compact_summary(monkeypatch) -> None:
    def fake_glance() -> SystemGlanceSummary:
        return SystemGlanceSummary(
            timestamp="2026-05-25T00:00:00Z",
            uptime_seconds=120,
            cpu=CpuSummary(percent=12.5, count=8, load_average=(1.0, 2.0, 3.0)),
            memory=MemorySummary(
                total_bytes=100,
                used_bytes=25,
                available_bytes=75,
                percent=25.0,
            ),
            disks=[],
        )

    monkeypatch.setattr(dashboard, "get_system_glance_summary", fake_glance)
    client = make_client()
    client.post("/api/auth/login", json={"password": "correct-password"})

    response = client.get("/api/system/glance")

    assert response.status_code == 200
    assert response.json()["cpu"]["percent"] == 12.5
    assert "gpus" not in response.json()


def test_system_gpus_returns_gpu_list(monkeypatch) -> None:
    monkeypatch.setattr(dashboard, "get_gpu_summaries", lambda: [])
    client = make_client()
    client.post("/api/auth/login", json={"password": "correct-password"})

    response = client.get("/api/system/gpus")

    assert response.status_code == 200
    assert response.json() == []


def test_dashboard_snapshot_requires_login() -> None:
    client = make_client()

    response = client.get("/api/dashboard/snapshot")

    assert response.status_code == 401


def test_dashboard_snapshot_returns_cached_sections(monkeypatch) -> None:
    def fake_glance() -> SystemGlanceSummary:
        return SystemGlanceSummary(
            timestamp="2026-05-25T00:00:00Z",
            uptime_seconds=120,
            cpu=CpuSummary(percent=12.5, count=8, load_average=(1.0, 2.0, 3.0)),
            memory=MemorySummary(
                total_bytes=100,
                used_bytes=25,
                available_bytes=75,
                percent=25.0,
            ),
            disks=[],
        )

    monkeypatch.setattr(dashboard, "get_system_glance_summary", fake_glance)
    monkeypatch.setattr(dashboard, "get_gpu_summaries", lambda: [])
    client = make_client()
    client.post("/api/auth/login", json={"password": "correct-password"})

    response = client.get("/api/dashboard/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["system"]["cpu"]["percent"] == 12.5
    assert payload["gpus"] == []
    assert payload["system_meta"]["stale"] is False
    assert payload["probe_history"] == []


def test_probe_history_requires_login() -> None:
    client = make_client()

    response = client.get("/api/probes/history")

    assert response.status_code == 401


def test_probe_history_returns_configured_target_summaries(tmp_path, monkeypatch) -> None:
    settings = Settings(
        auth=AuthSettings(
            admin_password="correct-password",
            session_secret="test-session-secret",
        ),
        probes=[
            ProbeTarget(
                name="nexus",
                type="icmp",
                host="154.21.80.210",
            )
        ],
        probe_history=ProbeHistorySettings(database_path=tmp_path / "probe-history.sqlite3"),
    )

    def fake_history(*args, **kwargs):
        return [
            ProbeHistorySummary(
                name="nexus",
                target="154.21.80.210",
                window_hours=24,
                bucket_minutes=5,
                total_checks=2,
                up_checks=1,
                down_checks=1,
                uptime_percent=50.0,
                outage_count=1,
            )
        ]

    monkeypatch.setattr(dashboard, "get_probe_history_summaries", fake_history)
    client = make_client(settings)
    client.post("/api/auth/login", json={"password": "correct-password"})

    response = client.get("/api/probes/history")

    assert response.status_code == 200
    assert response.json()[0]["name"] == "nexus"
    assert response.json()[0]["uptime_percent"] == 50.0
