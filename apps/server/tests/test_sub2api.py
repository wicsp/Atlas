from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atlas.config import Sub2ApiSettings
from atlas.sub2api import (
    Sub2ApiAccountsResponse,
    classify_account,
    collect_sub2api_accounts,
    get_sub2api_accounts,
    save_sub2api_snapshot,
)


def test_classify_account_ready() -> None:
    now = datetime(2026, 5, 25, tzinfo=UTC)

    state = classify_account({"status": "active", "schedulable": True}, now)

    assert state == "ready"


def test_classify_account_rate_limited_before_unschedulable() -> None:
    now = datetime(2026, 5, 25, tzinfo=UTC)
    reset_at = (now + timedelta(minutes=20)).isoformat()

    state = classify_account(
        {
            "status": "active",
            "schedulable": False,
            "rate_limit_reset_at": reset_at,
        },
        now,
    )

    assert state == "rate_limited"


def test_classify_account_expired() -> None:
    now = datetime(2026, 5, 25, tzinfo=UTC)
    expires_at = (now - timedelta(seconds=1)).isoformat()

    state = classify_account(
        {
            "status": "active",
            "schedulable": True,
            "expires_at": expires_at,
        },
        now,
    )

    assert state == "expired"


async def test_disabled_sub2api_monitor_returns_empty_response() -> None:
    response = await get_sub2api_accounts(
        Sub2ApiSettings(enabled=False, postgres_container="sub2api-postgres"),
    )

    assert response.status == "disabled"
    assert response.source == "sub2api-postgres"
    assert response.summary.total == 0
    assert response.accounts == []


async def test_collect_sub2api_accounts_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_psql_json(_settings: Sub2ApiSettings, _sql: str) -> list[dict]:
        if "today_tokens" in _sql:
            return [
                {
                    "usage_5h_percent": 35,
                    "usage_5h_reset_after_seconds": 15360,
                    "usage_7d_percent": 9,
                    "usage_7d_reset_after_seconds": 511200,
                    "today_tokens": 123456,
                    "today_cost_usd": 12.5,
                },
            ]

        return [
            {
                "id": 1,
                "name": "ready-account",
                "platform": "openai",
                "type": "apikey",
                "status": "active",
                "schedulable": True,
                "priority": 1,
                "concurrency": 10,
                "groups": ["default", "GPT-5.5"],
                "recent_requests": 3,
                "recent_cost_usd": 0.125,
                "usage_5h_requests": 4,
                "usage_5h_cost_usd": 0.4,
                "usage_7d_requests": 10,
                "usage_7d_cost_usd": 1.25,
            },

            {
                "id": 3,
                "name": "gpt-paused-account",
                "platform": "openai",
                "type": "oauth",
                "status": "paused",
                "schedulable": False,
                "priority": 3,
                "concurrency": 10,
                "groups": ["GPT-5.5"],
                "error_message": "Unauthorized (401): Unauthorized",
                "recent_requests": 2,
                "recent_cost_usd": 0.25,
                "usage_5h_requests": 2,
                "usage_5h_cost_usd": 0.2,
                "usage_7d_requests": 6,
                "usage_7d_cost_usd": 0.8,
            },
            {
                "id": 2,
                "name": "paused-account",
                "platform": "anthropic",
                "type": "oauth",
                "status": "paused",
                "schedulable": False,
                "priority": 5,
                "concurrency": 3,
                "groups": [],
                "recent_requests": 0,
                "recent_cost_usd": 0,
            },
        ]

    monkeypatch.setattr("atlas.sub2api._run_psql_json", fake_run_psql_json)

    response = await collect_sub2api_accounts(Sub2ApiSettings())

    assert response.status == "ok"
    assert response.summary.total == 3
    assert response.summary.ready == 1
    assert response.summary.attention == 2
    assert response.summary.recent_requests == 5
    assert response.summary.recent_cost_usd == 0.375
    assert response.summary.by_platform == {"anthropic": 1, "openai": 2}
    assert response.summary.by_state == {"paused": 1, "ready": 1, "unschedulable": 1}
    assert response.summary.gpt_5_5.total == 2
    assert response.summary.gpt_5_5.ready == 1
    assert response.summary.gpt_5_5.unavailable == 1
    assert response.summary.gpt_5_5.usage_5h_requests == 4
    assert response.summary.gpt_5_5.usage_5h_cost_usd == 0.4
    assert response.summary.gpt_5_5.usage_7d_requests == 10
    assert response.summary.gpt_5_5.usage_7d_cost_usd == 1.25
    assert response.summary.gpt_5_5.usage_5h_percent == 35
    assert response.summary.gpt_5_5.usage_5h_reset_after_seconds == 15360
    assert response.summary.gpt_5_5.usage_7d_percent == 9
    assert response.summary.gpt_5_5.usage_7d_reset_after_seconds == 511200
    assert response.summary.gpt_5_5.today_tokens == 123456
    assert response.summary.gpt_5_5.today_cost_usd == 12.5
    assert [account.state for account in response.accounts] == ["ready", "unschedulable", "paused"]
    assert response.accounts[0].usage_5h_requests == 4
    assert response.accounts[0].usage_7d_cost_usd == 1.25


async def test_get_sub2api_accounts_reads_saved_snapshot(tmp_path) -> None:
    snapshot_path = tmp_path / "snapshots.sqlite3"
    settings = Sub2ApiSettings(snapshot_database_path=snapshot_path, stale_after_seconds=300)
    collected = Sub2ApiAccountsResponse(
        status="ok",
        source="sub2api-postgres",
        checked_at=datetime.now(UTC),
        summary=_summary_fixture(),
        accounts=[],
    )
    save_sub2api_snapshot(snapshot_path, collected)

    response = await get_sub2api_accounts(settings, refreshing=True)

    assert response.status == "ok"
    assert response.refreshing is True
    assert response.stale is False
    assert response.snapshot_age_seconds is not None


async def test_error_snapshot_preserves_last_success_payload(tmp_path) -> None:
    snapshot_path = tmp_path / "snapshots.sqlite3"
    settings = Sub2ApiSettings(snapshot_database_path=snapshot_path)
    success = Sub2ApiAccountsResponse(
        status="ok",
        source="sub2api-postgres",
        checked_at=datetime.now(UTC),
        summary=_summary_fixture(total=2, ready=2),
        accounts=[],
    )
    save_sub2api_snapshot(snapshot_path, success)
    failure = Sub2ApiAccountsResponse(
        status="error",
        source="sub2api-postgres",
        checked_at=datetime.now(UTC),
        error="psql failed",
        summary=_summary_fixture(),
        accounts=[],
    )
    save_sub2api_snapshot(snapshot_path, failure)

    response = await get_sub2api_accounts(settings)

    assert response.status == "error"
    assert response.error == "psql failed"
    assert response.stale is True
    assert response.summary.total == 2
    assert response.summary.ready == 2
    assert response.last_success_at is not None
    assert response.last_error_at is not None


async def test_missing_snapshot_returns_stale_error(tmp_path) -> None:
    response = await get_sub2api_accounts(
        Sub2ApiSettings(snapshot_database_path=tmp_path / "missing.sqlite3"),
    )

    assert response.status == "error"
    assert response.stale is True
    assert response.error == "No Sub2API snapshot is available yet."


def _summary_fixture(
    total: int = 0,
    ready: int = 0,
):
    from atlas.sub2api import Sub2ApiAccountSummary

    return Sub2ApiAccountSummary(
        total=total,
        ready=ready,
        attention=total - ready,
    )
