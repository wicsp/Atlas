import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from atlas.config import AgentSettings, AuthSettings, Settings, Sub2ApiSettings, WorkSettings
from atlas.db.session import create_sqlite_session_factory
from atlas.main import create_app
from atlas.work.repository import ArtifactContentRow, ArtifactRow, RunRow


def make_client(tmp_path: Path) -> TestClient:
    database_path = tmp_path / "atlas.sqlite3"
    settings = Settings(
        auth=AuthSettings(
            admin_password="test-password",
            session_secret="test-session-secret",
        ),
        agents=AgentSettings(
            database_path=database_path,
            shared_token="test-control-token",
        ),
        work=WorkSettings(database_path=database_path),
        sub2api=Sub2ApiSettings(enabled=False),
    )
    client = TestClient(create_app(settings))
    client.headers["Authorization"] = "Bearer test-control-token"
    return client


def create_paper(client: TestClient, key: str, title: str) -> dict:
    response = client.post(
        "/api/sources",
        json={
            "source_key": f"arxiv:{key}",
            "kind": "paper",
            "canonical_uri": f"https://arxiv.org/abs/{key}",
            "title": title,
            "external_ids": {"arxiv_id": key},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def add_central_fulltext(client: TestClient, source_id: str, content: str) -> None:
    now = datetime(2026, 7, 29, 9, 0, tzinfo=UTC).isoformat()
    session_factory = create_sqlite_session_factory(
        client.app.state.settings.work.database_path
    )
    with session_factory() as session, session.begin():
        session.add(
            RunRow(
                run_id="run_fulltext_search",
                project_id="paper-library",
                job_name="extract",
                capabilities_json="[]",
                input_json=json.dumps({"workflow_input": {"source_id": source_id}}),
                output_json="{}",
                status="completed",
                agent_id="runner",
                lease_expires_at=None,
                attempt_number=1,
                max_attempts=3,
                priority=0,
                metadata_json="{}",
                error_message=None,
                created_at=now,
                started_at=now,
                completed_at=now,
            )
        )
        session.add(
            ArtifactRow(
                artifact_id="art_fulltext_search",
                run_id="run_fulltext_search",
                name="paper-fulltext",
                uri="atlas://artifacts/art_fulltext_search",
                content_type="text/plain",
                size_bytes=len(content.encode()),
                checksum=f"sha256:{'d' * 64}",
                created_at=now,
            )
        )
        session.add(
            ArtifactContentRow(
                artifact_id="art_fulltext_search",
                content=content,
                created_at=now,
                updated_at=now,
            )
        )


def test_paper_library_tags_search_citations_and_comparison(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    first = create_paper(client, "2607.00001", "Agent Safety One")
    second = create_paper(client, "2607.00002", "Agent Safety Two")
    add_central_fulltext(
        client,
        first["source_id"],
        "The hidden evaluation phrase is mechanistic anomaly detection.",
    )

    updated = client.patch(
        f"/api/papers/{first['source_id']}",
        json={
            "tags": ["Agent", "Safety", "agent"],
            "categories": ["Security"],
            "citation_source_ids": [second["source_id"]],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["tags"] == ["Agent", "Safety"]
    assert updated.json()["categories"] == ["Security"]

    second_update = client.patch(
        f"/api/papers/{second['source_id']}",
        json={
            "tags": ["Safety"],
            "categories": ["Security", "Evaluation"],
            "citation_source_ids": [],
        },
    )
    assert second_update.status_code == 200, second_update.text

    search = client.get("/api/papers", params={"q": "agent safety", "tag": "agent"})
    assert search.status_code == 200, search.text
    assert [item["source"]["source_id"] for item in search.json()] == [first["source_id"]]
    fulltext_search = client.get(
        "/api/papers",
        params={"q": "mechanistic anomaly detection"},
    )
    assert fulltext_search.status_code == 200, fulltext_search.text
    assert [item["source"]["source_id"] for item in fulltext_search.json()] == [
        first["source_id"]
    ]

    comparison = client.post(
        "/api/papers/compare",
        json={"source_ids": [first["source_id"], second["source_id"]]},
    )
    assert comparison.status_code == 200, comparison.text
    payload = comparison.json()
    assert len(payload["papers"]) == 2
    assert payload["shared_tags"] == ["Safety"]
    assert payload["shared_categories"] == ["Security"]
    assert payload["citation_edges"] == [
        {
            "citing_source_id": first["source_id"],
            "cited_source_id": second["source_id"],
        }
    ]


def test_paper_library_rejects_self_citation_and_non_paper_source(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    paper = create_paper(client, "2607.00003", "Paper")
    self_citation = client.patch(
        f"/api/papers/{paper['source_id']}",
        json={"citation_source_ids": [paper["source_id"]]},
    )
    assert self_citation.status_code == 422

    video = client.post(
        "/api/sources",
        json={
            "source_key": "bilibili:BV1TEST",
            "kind": "video",
            "canonical_uri": "https://www.bilibili.com/video/BV1TEST",
            "title": "Not a paper",
        },
    ).json()
    invalid = client.patch(
        f"/api/papers/{video['source_id']}",
        json={"tags": ["paper"]},
    )
    assert invalid.status_code == 409
