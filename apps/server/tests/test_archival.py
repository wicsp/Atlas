from datetime import UTC, datetime
from pathlib import Path

from atlas.content.repository import ResourceRow
from atlas.db.session import create_sqlite_session_factory
from atlas.work.repository import ArtifactRow
from atlas.work.service import create_work_service


def test_archives_only_unreferenced_legacy_local_artifacts(tmp_path: Path) -> None:
    database_path = tmp_path / "atlas.sqlite3"
    service = create_work_service(database_path)
    session_factory = create_sqlite_session_factory(database_path)
    now = datetime(2026, 7, 29, 9, 0, tzinfo=UTC)

    with session_factory() as session, session.begin():
        session.add_all(
            [
                ArtifactRow(
                    artifact_id="art_orphan",
                    run_id="run_old",
                    name="old transcript",
                    uri="file:///tmp/old.txt",
                    content_type="text/plain",
                    size_bytes=3,
                    checksum=f"sha256:{'a' * 64}",
                    created_at=now.isoformat(),
                ),
                ArtifactRow(
                    artifact_id="art_referenced",
                    run_id="run_current",
                    name="summary",
                    uri="file:///tmp/current.md",
                    content_type="text/markdown",
                    size_bytes=3,
                    checksum=f"sha256:{'b' * 64}",
                    created_at=now.isoformat(),
                ),
                ArtifactRow(
                    artifact_id="art_central",
                    run_id="run_central",
                    name="central summary",
                    uri="atlas://artifacts/art_central",
                    content_type="text/markdown",
                    size_bytes=3,
                    checksum=f"sha256:{'c' * 64}",
                    created_at=now.isoformat(),
                ),
                ResourceRow(
                    resource_id="res_current",
                    source_id="src_current",
                    produced_by_run_id="run_current",
                    artifact_id="art_referenced",
                    kind="summary",
                    title="Current",
                    content_hash=f"sha256:{'b' * 64}",
                    generator_json='{"mode":"deterministic","name":"test","version":"1"}',
                    metadata_json="{}",
                    review_status="pending",
                    created_at=now.isoformat(),
                    updated_at=now.isoformat(),
                ),
            ]
        )

    assert service.archive_orphaned_legacy_artifacts() == 1
    assert service.archive_orphaned_legacy_artifacts() == 0
    assert service.list_archived_artifact_ids() == ["art_orphan"]
