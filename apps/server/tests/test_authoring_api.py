from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from atlas.config import Settings
from atlas.main import create_app


def _client(tmp_path) -> TestClient:
    database_path = str(tmp_path / "atlas.sqlite3")
    app: FastAPI = create_app(
        Settings(
            auth={"admin_password": "test", "session_secret": "secret"},
            agents={"database_path": database_path, "shared_token": "test-token"},
            work={"database_path": database_path, "lease_ttl_seconds": 120},
        )
    )
    client = TestClient(app)
    client.headers["Authorization"] = "Bearer test-token"
    return client


def test_project_work_item_document_and_snapshot_workflow(tmp_path) -> None:
    client = _client(tmp_path)
    project_response = client.post(
        "/api/writing-projects",
        json={
            "title": "中心化知识系统论文",
            "goal": "形成一篇可以提交的 Markdown 论文",
            "audience": "同行评审",
        },
    )
    assert project_response.status_code == 200, project_response.text
    project = project_response.json()

    note = client.post(
        "/api/knowledge-notes",
        json={
            "title": "中心化状态",
            "claim": "长期工作需要稳定的中心化状态。",
            "status": "active",
        },
    ).json()
    document_response = client.post(
        "/api/documents",
        json={
            "project_id": project["project_id"],
            "title": "论文正文",
            "body_markdown": (
                "# 论文正文\n\n"
                f"使用 [[{note['knowledge_note_id']}|中心化状态]] 作为依据。\n\n"
                f"{{{{knowledge-page:{note['knowledge_note_id']}}}}}"
            ),
        },
    )
    assert document_response.status_code == 200, document_response.text
    document = document_response.json()
    assert document["linked_knowledge_note_ids"] == [note["knowledge_note_id"]]
    rendered = client.get(
        f"/api/documents/{document['document_id']}/rendered-markdown"
    )
    assert rendered.status_code == 200
    assert "## 中心化状态" in rendered.json()["body_markdown"]
    assert rendered.json()["embedded_knowledge_note_ids"] == [note["knowledge_note_id"]]

    work_item = client.post(
        "/api/work-items",
        json={
            "project_id": project["project_id"],
            "document_id": document["document_id"],
            "title": "完成初稿",
        },
    )
    assert work_item.status_code == 200, work_item.text
    completed = client.patch(
        f"/api/work-items/{work_item.json()['work_item_id']}",
        json={"expected_revision": 1, "status": "done"},
    )
    saved = client.patch(
        f"/api/documents/{document['document_id']}",
        json={
            "expected_revision": 1,
            "body_markdown": document["body_markdown"] + "\n\n完成。",
            "status": "final",
        },
    )
    snapshot = client.post(
        f"/api/documents/{document['document_id']}/versions",
        json={"label": "提交版"},
    )
    detail = client.get(f"/api/writing-projects/{project['project_id']}")

    assert completed.json()["status"] == "done"
    assert saved.json()["revision"] == 2
    assert snapshot.status_code == 200, snapshot.text
    assert snapshot.json()["revision"] == 2
    assert detail.json()["documents"][0]["status"] == "final"
    assert detail.json()["work_items"][0]["status"] == "done"


def test_authoring_uses_revision_conflicts_and_requires_control_auth(
    tmp_path,
) -> None:
    client = _client(tmp_path)
    project = client.post(
        "/api/writing-projects", json={"title": "项目", "goal": "完成输出"}
    ).json()
    updated = client.patch(
        f"/api/writing-projects/{project['project_id']}",
        json={"expected_revision": 1, "status": "on_hold"},
    )
    stale = client.patch(
        f"/api/writing-projects/{project['project_id']}",
        json={"expected_revision": 1, "status": "completed"},
    )
    assert updated.status_code == 200
    assert stale.status_code == 409

    anonymous = TestClient(client.app)
    assert anonymous.get("/api/writing-projects").status_code == 401
    assert anonymous.post("/api/work-items", json={}).status_code == 401
