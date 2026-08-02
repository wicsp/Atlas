import hashlib
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.config import Settings
from atlas.main import create_app


def make_client(tmp_path: Path) -> TestClient:
    database = tmp_path / "atlas.sqlite3"
    settings = Settings(
        auth={"admin_password": "test", "session_secret": "secret"},
        agents={"database_path": database, "shared_token": "control"},
        work={"database_path": database, "lease_ttl_seconds": 30},
    )
    client = TestClient(create_app(settings))
    client.headers["Authorization"] = "Bearer control"
    return client


def definition() -> dict:
    return {
        "name": "test.pipeline",
        "version": "1",
        "project_id": "test",
        "steps": [
            {
                "name": "extract",
                "requirements": {
                    "node_ids": ["macsp"],
                    "executors": ["script"],
                    "grants": ["source:read"],
                },
            },
            {
                "name": "summarize",
                "depends_on": ["extract"],
                "requirements": {"executors": ["pi", "codex"]},
            },
        ],
    }


def register_runner(
    client: TestClient,
    runner_id: str,
    executors: list[str],
    grants=None,
    node_id: str = "macsp",
) -> TestClient:
    response = client.post(
        "/api/runners/register",
        json={
            "runner_id": runner_id,
            "node": {"node_id": node_id, "labels": ["local-data"]},
            "executors": [
                {"name": name, "kind": "agent" if name in {"pi", "codex"} else "script"}
                for name in executors
            ],
            "available_grants": grants or [],
        },
    )
    assert response.status_code == 200, response.text
    scoped = TestClient(client.app)
    scoped.headers["Authorization"] = f"Bearer {response.json()['scoped_token']}"
    return scoped


def complete(
    scoped: TestClient,
    run: dict,
    output: dict,
    artifacts: list[dict] | None = None,
) -> None:
    response = scoped.post(
        f"/api/runs/{run['run_id']}/complete",
        json={
            "attempt_id": run["attempt_id"],
            "claim_token": run["claim_token"],
            "agent_id": "ignored-server-derived",
            "output": output,
            "artifacts": artifacts or [],
        },
    )
    assert response.status_code == 200, response.text


def test_workflow_definition_is_immutable_by_name_and_version(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = client.post("/api/workflows", json=definition())
    second = client.post("/api/workflows", json=definition())
    changed = definition()
    changed["steps"][0]["priority"] = 10
    conflict = client.post("/api/workflows", json=changed)

    assert first.status_code == 200
    assert second.json()["digest"] == first.json()["digest"]
    assert conflict.status_code == 409


def test_bilibili_v5_is_a_builtin_two_step_workflow(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    workflows = client.get("/api/workflows").json()
    bilibili = next(item for item in workflows if item["name"] == "bilibili.summary")

    assert bilibili["version"] == "5"
    assert [step["name"] for step in bilibili["steps"]] == ["acquire", "summarize"]
    assert bilibili["steps"][0]["requirements"]["grants"] == ["bilibili-cookie:read"]
    assert bilibili["steps"][1]["depends_on"] == ["acquire"]

    favorites = next(
        item for item in workflows if item["name"] == "bilibili.favorites-scan"
    )
    assert favorites["version"] == "1"
    assert favorites["steps"][0]["requirements"]["node_ids"] == ["macsp"]
    assert favorites["steps"][0]["requirements"]["grants"] == [
        "bilibili-cookie:read"
    ]


def test_local_review_and_web_workflows_are_builtin(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    workflows = {
        (item["name"], item["version"]): item
        for item in client.get("/api/workflows").json()
    }

    assert workflows[("web.summary", "1")]["steps"][0]["name"] == "summarize"
    paper = workflows[("paper.ingest", "1")]
    assert [step["name"] for step in paper["steps"]] == ["ingest", "summarize"]
    assert paper["steps"][0]["requirements"] == {
        "node_ids": ["macsp"],
        "executors": ["script"],
        "node_labels": [],
        "grants": ["zotero-library:write", "zotero-library:read"],
    }
    assert paper["steps"][1]["depends_on"] == ["ingest"]
    accepted = workflows[("paper.fulltext", "2")]
    assert [step["name"] for step in accepted["steps"]] == [
        "zotero_import",
        "extract",
        "summarize",
    ]
    assert accepted["steps"][0]["requirements"]["grants"] == [
        "zotero-library:write"
    ]
    assert accepted["steps"][1]["requirements"]["grants"] == [
        "zotero-library:read"
    ]
    assert accepted["steps"][2]["depends_on"] == ["extract"]
    assert ("vortex.comment", "1") not in workflows
    assert ("vortex.comment-sync", "1") not in workflows
    assert workflows[("vortex.comparison", "1")]["steps"][0]["requirements"][
        "executors"
    ] == ["pi"]
    knowledge = workflows[("knowledge.suggest", "1")]
    assert knowledge["project_id"] == "knowledge-base"
    assert knowledge["steps"][0]["requirements"]["node_ids"] == ["macsp"]
    assert knowledge["steps"][0]["requirements"]["executors"] == ["pi"]
    assert ("vortex.resource-purge", "1") not in workflows


def test_retired_comment_workflows_cannot_be_registered_or_invoked(
    tmp_path: Path,
) -> None:
    control = make_client(tmp_path)
    retired = {
        "name": "vortex.comment",
        "version": "1",
        "project_id": "resource-review",
        "steps": [{"name": "setup"}],
    }
    registration = control.post("/api/workflows", json=retired)
    invocation = control.post(
        "/api/workflow-invocations",
        json={
            "workflow_name": "vortex.comment",
            "workflow_version": "1",
            "input": {"resource_id": "res_12345678"},
        },
    )

    assert registration.status_code == 409
    assert "retired" in registration.json()["detail"]
    assert invocation.status_code == 404


def test_invocation_expands_steps_and_unblocks_dependency_with_context(tmp_path: Path) -> None:
    control = make_client(tmp_path)
    control.post("/api/workflows", json=definition())
    invocation = control.post(
        "/api/workflow-invocations",
        json={
            "workflow_name": "test.pipeline",
            "workflow_version": "1",
            "input": {"url": "https://example.test/video"},
        },
    ).json()
    assert set(invocation["step_runs"]) == {"extract", "summarize"}

    script = register_runner(control, "macsp-script", ["script"], ["source:read"])
    extracted = script.get("/api/runs/next").json()
    assert extracted["step_name"] == "extract"
    assert extracted["workflow"]["name"] == "test.pipeline"
    content = "hello from macsp"
    checksum = f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"
    complete(
        script,
        extracted,
        {"transcript": "hello"},
        [
            {
                "name": "transcript",
                "uri": "file:///macsp/private/transcript.txt",
                "content_type": "text/plain",
                "size_bytes": len(content.encode()),
                "checksum": checksum,
                "content": content,
            }
        ],
    )

    agent = register_runner(control, "amax-pi", ["pi"], node_id="amax")
    summarized = agent.get("/api/runs/next").json()
    assert summarized["step_name"] == "summarize"
    upstream = summarized["execution_context"][extracted["run_id"]]
    assert upstream["output"] == {"transcript": "hello"}
    assert upstream["artifacts"][0]["uri"].startswith("atlas://artifacts/")
    assert upstream["artifacts"][0]["content"] == content
    complete(agent, summarized, {"summary": "short"})

    status = control.get(
        f"/api/workflow-invocations/{invocation['invocation_id']}"
    ).json()
    assert status["status"] == "completed"

    service = control.app.state.workflow_service
    service._repository.set_invocation_status(
        invocation["invocation_id"],
        "running",
        datetime.now(UTC),
    )
    assert service.reconcile_running_invocations()["completed"] == 1
