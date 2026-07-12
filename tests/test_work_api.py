"""Work API tests — Milestone 2: Reliable work execution."""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.config import Settings
from atlas.main import create_app


@pytest.fixture
def atlas_app(tmp_path) -> FastAPI:
    db = str(tmp_path / "atlas.sqlite3")
    settings = Settings(
        auth={"admin_password": "test", "session_secret": "secret"},
        agents={"database_path": db, "shared_token": "test-token"},
        work={"database_path": db, "lease_ttl_seconds": 5},
    )
    return create_app(settings)


@pytest.fixture
def agent_client(atlas_app: FastAPI) -> TestClient:
    client = TestClient(atlas_app)
    client.headers["Authorization"] = "Bearer test-token"
    return client


@pytest.fixture
def session_client(atlas_app: FastAPI) -> TestClient:
    """An authenticated dashboard client."""
    client = TestClient(atlas_app)
    res = client.post("/api/auth/login", json={"password": "test"})
    assert res.status_code == 200, res.text
    return client


def _create_project(agent_client: TestClient, project_id: str, name: str) -> dict:
    res = agent_client.post("/api/projects", json={"project_id": project_id, "name": name})
    assert res.status_code == 200, res.text
    return res.json()


def _enqueue_run(agent_client: TestClient, project_id: str, job_name: str, **kwargs) -> dict:
    payload = {"project_id": project_id, "job_name": job_name, **kwargs}
    res = agent_client.post("/api/runs/enqueue", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


class TestProjects:
    def test_create_and_list(self, agent_client, session_client):
        _create_project(agent_client, "m2", "M2 Test")
        res = session_client.get("/api/projects")
        assert res.status_code == 200
        projects = res.json()
        assert any(p["project_id"] == "m2" for p in projects)

    def test_create_requires_agent_auth(self, atlas_app):
        client = TestClient(atlas_app)
        res = client.post("/api/projects", json={"project_id": "x", "name": "X"})
        assert res.status_code == 401

    def test_duplicate_project_id_fails(self, agent_client):
        """project_id is a primary key - duplicates raise IntegrityError."""
        _create_project(agent_client, "dup", "First")
        with pytest.raises(Exception):
            agent_client.post("/api/projects", json={"project_id": "dup", "name": "Second"})
class TestRunLifecycle:
    def test_enqueue_claim_complete(self, agent_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "hello-world", input={"msg": "hello"})
        run_id = run["run_id"]
        assert run["status"] == "pending"
        assert run["attempt_number"] == 0

        # Claim
        res = agent_client.post(f"/api/runs/{run_id}/claim?agent_id=test-agent")
        assert res.status_code == 200, res.text
        claimed = res.json()
        assert claimed["status"] == "claimed"
        assert claimed["agent_id"] == "test-agent"
        assert claimed["attempt_number"] == 1

        # Heartbeat
        res = agent_client.post(f"/api/runs/{run_id}/heartbeat?agent_id=test-agent")
        assert res.status_code == 200

        # Complete with artifacts
        res = agent_client.post(
            f"/api/runs/{run_id}/complete",
            json={
                "agent_id": "test-agent",
                "output": {"result": "done"},
                "artifacts": [
                    {"name": "output.txt", "uri": "file:///tmp/out.txt", "size_bytes": 42}
                ],
            },
        )
        assert res.status_code == 200, res.text
        completed = res.json()
        assert completed["status"] == "completed"
        assert completed["output"] == {"result": "done"}

        # Verify via session client
        res = session_client.get(f"/api/runs/{run_id}")
        assert res.status_code == 200
        assert res.json()["status"] == "completed"

    def test_enqueue_claim_fail(self, agent_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "fail-job")
        agent_client.post(f"/api/runs/{run['run_id']}/claim?agent_id=agent-f")
        res = agent_client.post(
            f"/api/runs/{run['run_id']}/fail",
            json={"agent_id": "agent-f", "error_message": "something broke"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "failed"

    def test_cannot_claim_already_claimed(self, agent_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "busy")
        agent_client.post(f"/api/runs/{run['run_id']}/claim?agent_id=a1")
        res = agent_client.post(f"/api/runs/{run['run_id']}/claim?agent_id=a2")
        assert res.status_code == 409

    def test_cannot_complete_with_wrong_agent(self, agent_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "owner")
        agent_client.post(f"/api/runs/{run['run_id']}/claim?agent_id=owner")
        res = agent_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"agent_id": "intruder", "output": {}},
        )
        assert res.status_code == 409

    def test_run_not_found(self, agent_client):
        res = agent_client.post("/api/runs/nonexistent/claim?agent_id=a")
        assert res.status_code == 404

    def test_events_recorded(self, agent_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "eventful")
        agent_client.post(f"/api/runs/{run['run_id']}/claim?agent_id=evt-a")
        agent_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"agent_id": "evt-a", "output": {}},
        )

        res = session_client.get(f"/api/runs/{run['run_id']}/events")
        assert res.status_code == 200
        events = res.json()
        event_types = [e["event_type"] for e in events]
        assert "enqueued" in event_types
        assert "claimed" in event_types
        assert "completed" in event_types

    def test_artifacts(self, agent_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "artifact-producer")
        agent_client.post(f"/api/runs/{run['run_id']}/claim?agent_id=art-a")
        agent_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={
                "agent_id": "art-a",
                "output": {},
                "artifacts": [
                    {"name": "log.txt", "uri": "file:///tmp/log.txt", "content_type": "text/plain"},
                    {"name": "data.json", "uri": "s3://bucket/data.json", "checksum": "sha256:abc"},
                ],
            },
        )

        res = session_client.get(f"/api/runs/{run['run_id']}/artifacts")
        assert res.status_code == 200
        arts = res.json()
        assert len(arts) == 2
        names = {a["name"] for a in arts}
        assert names == {"log.txt", "data.json"}


class TestClaimNext:
    def test_claim_next_with_capabilities(self, agent_client):
        _create_project(agent_client, "m2", "M2")
        _enqueue_run(agent_client, "m2", "needs-gpu", capabilities_required=["gpu"], priority=5)
        _enqueue_run(agent_client, "m2", "cpu-only", capabilities_required=[], priority=1)

        res = agent_client.get("/api/runs/next?agent_id=gpu-agent&capabilities=gpu,cpu")
        assert res.status_code == 200
        run = res.json()
        assert run is not None
        assert run["job_name"] == "needs-gpu"

    def test_claim_next_no_matching_capabilities(self, agent_client):
        _create_project(agent_client, "m2", "M2")
        _enqueue_run(agent_client, "m2", "needs-gpu", capabilities_required=["gpu"])

        res = agent_client.get("/api/runs/next?agent_id=cpu-agent&capabilities=cpu")
        assert res.status_code == 200
        assert res.json() is None

    def test_claim_next_priority_order(self, agent_client):
        _create_project(agent_client, "m2", "M2")
        _enqueue_run(agent_client, "m2", "low", priority=1)
        _enqueue_run(agent_client, "m2", "high", priority=10)

        res = agent_client.get("/api/runs/next?agent_id=a")
        run = res.json()
        assert run is not None
        assert run["job_name"] == "high"

    def test_claim_next_returns_none_when_empty(self, agent_client):
        _create_project(agent_client, "m2", "M2")
        res = agent_client.get("/api/runs/next?agent_id=a")
        assert res.json() is None


class TestLeaseExpiry:
    def test_lease_expires_stale_claim(self, agent_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "lease-test")

        agent_client.post(f"/api/runs/{run['run_id']}/claim?agent_id=ghost")

        # Wait for lease to expire
        time.sleep(6)

        # find_next_pending should expire the stale claim
        res = agent_client.get("/api/runs/next?agent_id=new-agent")
        assert res.status_code == 200
        # The run should be available again
        claimed = res.json()
        assert claimed is not None
        assert claimed["job_name"] == "lease-test"
        assert claimed["attempt_number"] == 2

    def test_cancel_run(self, agent_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "cancel-me")
        agent_client.post(f"/api/runs/{run['run_id']}/claim?agent_id=a")

        res = session_client.post(f"/api/runs/{run['run_id']}/cancel")
        assert res.status_code == 200
        assert res.json()["status"] == "cancelled"

    def test_cancel_terminal_run_fails(self, agent_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "done")
        agent_client.post(f"/api/runs/{run['run_id']}/claim?agent_id=a")
        agent_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"agent_id": "a", "output": {}},
        )

        res = session_client.post(f"/api/runs/{run['run_id']}/cancel")
        assert res.status_code == 409


class TestListing:
    def test_list_runs_by_project(self, agent_client, session_client):
        _create_project(agent_client, "p1", "P1")
        _create_project(agent_client, "p2", "P2")
        _enqueue_run(agent_client, "p1", "j1")
        _enqueue_run(agent_client, "p2", "j2")

        res = session_client.get("/api/runs?project_id=p1")
        assert res.status_code == 200
        runs = res.json()
        assert len(runs) >= 1
        assert all(r["project_id"] == "p1" for r in runs)

    def test_list_runs_by_status(self, agent_client, session_client):
        _create_project(agent_client, "m2", "M2")
        r1 = _enqueue_run(agent_client, "m2", "j1")
        _enqueue_run(agent_client, "m2", "j2")

        agent_client.post(f"/api/runs/{r1['run_id']}/claim?agent_id=a")
        agent_client.post(
            f"/api/runs/{r1['run_id']}/complete",
            json={"agent_id": "a", "output": {}},
        )

        res = session_client.get("/api/runs?project_id=m2&status_str=pending")
        assert res.status_code == 200
        runs = res.json()
        pending = [r for r in runs if r["status"] == "pending"]
        assert len(pending) >= 1
