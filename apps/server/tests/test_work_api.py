"""Work API tests — Phase 1 (M2.5) + P0-1 (idempotency)."""

from __future__ import annotations

import time
import uuid

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
    """Client authenticated with the shared token (for registration and project creation)."""
    client = TestClient(atlas_app)
    client.headers["Authorization"] = "Bearer test-token"
    return client


def _register_and_get_scoped(atlas_app: FastAPI, agent_id: str = "test-agent",
    capabilities: list[str] | None = None,
) -> tuple[TestClient, str]:
    """Register an agent and return a client with its scoped token + the token string."""
    client = TestClient(atlas_app)
    client.headers["Authorization"] = "Bearer test-token"
    caps = capabilities or ["testing"]
    res = client.post("/api/agents/register", json={
        "agent_id": agent_id,
        "name": f"Agent {agent_id}",
        "capabilities": caps,
    })
    assert res.status_code == 200, f"Register failed: {res.text}"
    scoped_token = res.json()["scoped_token"]
    assert scoped_token, "Expected scoped_token in registration response"
    scoped = TestClient(atlas_app)
    scoped.headers["Authorization"] = f"Bearer {scoped_token}"
    return scoped, scoped_token


@pytest.fixture
def scoped_client(atlas_app: FastAPI) -> TestClient:
    """Client authenticated with a scoped token (for work operations)."""
    client, _ = _register_and_get_scoped(atlas_app)
    return client


@pytest.fixture
def session_client(atlas_app: FastAPI) -> TestClient:
    """An authenticated dashboard client."""
    client = TestClient(atlas_app)
    res = client.post("/api/auth/login", json={"password": "test"})
    assert res.status_code == 200, res.text
    return client


def _create_project(client: TestClient, project_id: str, name: str) -> dict:
    res = client.post("/api/projects", json={"project_id": project_id, "name": name})
    assert res.status_code == 200, res.text
    return res.json()


def _enqueue_run(client: TestClient, project_id: str, job_name: str, **kwargs) -> dict:
    payload = {"project_id": project_id, "job_name": job_name, **kwargs}
    res = client.post("/api/runs/enqueue", json=payload)
    assert res.status_code == 200, res.text
    return res.json()


def _claim(client, run: dict) -> tuple[str, str]:
    """Claim a run via by-id endpoint, return (attempt_id, claim_token)."""
    res = client.post(f"/api/runs/{run['run_id']}/claim")
    assert res.status_code == 200, f"Claim failed: {res.text}"
    data = res.json()
    return data["attempt_id"], data["claim_token"]


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

    def test_duplicate_project_id_is_an_idempotent_upsert(self, agent_client):
        _create_project(agent_client, "dup", "First")
        response = agent_client.post(
            "/api/projects", json={"project_id": "dup", "name": "Second"}
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Second"


class TestRunLifecycle:
    def test_enqueue_claim_complete(self, agent_client, scoped_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "hello-world", input={"msg": "hello"})
        run_id = run["run_id"]
        assert run["status"] == "pending"
        assert run["attempt_number"] == 0

        # Claim via scoped client
        res = scoped_client.post(f"/api/runs/{run_id}/claim")
        assert res.status_code == 200, res.text
        claimed = res.json()
        assert claimed["status"] == "claimed"
        assert claimed["agent_id"] == "test-agent"
        assert claimed["attempt_number"] == 1
        aid = claimed["attempt_id"]
        ct = claimed["claim_token"]

        # Heartbeat
        res = scoped_client.post(
            f"/api/runs/{run_id}/heartbeat",
            json={"attempt_id": aid, "claim_token": ct},
        )
        assert res.status_code == 200

        # Complete with artifacts
        res = scoped_client.post(
            f"/api/runs/{run_id}/complete",
            json={
                "attempt_id": aid,
                "claim_token": ct,
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

    def test_enqueue_claim_fail(self, agent_client, scoped_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "fail-job")
        aid, ct = _claim(scoped_client, run)
        res = scoped_client.post(
            f"/api/runs/{run['run_id']}/fail",
            json={"attempt_id": aid, "claim_token": ct, "agent_id": "test-agent", "error_message": "something broke"},  # noqa: E501
        )
        assert res.status_code == 200
        assert res.json()["status"] == "failed"

    def test_cannot_claim_already_claimed(self, agent_client, scoped_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "busy")
        scoped_client.post(f"/api/runs/{run['run_id']}/claim")
        res = scoped_client.post(f"/api/runs/{run['run_id']}/claim")
        assert res.status_code == 409

    def test_cannot_complete_with_wrong_agent(self, agent_client, scoped_client, atlas_app):
        """A second agent's scoped token cannot complete another agent's run."""
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "owner")
        aid, ct = _claim(scoped_client, run)

        # Register a second agent to get a different scoped token.
        intruder, _ = _register_and_get_scoped(atlas_app, agent_id="intruder", capabilities=[])

        res = intruder.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"attempt_id": aid, "claim_token": ct, "agent_id": "intruder", "output": {}},
        )
        assert res.status_code == 409

    def test_cannot_complete_pending_run(self, agent_client, scoped_client):
        """M2.5: pending runs cannot be completed — must be claimed first."""
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "skip-claim")
        # No claim — pending run, complete should fail on missing valid attempt_id
        # Use a dummy attempt_id since it's a pending run (no real attempt exists)
        res = scoped_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"attempt_id": "attempt_nonexistent", "claim_token": "dummy", "agent_id": "test-agent", "output": {}},  # noqa: E501
        )
        assert res.status_code == 409, f"Expected 409, got {res.status_code}: {res.text}"

    def test_run_not_found(self, scoped_client):
        res = scoped_client.post("/api/runs/nonexistent/claim")
        assert res.status_code == 404

    def test_events_recorded(self, agent_client, scoped_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "eventful")
        aid, ct = _claim(scoped_client, run)
        scoped_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"attempt_id": aid, "claim_token": ct, "agent_id": "test-agent", "output": {}},
        )

        res = session_client.get(f"/api/runs/{run['run_id']}/events")
        assert res.status_code == 200
        events = res.json()
        event_types = [e["event_type"] for e in events]
        assert "enqueued" in event_types
        assert "claimed" in event_types
        assert "completed" in event_types

    def test_artifacts(self, agent_client, scoped_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "artifact-producer")
        aid, ct = _claim(scoped_client, run)
        scoped_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={
                "attempt_id": aid,
                "claim_token": ct,
                "agent_id": "test-agent",
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
    def test_claim_next_with_capabilities(self, agent_client, atlas_app):
        _create_project(agent_client, "m2", "M2")
        _enqueue_run(agent_client, "m2", "needs-gpu", capabilities_required=["gpu"], priority=5)
        _enqueue_run(agent_client, "m2", "cpu-only", capabilities_required=[], priority=1)

        scoped, _ = _register_and_get_scoped(atlas_app, capabilities=["gpu", "cpu"])
        res = scoped.get("/api/runs/next?capabilities=gpu,cpu")
        assert res.status_code == 200
        run = res.json()
        assert run is not None
        assert run["job_name"] == "needs-gpu"

    def test_claim_next_no_matching_capabilities(self, agent_client, atlas_app):
        _create_project(agent_client, "m2", "M2")
        _enqueue_run(agent_client, "m2", "needs-gpu", capabilities_required=["gpu"])

        scoped, _ = _register_and_get_scoped(atlas_app, capabilities=["cpu"])
        res = scoped.get("/api/runs/next?capabilities=cpu")
        assert res.status_code == 200
        assert res.json() is None

    def test_claim_next_priority_order(self, agent_client, scoped_client):
        _create_project(agent_client, "m2", "M2")
        _enqueue_run(agent_client, "m2", "low", priority=1)
        _enqueue_run(agent_client, "m2", "high", priority=10)

        res = scoped_client.get("/api/runs/next")
        run = res.json()
        assert run is not None
        assert run["job_name"] == "high"

    def test_claim_next_returns_none_when_empty(self, agent_client, scoped_client):
        _create_project(agent_client, "m2", "M2")
        res = scoped_client.get("/api/runs/next")
        assert res.json() is None

    def test_workflow_requirements_route_by_node_executor_and_grant(
        self, agent_client, atlas_app
    ):
        _create_project(agent_client, "workflow", "Workflow")
        run = _enqueue_run(
            agent_client,
            "workflow",
            "summarize",
            workflow={"name": "bilibili-summary", "version": "5", "digest": "sha256:abc"},
            step_name="summarize",
            requirements={
                "node_ids": ["macsp"],
                "executors": ["pi", "codex"],
                "node_labels": ["local-data"],
                "grants": ["bilibili-cookie:read"],
            },
        )
        assert run["workflow"]["name"] == "bilibili-summary"
        assert run["metadata"] == {}

        legacy, _ = _register_and_get_scoped(atlas_app, agent_id="legacy", capabilities=[])
        assert legacy.get("/api/runs/next").json() is None

        bootstrap = TestClient(atlas_app)
        bootstrap.headers["Authorization"] = "Bearer test-token"
        registration = bootstrap.post(
            "/api/runners/register",
            json={
                "runner_id": "macsp-runner",
                "node": {"node_id": "macsp", "labels": ["local-data"]},
                "executors": [{"name": "pi", "kind": "agent"}],
                "available_grants": ["bilibili-cookie:read"],
            },
        )
        scoped = TestClient(atlas_app)
        scoped.headers["Authorization"] = f"Bearer {registration.json()['scoped_token']}"
        claimed = scoped.get("/api/runs/next")
        assert claimed.status_code == 200, claimed.text
        assert claimed.json()["run_id"] == run["run_id"]
        assert claimed.json()["workflow"]["version"] == "5"

class TestLeaseExpiry:
    def test_lease_expires_stale_claim(self, agent_client, scoped_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "lease-test")

        scoped_client.post(f"/api/runs/{run['run_id']}/claim")

        # Wait for lease to expire
        time.sleep(6)

        # find_next_pending should expire the stale claim
        res = scoped_client.get("/api/runs/next")
        assert res.status_code == 200
        claimed = res.json()
        assert claimed is not None
        assert claimed["job_name"] == "lease-test"
        assert claimed["attempt_number"] == 2

    def test_cancel_run(self, agent_client, scoped_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "cancel-me")
        scoped_client.post(f"/api/runs/{run['run_id']}/claim")

        res = session_client.post(f"/api/runs/{run['run_id']}/cancel")
        assert res.status_code == 200
        assert res.json()["status"] == "cancelled"

    def test_cancel_terminal_run_fails(self, agent_client, scoped_client, session_client):
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "done")
        aid, ct = _claim(scoped_client, run)
        scoped_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"attempt_id": aid, "claim_token": ct, "agent_id": "test-agent", "output": {}},
        )

        res = session_client.post(f"/api/runs/{run['run_id']}/cancel")
        assert res.status_code == 409


class TestListing:
    def test_control_credential_can_list_and_get_runs(self, agent_client):
        _create_project(agent_client, "nightly", "Nightly")
        run = _enqueue_run(agent_client, "nightly", "bilibili-summary-v4")

        listed = agent_client.get("/api/runs?project_id=nightly")
        fetched = agent_client.get(f"/api/runs/{run['run_id']}")

        assert listed.status_code == 200
        assert [item["run_id"] for item in listed.json()] == [run["run_id"]]
        assert fetched.status_code == 200
        assert fetched.json()["run_id"] == run["run_id"]

    def test_scoped_executor_cannot_list_arbitrary_runs(self, scoped_client):
        assert scoped_client.get("/api/runs").status_code == 401

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

    def test_list_runs_by_status(self, agent_client, scoped_client, session_client):
        _create_project(agent_client, "m2", "M2")
        r1 = _enqueue_run(agent_client, "m2", "j1")
        _enqueue_run(agent_client, "m2", "j2")

        scoped_client.post(f"/api/runs/{r1['run_id']}/claim")
        scoped_client.post(
            f"/api/runs/{r1['run_id']}/complete",
            json={"agent_id": "test-agent", "output": {}},
        )

        res = session_client.get("/api/runs?project_id=m2&status_str=pending")
        assert res.status_code == 200
        runs = res.json()
        pending = [r for r in runs if r["status"] == "pending"]
        assert len(pending) >= 1


# ── P0-1: Idempotency key tests ──────────────────────────────

class TestIdempotency:
    def test_complete_is_idempotent_with_key(self, agent_client, scoped_client, session_client):
        """Same idempotency key + same payload → returns cached result."""
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "idem-test")
        aid, ct = _claim(scoped_client, run)

        key = f"idem-{uuid.uuid4().hex}"
        payload = {"attempt_id": aid, "claim_token": ct, "agent_id": "test-agent", "output": {"v": 1}}  # noqa: E501

        # First request
        headers = {"Idempotency-Key": key}
        r1 = scoped_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json=payload,
            headers=headers,
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["status"] == "completed"

        # Second request with same key — should succeed and return same terminal state
        r2 = scoped_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json=payload,
            headers=headers,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["status"] == "completed"
        assert r2.json()["run_id"] == r1.json()["run_id"]

    def test_complete_same_key_different_payload_conflicts(self, agent_client, scoped_client):
        """Same idempotency key + different payload → 409."""
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "idem-conflict")
        aid, ct = _claim(scoped_client, run)

        key = f"idem-{uuid.uuid4().hex}"

        r1 = scoped_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"attempt_id": aid, "claim_token": ct,
                 "agent_id": "test-agent", "output": {"v": 1}},
            headers={"Idempotency-Key": key},
        )
        assert r1.status_code == 200

        r2 = scoped_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"attempt_id": aid, "claim_token": ct,
                 "agent_id": "test-agent", "output": {"v": 2}},
            headers={"Idempotency-Key": key},
        )
        assert r2.status_code == 409

    def test_fail_is_idempotent_with_key(self, agent_client, scoped_client):
        """Same idempotency key for fail → cached result."""
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "idem-fail")
        aid, ct = _claim(scoped_client, run)

        key = f"idem-{uuid.uuid4().hex}"
        payload = {"attempt_id": aid, "claim_token": ct, "agent_id": "test-agent", "error_message": "crash"}  # noqa: E501

        r1 = scoped_client.post(
            f"/api/runs/{run['run_id']}/fail",
            json=payload,
            headers={"Idempotency-Key": key},
        )
        assert r1.status_code == 200
        assert r1.json()["status"] == "failed"

        r2 = scoped_client.post(
            f"/api/runs/{run['run_id']}/fail",
            json=payload,
            headers={"Idempotency-Key": key},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "failed"

    def test_no_idempotency_key_backward_compat(self, agent_client, scoped_client):
        """Without Idempotency-Key header, behavior is unchanged."""
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "no-key")
        aid, ct = _claim(scoped_client, run)

        r = scoped_client.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"attempt_id": aid, "claim_token": ct, "agent_id": "test-agent", "output": {}},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

class TestAtomicClaim:
    def test_concurrent_claim_returns_one_winner(self, agent_client, atlas_app):
        """Two agents claiming the same pending run -> exactly one winner."""
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "race-target")

        sc1, _ = _register_and_get_scoped(atlas_app, agent_id="agent-1")
        sc2, _ = _register_and_get_scoped(atlas_app, agent_id="agent-2")

        import concurrent.futures

        def claim_one(client, label):
            r = client.get("/api/runs/next")
            if r.status_code == 200:
                data = r.json()
                if data is not None:
                    data["_claimed_by"] = label
                return data
            return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            f1 = ex.submit(claim_one, sc1, "agent-1")
            f2 = ex.submit(claim_one, sc2, "agent-2")
            r1 = f1.result()
            r2 = f2.result()

        claimed = [r for r in (r1, r2) if r is not None]
        assert len(claimed) == 1, (
            f"Expected exactly 1 winner, got {len(claimed)}: r1={r1}, r2={r2}"
        )
        assert claimed[0]["run_id"] == run["run_id"]

        login = TestClient(atlas_app)
        login.post("/api/auth/login", json={"password": "test"})
        events = login.get(f"/api/runs/{run['run_id']}/events").json()
        claimed_events = [e for e in events if e["event_type"] == "claimed"]
        assert len(claimed_events) == 1, (
            f"Expected 1 claimed event, got {len(claimed_events)}"
        )

        run_data = login.get(f"/api/runs/{run['run_id']}").json()
        assert run_data["attempt_number"] == 1


class TestLeaseExpiryGuard:
    def test_expired_lease_rejects_heartbeat(self, agent_client, atlas_app):
        """Heartbeat on an expired lease must fail with 409."""
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "lease-heartbeat")
        sc, _ = _register_and_get_scoped(atlas_app)
        claim_res = sc.post(f"/api/runs/{run['run_id']}/claim").json()
        aid = claim_res["attempt_id"]
        ct = claim_res["claim_token"]

        # Wait for the 5-second lease to expire.
        time.sleep(6)

        r = sc.post(
            f"/api/runs/{run['run_id']}/heartbeat",
            json={"attempt_id": aid, "claim_token": ct},
        )
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
        assert "lease expired" in r.text.lower()

    def test_expired_lease_rejects_complete(self, agent_client, atlas_app):
        """RFC 0002: complete on expired lease must be rejected."""
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "lease-complete")
        sc, _ = _register_and_get_scoped(atlas_app)
        claim_res = sc.post(f"/api/runs/{run['run_id']}/claim")
        aid = claim_res.json()["attempt_id"]
        ct = claim_res.json()["claim_token"]
        time.sleep(6)

        r = sc.post(
            f"/api/runs/{run['run_id']}/complete",
            json={"attempt_id": aid, "claim_token": ct, "agent_id": "test-agent", "output": {}},
        )
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
        assert "lease expired" in r.text.lower()

    def test_expired_lease_rejects_fail(self, agent_client, atlas_app):
        """RFC 0002: fail on expired lease must be rejected."""
        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "lease-fail")
        sc, _ = _register_and_get_scoped(atlas_app)
        claim_res = sc.post(f"/api/runs/{run['run_id']}/claim")
        aid = claim_res.json()["attempt_id"]
        ct = claim_res.json()["claim_token"]
        time.sleep(6)

        r = sc.post(
            f"/api/runs/{run['run_id']}/fail",
            json={"attempt_id": aid, "claim_token": ct, "agent_id": "test-agent", "error_message": "crash"},  # noqa: E501
        )
        assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
        assert "lease expired" in r.text.lower()


class TestCredentialRotation:
    def test_re_registration_returns_new_token(self, agent_client, atlas_app):
        """Re-registering the same agent rotates the scoped credential."""
        sc1, tok1 = _register_and_get_scoped(atlas_app, agent_id="rotate-me")
        assert tok1, "first registration must return a token"

        sc2, tok2 = _register_and_get_scoped(atlas_app, agent_id="rotate-me")
        assert tok2, "re-registration must return a token"
        assert tok2 != tok1, "token must be rotated"

        _create_project(agent_client, "m2", "M2")
        run = _enqueue_run(agent_client, "m2", "rotation-test")
        r = sc2.post("/api/runs/" + run["run_id"] + "/claim")
        assert r.status_code == 200, "new token rejected: " + r.text

        r = sc1.post(
            "/api/runs/" + run["run_id"] + "/heartbeat",
            json={"attempt_id": "dummy-aid", "claim_token": "dummy-token"},
        )
        assert r.status_code in (401, 409, 422), (
            "old token should be rejected after rotation, got " + str(r.status_code)
        )


class TestExecutionHardeningClosure:
    def test_direct_claim_has_one_concurrent_winner(self, agent_client, atlas_app):
        _create_project(agent_client, "hardening", "Hardening")
        run = _enqueue_run(agent_client, "hardening", "direct-race")
        first, _ = _register_and_get_scoped(atlas_app, agent_id="direct-1")
        second, _ = _register_and_get_scoped(atlas_app, agent_id="direct-2")

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda client: client.post(f"/api/runs/{run['run_id']}/claim"),
                    (first, second),
                )
            )

        assert sorted(response.status_code for response in responses) == [200, 409]

    def test_claim_next_ignores_client_capability_escalation(self, agent_client, atlas_app):
        _create_project(agent_client, "hardening", "Hardening")
        _enqueue_run(
            agent_client,
            "hardening",
            "gpu-only",
            capabilities_required=["gpu"],
        )
        cpu_client, _ = _register_and_get_scoped(
            atlas_app, agent_id="cpu-agent", capabilities=["cpu"]
        )

        response = cpu_client.get("/api/runs/next?capabilities=gpu")

        assert response.status_code == 200
        assert response.json() is None

    def test_agent_with_no_capabilities_cannot_claim_restricted_run(
        self, agent_client, atlas_app
    ):
        _create_project(agent_client, "hardening", "Hardening")
        _enqueue_run(
            agent_client,
            "hardening",
            "gpu-only-empty-agent",
            capabilities_required=["gpu"],
        )
        empty_client, _ = _register_and_get_scoped(
            atlas_app, agent_id="empty-agent", capabilities=[]
        )

        response = empty_client.get("/api/runs/next")

        assert response.status_code == 200
        assert response.json() is None

    def test_direct_claim_enforces_registered_capabilities(self, agent_client, atlas_app):
        _create_project(agent_client, "hardening", "Hardening")
        run = _enqueue_run(
            agent_client,
            "hardening",
            "gpu-only",
            capabilities_required=["gpu"],
        )
        cpu_client, _ = _register_and_get_scoped(
            atlas_app, agent_id="cpu-agent", capabilities=["cpu"]
        )

        response = cpu_client.post(f"/api/runs/{run['run_id']}/claim")

        assert response.status_code == 409
        assert "lacks capabilities" in response.text

    def test_retryable_failure_requeues_then_exhausts(
        self, agent_client, scoped_client, session_client
    ):
        _create_project(agent_client, "hardening", "Hardening")
        run = _enqueue_run(agent_client, "hardening", "flaky", max_attempts=2)

        aid1, ct1 = _claim(scoped_client, run)
        first = scoped_client.post(
            f"/api/runs/{run['run_id']}/fail",
            json={
                "attempt_id": aid1,
                "claim_token": ct1,
                "agent_id": "ignored",
                "error_code": "temporary",
                "error_message": "try again",
                "retryable": True,
            },
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "pending"
        assert first.json()["agent_id"] is None

        aid2, ct2 = _claim(scoped_client, run)
        final = scoped_client.post(
            f"/api/runs/{run['run_id']}/fail",
            json={
                "attempt_id": aid2,
                "claim_token": ct2,
                "agent_id": "ignored",
                "error_code": "temporary",
                "error_message": "still broken",
                "retryable": True,
            },
        )
        assert final.status_code == 200, final.text
        assert final.json()["status"] == "failed"

        events = session_client.get(f"/api/runs/{run['run_id']}/events").json()
        assert [event["event_type"] for event in events].count("retry_scheduled") == 1
        assert [event["event_type"] for event in events].count("failed") == 1

    def test_cancel_creates_event(self, agent_client, scoped_client, session_client):
        _create_project(agent_client, "hardening", "Hardening")
        run = _enqueue_run(agent_client, "hardening", "cancel-event")
        scoped_client.post(f"/api/runs/{run['run_id']}/claim")

        response = session_client.post(f"/api/runs/{run['run_id']}/cancel")

        assert response.status_code == 200
        events = session_client.get(f"/api/runs/{run['run_id']}/events").json()
        assert events[-1]["event_type"] == "cancelled"

    def test_expired_final_attempt_becomes_failed(
        self, agent_client, scoped_client, session_client
    ):
        _create_project(agent_client, "hardening", "Hardening")
        run = _enqueue_run(
            agent_client, "hardening", "lease-exhausted", max_attempts=1
        )
        scoped_client.post(f"/api/runs/{run['run_id']}/claim")
        time.sleep(6)

        response = scoped_client.get("/api/runs/next")

        assert response.status_code == 200
        assert response.json() is None
        stored = session_client.get(f"/api/runs/{run['run_id']}").json()
        assert stored["status"] == "failed"
        assert stored["error_message"] == "lease expired; attempts exhausted"
        events = session_client.get(f"/api/runs/{run['run_id']}/events").json()
        assert events[-1]["event_type"] == "failed"
