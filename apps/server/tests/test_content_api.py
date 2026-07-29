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


def _publish_variant(
    control: TestClient,
    scoped: TestClient,
    source_id: str,
    seed: int,
) -> str:
    claimed = _claimed_run(control, scoped, source_id)
    payload = _completion_payload(claimed, source_id)
    for index, (artifact, resource) in enumerate(
        zip(payload["artifacts"], payload["resources"], strict=True)
    ):
        checksum = f"sha256:{hashlib.sha256(f'{seed}:{index}'.encode()).hexdigest()}"
        artifact["name"] = f"{artifact['name']}-{seed}"
        artifact["checksum"] = checksum
        resource["artifact_name"] = artifact["name"]
        resource["content_hash"] = checksum
        resource["resource_id"] = _resource_id(source_id, resource["kind"], checksum)
    completed = scoped.post(f"/api/runs/{claimed['run_id']}/complete", json=payload)
    assert completed.status_code == 200, completed.text
    return payload["resources"][1]["resource_id"]


def _publish_paper_preview(
    control: TestClient,
    scoped: TestClient,
) -> tuple[dict, str]:
    source_response = control.post(
        "/api/sources",
        json={
            "source_key": "arxiv:2607.01234",
            "kind": "paper",
            "canonical_uri": "https://arxiv.org/abs/2607.01234",
            "title": "A Useful Paper",
            "external_ids": {"arxiv_id": "2607.01234"},
            "metadata": {"captured_via": "test"},
        },
    )
    assert source_response.status_code == 200, source_response.text
    source = source_response.json()
    claimed = _claimed_run(control, scoped, source["source_id"])
    preview = (
        "# A Useful Paper\n\n"
        "## 一句话结论\n有用。\n"
        "## 研究问题\n问题。\n"
        "## 方法思路\n方法。\n"
        "## 作者声称的结果\n结果。\n"
        "## 主要贡献\n贡献。\n"
        "## 局限与待核查\n待核查。\n"
    )
    checksum = f"sha256:{hashlib.sha256(preview.encode()).hexdigest()}"
    resource_id = _resource_id(source["source_id"], "summary", checksum)
    completed = scoped.post(
        f"/api/runs/{claimed['run_id']}/complete",
        json={
            "attempt_id": claimed["attempt_id"],
            "claim_token": claimed["claim_token"],
            "agent_id": "ignored",
            "output": {"preview_resource_id": resource_id},
            "artifacts": [
                {
                    "name": "paper-preview-2607.01234",
                    "uri": "file:///private/atlas/paper-preview.md",
                    "content_type": "text/markdown; charset=utf-8",
                    "size_bytes": len(preview.encode()),
                    "checksum": checksum,
                    "content": preview,
                }
            ],
            "resources": [
                {
                    "resource_id": resource_id,
                    "source_id": source["source_id"],
                    "kind": "summary",
                    "title": "A Useful Paper — abstract preview",
                    "artifact_name": "paper-preview-2607.01234",
                    "content_hash": checksum,
                    "generator": {
                        "mode": "ai",
                        "name": "atlas-runner-paper-preview",
                        "version": "1",
                        "model_provider": "test",
                        "model_id": "test",
                        "prompt_version": "paper-preview-v1",
                    },
                    "metadata": {
                        "profile_id": "paper-preview-v1",
                        "basis": "abstract",
                        "arxiv_id": "2607.01234",
                    },
                }
            ],
        },
    )
    assert completed.status_code == 200, completed.text
    return source, resource_id


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


def test_paper_ingest_enqueues_workflow_and_reuses_active_invocation(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    source_response = control_client.post(
        "/api/sources",
        json={
            "source_key": "arxiv:2607.01234",
            "kind": "paper",
            "canonical_uri": "https://arxiv.org/abs/2607.01234",
            "title": "A Useful Paper",
            "external_ids": {"arxiv_id": "2607.01234"},
            "metadata": {"captured_via": "test"},
        },
    )
    assert source_response.status_code == 200, source_response.text
    source = source_response.json()

    first = dashboard_client.post(
        "/api/paper/ingest",
        json={"source_id": source["source_id"]},
    )
    replay = dashboard_client.post(
        "/api/paper/ingest",
        json={"source_id": source["source_id"]},
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert first.json()["reused"] is False
    assert replay.json()["reused"] is True
    assert replay.json()["invocation"]["invocation_id"] == (
        first.json()["invocation"]["invocation_id"]
    )
    invocation = first.json()["invocation"]
    assert invocation["workflow_name"] == "paper.ingest"
    assert invocation["workflow_version"] == "1"
    assert invocation["input"] == {
        "source_id": source["source_id"],
        "arxiv_id": "2607.01234",
        "canonical_uri": "https://arxiv.org/abs/2607.01234",
    }


def test_paper_ingest_rejects_non_paper_source(
    control_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    source_response = control_client.post(
        "/api/sources",
        json={
            "source_key": "https://example.com/video",
            "kind": "video",
            "canonical_uri": "https://example.com/video",
            "title": "A Video",
        },
    )
    assert source_response.status_code == 200
    source = source_response.json()

    response = dashboard_client.post(
        "/api/paper/ingest",
        json={"source_id": source["source_id"]},
    )

    assert response.status_code == 409


def test_paper_workflows_cannot_bypass_domain_api(
    dashboard_client: TestClient,
) -> None:
    response = dashboard_client.post(
        "/api/workflow-invocations",
        json={
            "workflow_name": "paper.ingest",
            "workflow_version": "1",
            "input": {"source_id": "src_bypass"},
        },
    )
    assert response.status_code == 409
    assert "/api/paper/ingest" in response.json()["detail"]


def test_paper_fulltext_validates_preview_source_and_profile(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    source, preview_resource_id = _publish_paper_preview(
        control_client, scoped_client
    )
    accepted = dashboard_client.post(
        "/api/paper/fulltext",
        json={
            "source_id": source["source_id"],
            "preview_resource_id": preview_resource_id,
        },
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["reused"] is False

    other = control_client.post(
        "/api/sources",
        json={
            "source_key": "arxiv:2607.09999",
            "kind": "paper",
            "canonical_uri": "https://arxiv.org/abs/2607.09999",
            "external_ids": {"arxiv_id": "2607.09999"},
        },
    ).json()
    rejected = dashboard_client.post(
        "/api/paper/fulltext",
        json={
            "source_id": other["source_id"],
            "preview_resource_id": preview_resource_id,
        },
    )
    assert rejected.status_code == 409
    assert "does not belong" in rejected.json()["detail"]


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


def test_resource_content_is_uploaded_atomically_and_readable_in_console(
    control_client: TestClient,
    scoped_client: TestClient,
) -> None:
    source = _source(control_client)
    claimed = _claimed_run(control_client, scoped_client, source["source_id"])
    payload = _completion_payload(claimed, source["source_id"])
    markdown = "# Summary\n\nReadable in Atlas Console.\n"
    checksum = f"sha256:{hashlib.sha256(markdown.encode()).hexdigest()}"
    payload["artifacts"][1].update(
        content=markdown,
        size_bytes=len(markdown.encode()),
        checksum=checksum,
    )
    payload["resources"][1].update(
        resource_id=_resource_id(source["source_id"], "summary", checksum),
        content_hash=checksum,
    )

    completed = scoped_client.post(
        f"/api/runs/{claimed['run_id']}/complete", json=payload
    )
    assert completed.status_code == 200, completed.text

    resource_id = payload["resources"][1]["resource_id"]
    document = control_client.get(f"/api/resources/{resource_id}/content")
    assert document.status_code == 200, document.text
    assert document.json()["content"] == markdown
    assert document.json()["artifact"]["checksum"] == checksum
    assert document.json()["artifact"]["uri"].startswith("atlas://artifacts/")


def test_existing_artifact_content_can_be_backfilled_once(
    control_client: TestClient,
    scoped_client: TestClient,
) -> None:
    source = _source(control_client)
    claimed = _claimed_run(control_client, scoped_client, source["source_id"])
    payload = _completion_payload(claimed, source["source_id"])
    markdown = "# Backfilled summary\n"
    checksum = f"sha256:{hashlib.sha256(markdown.encode()).hexdigest()}"
    payload["artifacts"][1].update(
        size_bytes=len(markdown.encode()),
        checksum=checksum,
    )
    payload["resources"][1].update(
        resource_id=_resource_id(source["source_id"], "summary", checksum),
        content_hash=checksum,
    )
    completed = scoped_client.post(
        f"/api/runs/{claimed['run_id']}/complete", json=payload
    )
    assert completed.status_code == 200, completed.text

    resource_id = payload["resources"][1]["resource_id"]
    resource = control_client.get(f"/api/resources/{resource_id}").json()
    missing = control_client.get(f"/api/resources/{resource_id}/content")
    assert missing.status_code == 404

    uploaded = control_client.put(
        f"/api/artifacts/{resource['artifact_id']}/content",
        json={"content": markdown},
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["content"] == markdown
    bundle = control_client.get(f"/api/resources/{resource_id}/bundle").json()
    assert bundle["artifact"]["uri"].startswith("atlas://artifacts/")
    document = control_client.get(f"/api/resources/{resource_id}/content")
    assert document.status_code == 200, document.text
    assert document.json()["content"] == markdown


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
    assert restored.json()["review_status"] == "reviewed"


def test_commented_resource_can_be_ignored_and_restored_to_reviewed(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    source = _source(control_client)
    claimed = _claimed_run(control_client, scoped_client, source["source_id"])
    payload = _completion_payload(claimed, source["source_id"])
    completed = scoped_client.post(
        f"/api/runs/{claimed['run_id']}/complete", json=payload
    )
    assert completed.status_code == 200, completed.text
    resource_id = payload["resources"][1]["resource_id"]

    commented = dashboard_client.post(
        "/api/review-actions/complete-comment",
        json={
            "resource_id": resource_id,
            "body_markdown": "This is my retained comment.",
        },
    )
    assert commented.status_code == 200, commented.text

    ignored = dashboard_client.post(
        "/api/review-actions/ignore-resource",
        json={"resource_id": resource_id},
    )
    assert ignored.status_code == 200, ignored.text
    assert ignored.json()["resource"]["review_status"] == "dismissed"
    assert ignored.json()["evicted_resource_ids"] == []
    assert dashboard_client.get(
        f"/api/comments?resource_id={resource_id}"
    ).json()[0]["body_markdown"] == "This is my retained comment."

    restored = dashboard_client.post(
        "/api/review-actions/restore-resource",
        json={"resource_id": resource_id},
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["resource"]["review_status"] == "reviewed"
    assert dashboard_client.post(
        "/api/review-actions/purge-source",
        json={"source_id": source["source_id"]},
    ).status_code == 404


def test_ignore_list_keeps_ten_and_permanently_cleans_oldest(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    source = _source(control_client)
    resource_ids = [
        _publish_variant(
            control_client,
            scoped_client,
            source["source_id"],
            seed,
        )
        for seed in range(11)
    ]
    comment = dashboard_client.post(
        "/api/review-actions/complete-comment",
        json={
            "resource_id": resource_ids[0],
            "body_markdown": "Oldest ignored comment.",
        },
    )
    assert comment.status_code == 200, comment.text

    last_ignore = None
    for resource_id in resource_ids:
        last_ignore = dashboard_client.post(
            "/api/review-actions/ignore-resource",
            json={"resource_id": resource_id},
        )
        assert last_ignore.status_code == 200, last_ignore.text

    assert last_ignore is not None
    result = last_ignore.json()
    assert result["evicted_resource_ids"] == [resource_ids[0]]
    assert len(result["cleanup_runs"]) == 1
    cleanup = result["cleanup_runs"][0]
    assert cleanup["job_name"] == "vortex-resource-purge-v1"
    assert cleanup["metadata"]["requested_via"] == "ignored-resource-retention"
    expired = cleanup["input"]["resources"][0]
    assert expired["resource_id"] == resource_ids[0]
    assert expired["remove_comment"] is True

    assert dashboard_client.get(f"/api/resources/{resource_ids[0]}").status_code == 404
    ignored = dashboard_client.get(
        "/api/resources?kind=summary&review_status=dismissed&limit=500"
    ).json()
    assert len(ignored) == 10
    assert dashboard_client.get(
        f"/api/comments?resource_id={resource_ids[0]}"
    ).json() == []
    assert all(
        resource_ids[0] not in item["resource_ids"]
        for item in dashboard_client.get("/api/knowledge-refs?limit=500").json()
    )


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
    assert run["capabilities_required"] == []
    assert run["input"]["resource_id"] == resource_id
    assert run["input"]["bundle"]["resource"]["resource_id"] == resource_id
    assert run["workflow"]["name"] == "vortex.comment"
    assert run["step_name"] == "setup"
    assert run["requirements"]["grants"] == ["obsidian-vault:write"]
    assert run["priority"] == 100
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


def test_complete_comment_stores_markdown_and_marks_reviewed(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    source, publication = _publish_content(control_client, scoped_client)
    resource_id = publication["resources"][1]["resource_id"]

    markdown = "# Knowledge Comment\n\n## 我的评论\n\n这是我的判断。\n"
    content_hash = f"sha256:{hashlib.sha256(markdown.encode()).hexdigest()}"
    payload = {
        "resource_id": resource_id,
        "body_markdown": markdown,
    }
    completed = dashboard_client.post(
        "/api/review-actions/complete-comment",
        json=payload,
    )
    replay = dashboard_client.post(
        "/api/review-actions/complete-comment",
        json={**payload, "content_hash": content_hash},
    )

    assert completed.status_code == 200, completed.text
    assert replay.status_code == 200, replay.text
    body = completed.json()
    assert body["resource"]["review_status"] == "reviewed"
    assert body["knowledge_ref"]["note_id"] == f"Atlas/Comments/{resource_id}"
    assert body["knowledge_ref"]["uri"] == f"/#resource-{resource_id}"
    assert body["knowledge_ref"]["resource_ids"] == [resource_id]
    assert body["knowledge_ref"]["source_ids"] == [source["source_id"]]
    assert body["comment"]["body_markdown"] == markdown
    assert body["comment"]["content_hash"] == content_hash
    assert body["comment"]["resource_ids"] == [resource_id]
    assert (
        replay.json()["comment"]["comment_id"]
        == body["comment"]["comment_id"]
    )
    listed = dashboard_client.get(f"/api/comments?resource_id={resource_id}")
    assert listed.status_code == 200, listed.text
    assert listed.json() == [body["comment"]]


def test_complete_comment_requires_valid_content_and_summary_resource(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    _, publication = _publish_content(control_client, scoped_client)
    transcript_id = publication["resources"][0]["resource_id"]
    summary_id = publication["resources"][1]["resource_id"]

    missing_body = dashboard_client.post(
        "/api/review-actions/complete-comment",
        json={"resource_id": summary_id},
    )
    hash_mismatch = dashboard_client.post(
        "/api/review-actions/complete-comment",
        json={
            "resource_id": summary_id,
            "body_markdown": "written comment",
            "content_hash": f"sha256:{'0' * 64}",
        },
    )
    transcript = dashboard_client.post(
        "/api/review-actions/complete-comment",
        json={
            "resource_id": transcript_id,
            "body_markdown": "written comment",
        },
    )

    assert missing_body.status_code == 422
    assert hash_mismatch.status_code == 422
    assert transcript.status_code == 409


def test_comment_sync_request_enqueues_fixed_capability_and_reuses_active_run(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    _, publication = _publish_content(control_client, scoped_client)
    resource_id = publication["resources"][1]["resource_id"]

    first = dashboard_client.post(
        "/api/review-actions/sync-comment", json={"resource_id": resource_id}
    )
    replay = dashboard_client.post(
        "/api/review-actions/sync-comment", json={"resource_id": resource_id}
    )

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["reused"] is True
    assert replay.json()["run"]["run_id"] == first.json()["run"]["run_id"]
    assert first.json()["run"]["job_name"] == "vortex-comment-sync-v1"
    run = first.json()["run"]
    assert run["capabilities_required"] == []
    assert run["workflow"]["name"] == "vortex.comment-sync"
    assert run["requirements"]["grants"] == [
        "obsidian-vault:read",
        "atlas-control:write",
    ]


def test_comparison_request_enqueues_fixed_capability_and_reuses_active_run(
    control_client: TestClient,
    scoped_client: TestClient,
    dashboard_client: TestClient,
) -> None:
    _, publication = _publish_content(control_client, scoped_client)
    resource_id = publication["resources"][1]["resource_id"]
    first = dashboard_client.post(
        "/api/review-actions/compare", json={"resource_id": resource_id}
    )
    replay = dashboard_client.post(
        "/api/review-actions/compare", json={"resource_id": resource_id}
    )
    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json()["reused"] is True
    assert replay.json()["run"]["run_id"] == first.json()["run"]["run_id"]
    assert first.json()["run"]["job_name"] == "vortex-comparison-v1"
    run = first.json()["run"]
    assert run["capabilities_required"] == []
    assert run["workflow"]["name"] == "vortex.comparison"
    assert run["input"]["bundle"]["resource"]["resource_id"] == resource_id
