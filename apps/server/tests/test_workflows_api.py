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


def register_runner(client: TestClient, runner_id: str, executors: list[str], grants=None) -> TestClient:
    response = client.post(
        "/api/runners/register",
        json={
            "runner_id": runner_id,
            "node": {"node_id": "macsp", "labels": ["local-data"]},
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


def complete(scoped: TestClient, run: dict, output: dict) -> None:
    response = scoped.post(
        f"/api/runs/{run['run_id']}/complete",
        json={
            "attempt_id": run["attempt_id"],
            "claim_token": run["claim_token"],
            "agent_id": "ignored-server-derived",
            "output": output,
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
    complete(script, extracted, {"transcript": "hello"})

    agent = register_runner(control, "macsp-pi", ["pi"])
    summarized = agent.get("/api/runs/next").json()
    assert summarized["step_name"] == "summarize"
    upstream = summarized["execution_context"][extracted["run_id"]]
    assert upstream["output"] == {"transcript": "hello"}
    complete(agent, summarized, {"summary": "short"})

    status = control.get(
        f"/api/workflow-invocations/{invocation['invocation_id']}"
    ).json()
    assert status["status"] == "completed"
