"""RFC 0003 Source, Resource, and KnowledgeRef API contract tests."""

from __future__ import annotations

import hashlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.config import Settings
from atlas.main import create_app


@pytest.fixture
def atlas_app(tmp_path) -> FastAPI:
    database_path = str(tmp_path / "atlas.sqlite3")
    settings = Settings(
        auth={"admin_password": "test", "session_secret": "secret"},
        agents={"database_path": database_path, "shared_token": "test-token"},
        work={"database_path": database_path, "lease_ttl_seconds": 120},
    )
    return create_app(settings)


@pytest.fixture
def control_client(atlas_app: FastAPI) -> TestClient:
    client = TestClient(atlas_app)
    client.headers["Authorization"] = "Bearer test-token"
    return client


@pytest.fixture
def dashboard_client(atlas_app: FastAPI) -> TestClient:
    client = TestClient(atlas_app)
    response = client.post("/api/auth/login", json={"password": "test"})
    assert response.status_code == 200
    return client


@pytest.fixture
def scoped_client(atlas_app: FastAPI) -> TestClient:
    bootstrap = TestClient(atlas_app)
    bootstrap.headers["Authorization"] = "Bearer test-token"
    response = bootstrap.post(
        "/api/agents/register",
        json={
            "agent_id": "macsp.lumio.pi.rfc3",
            "name": "RFC 3 test agent",
            "capabilities": ["bilibili-summary"],
            "metadata": {"protocol_version": "atlas-agent-v3"},
        },
    )
    assert response.status_code == 200
    client = TestClient(atlas_app)
    client.headers["Authorization"] = f"Bearer {response.json()['scoped_token']}"
    return client


def _source(client: TestClient, title: str | None = None) -> dict:
    response = client.post(
        "/api/sources",
        json={
            "source_key": "bilibili:BV1AB411C7mD",
            "kind": "video",
            "canonical_uri": "https://www.bilibili.com/video/BV1AB411C7mD",
            "title": title,
            "external_ids": {"bvid": "BV1AB411C7mD"},
            "metadata": {"captured_via": "test"},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _claimed_run(control: TestClient, scoped: TestClient, source_id: str) -> dict:
    project = control.post(
        "/api/projects",
        json={"project_id": "bilibili-capture", "name": "Bilibili Capture"},
    )
    assert project.status_code == 200, project.text
    enqueued = control.post(
        "/api/runs/enqueue",
        json={
            "project_id": "bilibili-capture",
            "job_name": "bilibili-summary",
            "capabilities_required": ["bilibili-summary"],
            "input": {"source_id": source_id, "url": "https://b23.tv/example"},
        },
    )
    assert enqueued.status_code == 200, enqueued.text
    claimed = scoped.post(f"/api/runs/{enqueued.json()['run_id']}/claim")
    assert claimed.status_code == 200, claimed.text
    return claimed.json()


def _completion_payload(claimed: dict, source_id: str) -> dict:
    return {
        "attempt_id": claimed["attempt_id"],
        "claim_token": claimed["claim_token"],
        "agent_id": "untrusted-client-value",
        "output": {
            "bvid": "BV1AB411C7mD",
            "title": "A useful video",
            "transcript_length": 1200,
            "processing_level": 2,
        },
        "source_updates": [
            {
                "source_id": source_id,
                "title": "A useful video",
                "metadata": {"duration_text": "10:00"},
            }
        ],
        "artifacts": [
            {
                "name": "transcript-BV1AB411C7mD",
                "uri": "file:///private/atlas/transcript.txt",
                "content_type": "text/plain; charset=utf-8",
                "size_bytes": 1200,
                "checksum": f"sha256:{'a' * 64}",
            },
            {
                "name": "summary-BV1AB411C7mD",
                "uri": "file:///private/atlas/summary.md",
                "content_type": "text/markdown; charset=utf-8",
                "size_bytes": 800,
                "checksum": f"sha256:{'b' * 64}",
            },
        ],
        "resources": [
            {
                "resource_id": _resource_id(
                    source_id, "transcript", f"sha256:{'a' * 64}"
                ),
                "source_id": source_id,
                "kind": "transcript",
                "title": "A useful video — transcript",
                "artifact_name": "transcript-BV1AB411C7mD",
                "content_hash": f"sha256:{'a' * 64}",
                "generator": {
                    "mode": "deterministic",
                    "name": "lumio-bilibili-transcript",
                    "version": "1",
                },
                "metadata": {"language": "zh-CN"},
            },
            {
                "resource_id": _resource_id(
                    source_id, "summary", f"sha256:{'b' * 64}"
                ),
                "source_id": source_id,
                "kind": "summary",
                "title": "A useful video — AI summary",
                "artifact_name": "summary-BV1AB411C7mD",
                "content_hash": f"sha256:{'b' * 64}",
                "generator": {
                    "mode": "ai",
                    "name": "lumio-bilibili-summary",
                    "version": "1",
                    "model_provider": "openai",
                    "model_id": "gpt-test",
                    "prompt_version": "bilibili-summary-v1",
                },
                "metadata": {"transcript_truncated": False},
            },
        ],
    }


def _resource_id(source_id: str, kind: str, content_hash: str) -> str:
    digest = hashlib.sha256(f"{source_id}\0{kind}\0{content_hash}".encode()).hexdigest()
    return f"res_{digest[:32]}"


def _publish_content(control: TestClient, scoped: TestClient) -> tuple[dict, dict]:
    source = _source(control)
    claimed = _claimed_run(control, scoped, source["source_id"])
    payload = _completion_payload(claimed, source["source_id"])
    completed = scoped.post(f"/api/runs/{claimed['run_id']}/complete", json=payload)
    assert completed.status_code == 200, completed.text
    return source, payload


def test_source_upsert_is_stable_and_enriches_metadata(control_client: TestClient) -> None:
    first = _source(control_client)
    second = _source(control_client, title="A useful video")
    third = _source(control_client)

    assert second["source_id"] == first["source_id"]
    assert second["title"] == "A useful video"
    assert third["title"] == "A useful video"
    response = control_client.get("/api/sources")
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_content_endpoints_require_control_auth(atlas_app: FastAPI) -> None:
    client = TestClient(atlas_app)
    assert client.get("/api/sources").status_code == 401
    assert client.get("/api/resources").status_code == 401
    assert client.get("/api/knowledge-refs").status_code == 401
    assert client.post(
        "/api/review-actions/comment",
        json={"resource_id": "res_12345678"},
    ).status_code == 401


def test_completion_atomically_publishes_resources_and_is_idempotent(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    source = _source(control_client)
    claimed = _claimed_run(control_client, scoped_client, source["source_id"])
    payload = _completion_payload(claimed, source["source_id"])
    headers = {"Idempotency-Key": "rfc3-complete-1"}

    first = scoped_client.post(
        f"/api/runs/{claimed['run_id']}/complete", json=payload, headers=headers
    )
    replay = scoped_client.post(
        f"/api/runs/{claimed['run_id']}/complete", json=payload, headers=headers
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert first.json()["status"] == "completed"
    assert "summary" not in first.json()["output"]

    resources = control_client.get("/api/resources").json()
    artifacts = dashboard_client.get(
        f"/api/runs/{claimed['run_id']}/artifacts"
    ).json()
    events = dashboard_client.get(f"/api/runs/{claimed['run_id']}/events").json()
    assert len(resources) == 2
    assert len(artifacts) == 2
    assert sum(event["event_type"] == "completed" for event in events) == 1
    assert {resource["artifact_id"] for resource in resources} == {
        artifact["artifact_id"] for artifact in artifacts
    }
    assert all(resource["review_status"] == "pending" for resource in resources)
    assert all(resource["produced_by_run_id"] == claimed["run_id"] for resource in resources)

    summary = next(resource for resource in resources if resource["kind"] == "summary")
    bundle = control_client.get(f"/api/resources/{summary['resource_id']}/bundle")
    assert bundle.status_code == 200, bundle.text
    assert bundle.json()["resource"] == summary
    assert bundle.json()["source"]["source_id"] == source["source_id"]
    assert bundle.json()["artifact"]["artifact_id"] == summary["artifact_id"]

    enriched = control_client.get(f"/api/sources/{source['source_id']}").json()
    assert enriched["title"] == "A useful video"
    assert enriched["metadata"] == {
        "captured_via": "test",
        "duration_text": "10:00",
    }


def test_invalid_resource_rolls_back_entire_completion(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    source = _source(control_client)
    claimed = _claimed_run(control_client, scoped_client, source["source_id"])
    payload = _completion_payload(claimed, source["source_id"])
    payload["resources"][1]["artifact_name"] = "missing-summary-artifact"

    response = scoped_client.post(
        f"/api/runs/{claimed['run_id']}/complete", json=payload
    )

    assert response.status_code == 409
    run = dashboard_client.get(f"/api/runs/{claimed['run_id']}").json()
    artifacts = dashboard_client.get(
        f"/api/runs/{claimed['run_id']}/artifacts"
    ).json()
    assert run["status"] == "claimed"
    assert artifacts == []
    assert control_client.get("/api/resources").json() == []


def test_resource_review_state_is_explicit(
    control_client: TestClient,
    scoped_client: TestClient,
) -> None:
    source = _source(control_client)
    claimed = _claimed_run(control_client, scoped_client, source["source_id"])
    payload = _completion_payload(claimed, source["source_id"])
    response = scoped_client.post(
        f"/api/runs/{claimed['run_id']}/complete", json=payload
    )
    assert response.status_code == 200, response.text

    resource_id = payload["resources"][1]["resource_id"]
    reviewed = control_client.patch(
        f"/api/resources/{resource_id}/review", json={"review_status": "reviewed"}
    )
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["review_status"] == "reviewed"

    dismissed = control_client.patch(
        f"/api/resources/{resource_id}/review", json={"review_status": "dismissed"}
    )
    assert dismissed.status_code == 200, dismissed.text
    assert dismissed.json()["review_status"] == "dismissed"

    restored = control_client.patch(
        f"/api/resources/{resource_id}/review", json={"review_status": "pending"}
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["review_status"] == "pending"


def test_resource_referenced_by_human_knowledge_cannot_be_dismissed(
    control_client: TestClient,
    scoped_client: TestClient,
) -> None:
    source = _source(control_client)
    claimed = _claimed_run(control_client, scoped_client, source["source_id"])
    payload = _completion_payload(claimed, source["source_id"])
    completed = scoped_client.post(
        f"/api/runs/{claimed['run_id']}/complete", json=payload
    )
    assert completed.status_code == 200, completed.text
    resource_id = payload["resources"][1]["resource_id"]

    reviewed = control_client.patch(
        f"/api/resources/{resource_id}/review", json={"review_status": "reviewed"}
    )
    assert reviewed.status_code == 200, reviewed.text
    knowledge_ref = control_client.post(
        "/api/knowledge-refs",
        json={
            "note_id": "Knowledge/Comments/kept-evidence",
            "uri": "obsidian://open?vault=Vortex&file=Knowledge%2FComments%2Fkept-evidence",
            "resource_ids": [resource_id],
        },
    )
    assert knowledge_ref.status_code == 200, knowledge_ref.text

    rejected = control_client.patch(
        f"/api/resources/{resource_id}/review", json={"review_status": "dismissed"}
    )
    assert rejected.status_code == 409, rejected.text
    assert "KnowledgeRef" in rejected.json()["detail"]
    current = control_client.get(f"/api/resources/{resource_id}")
    assert current.status_code == 200
    assert current.json()["review_status"] == "reviewed"


def test_knowledge_ref_rejects_prose_and_derives_source_relation(
    control_client: TestClient,
    scoped_client: TestClient,
) -> None:
    source = _source(control_client)
    claimed = _claimed_run(control_client, scoped_client, source["source_id"])
    payload = _completion_payload(claimed, source["source_id"])
    completed = scoped_client.post(
        f"/api/runs/{claimed['run_id']}/complete", json=payload
    )
    assert completed.status_code == 200, completed.text
    resource_id = payload["resources"][1]["resource_id"]

    rejected = control_client.post(
        "/api/knowledge-refs",
        json={
            "note_id": "Knowledge/Comments/comment-1",
            "uri": "obsidian://open?vault=Vortex&file=Knowledge%2FComments%2Fcomment-1",
            "resource_ids": [resource_id],
            "body": "An AI must never be able to place this prose in Knowledge.",
        },
    )
    assert rejected.status_code == 422

    accepted = control_client.post(
        "/api/knowledge-refs",
        json={
            "note_id": "Knowledge/Comments/comment-1",
            "uri": "obsidian://open?vault=Vortex&file=Knowledge%2FComments%2Fcomment-1",
            "resource_ids": [resource_id],
        },
    )
    assert accepted.status_code == 200, accepted.text
    record = accepted.json()
    assert record["resource_ids"] == [resource_id]
    assert record["source_ids"] == [source["source_id"]]
    assert "body" not in record
    assert "content" not in record

    listed = control_client.get("/api/knowledge-refs").json()
    assert listed == [record]


def test_knowledge_ref_upsert_preserves_identity(
    control_client: TestClient,
) -> None:
    source = _source(control_client)
    payload = {
        "note_id": "Knowledge/Comments/source-only",
        "uri": "obsidian://open?vault=Vortex&file=Knowledge%2FComments%2Fsource-only",
        "source_ids": [source["source_id"]],
    }
    first = control_client.post("/api/knowledge-refs", json=payload)
    second = control_client.post("/api/knowledge-refs", json=payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["knowledge_ref_id"] == second.json()["knowledge_ref_id"]
    assert len(control_client.get("/api/knowledge-refs").json()) == 1


def test_comment_request_enqueues_only_fixed_capability_and_reuses_active_run(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    _, publication = _publish_content(control_client, scoped_client)
    resource_id = publication["resources"][1]["resource_id"]

    first = dashboard_client.post(
        "/api/review-actions/comment",
        json={"resource_id": resource_id},
    )
    second = dashboard_client.post(
        "/api/review-actions/comment",
        json={"resource_id": resource_id},
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["reused"] is False
    assert second.json()["reused"] is True
    assert second.json()["run"]["run_id"] == first.json()["run"]["run_id"]

    run = first.json()["run"]
    assert run["project_id"] == "resource-review"
    assert run["job_name"] == "vortex-comment-v1"
    assert run["capabilities_required"] == ["vortex-comment-v1"]
    assert run["input"] == {"resource_id": resource_id}
    assert run["metadata"] == {"requested_via": "atlas-console"}
    assert run["output"] is None

    visible = dashboard_client.get(f"/api/runs/{run['run_id']}")
    assert visible.status_code == 200, visible.text
    assert visible.json() == run


def test_comment_request_rejects_prose_and_non_summary_resources(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    _, publication = _publish_content(control_client, scoped_client)
    transcript_id = publication["resources"][0]["resource_id"]
    summary_id = publication["resources"][1]["resource_id"]

    prose = dashboard_client.post(
        "/api/review-actions/comment",
        json={"resource_id": summary_id, "body": "machine-authored prose"},
    )
    transcript = dashboard_client.post(
        "/api/review-actions/comment",
        json={"resource_id": transcript_id},
    )

    assert prose.status_code == 422
    assert transcript.status_code == 409, transcript.text
    assert "summary Resource" in transcript.json()["detail"]
    assert dashboard_client.get("/api/runs?project_id=resource-review").json() == []


def test_comment_request_conflicts_when_human_comment_already_exists(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    _, publication = _publish_content(control_client, scoped_client)
    resource_id = publication["resources"][1]["resource_id"]
    knowledge_ref = control_client.post(
        "/api/knowledge-refs",
        json={
            "note_id": "Knowledge/Comments/already-commented",
            "uri": (
                "obsidian://open?vault=Vortex&file="
                "Knowledge%2FComments%2Falready-commented"
            ),
            "resource_ids": [resource_id],
        },
    )
    assert knowledge_ref.status_code == 200, knowledge_ref.text

    response = dashboard_client.post(
        "/api/review-actions/comment",
        json={"resource_id": resource_id},
    )

    assert response.status_code == 409, response.text
    assert "already has KnowledgeRef" in response.json()["detail"]
    assert dashboard_client.get("/api/runs?project_id=resource-review").json() == []
