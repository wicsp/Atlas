from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from atlas.config import Settings
from atlas.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    database = tmp_path / "atlas.sqlite3"
    settings = Settings(
        auth={"admin_password": "test", "session_secret": "secret"},
        agents={"database_path": database, "shared_token": "control"},
        work={"database_path": database, "lease_ttl_seconds": 30},
        scheduler={"enabled": False, "poll_interval_seconds": 30},
        sub2api={"enabled": False},
    )
    client = TestClient(create_app(settings))
    client.headers["Authorization"] = "Bearer control"
    return client


def register_runner(client: TestClient) -> TestClient:
    response = client.post(
        "/api/runners/register",
        json={
            "runner_id": "macsp.runner",
            "name": "macsp",
            "node": {"node_id": "macsp", "labels": ["local-data"]},
            "executors": [{"name": "script", "kind": "script"}],
            "available_grants": ["bilibili-cookie:read"],
        },
    )
    assert response.status_code == 200, response.text
    scoped = TestClient(client.app)
    scoped.headers["Authorization"] = f"Bearer {response.json()['scoped_token']}"
    return scoped


def test_daily_schedule_invokes_scan_once_and_fans_out_summary(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    schedules = client.get("/api/schedules")
    assert schedules.status_code == 200
    assert schedules.json()[0]["schedule_id"] == "bilibili-atlas-favorites-daily"

    coordinator = client.app.state.schedule_coordinator
    timezone = ZoneInfo("Asia/Shanghai")
    assert coordinator.tick(datetime(2026, 7, 22, 1, 59, tzinfo=timezone)) == []
    first = coordinator.tick(datetime(2026, 7, 22, 2, 0, tzinfo=timezone))
    assert len(first) == 1
    assert coordinator.tick(datetime(2026, 7, 22, 23, 0, tzinfo=timezone)) == []

    scoped = register_runner(client)
    claimed = scoped.get("/api/runs/next")
    assert claimed.status_code == 200
    scan = claimed.json()
    assert scan["workflow"]["name"] == "bilibili.favorites-scan"
    assert scan["requirements"]["node_ids"] == ["macsp"]

    completed = scoped.post(
        f"/api/runs/{scan['run_id']}/complete",
        json={
            "attempt_id": scan["attempt_id"],
            "claim_token": scan["claim_token"],
            "agent_id": "server-derived",
            "output": {
                "folder_name": "Atlas",
                "items": [
                    {
                        "bvid": "BV1abcdefghi",
                        "aid": 42,
                        "title": "Queued video",
                        "owner": "owner",
                        "duration_seconds": 120,
                    }
                ],
                "failed": [],
            },
        },
    )
    assert completed.status_code == 200, completed.text

    assert coordinator.reconcile_favorites() == 1
    assert coordinator.reconcile_favorites() == 0
    sources = client.get("/api/sources").json()
    assert sources[0]["source_key"] == "bilibili:BV1abcdefghi"
    runs = client.get("/api/runs?project_id=bilibili-capture&limit=10").json()
    assert {run["step_name"] for run in runs} == {"acquire", "summarize"}
    acquire = next(run for run in runs if run["step_name"] == "acquire")
    assert acquire["input"]["workflow_input"]["source_id"] == sources[0]["source_id"]
