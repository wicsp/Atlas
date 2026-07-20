from __future__ import annotations

import asyncio
import json
import sqlite3
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .config import Sub2ApiSettings

MonitorStatus = Literal["disabled", "ok", "error"]
RefreshStatus = Literal["disabled", "scheduled", "running"]
SNAPSHOT_ROW_ID = 1


class Sub2ApiAccount(BaseModel):
    id: int
    name: str
    platform: str
    type: str
    status: str
    state: str
    schedulable: bool
    priority: int
    concurrency: int
    groups: list[str]
    error_message: str | None = None
    temp_unschedulable_reason: str | None = None
    last_used_at: datetime | None = None
    rate_limited_at: datetime | None = None
    rate_limit_reset_at: datetime | None = None
    overload_until: datetime | None = None
    temp_unschedulable_until: datetime | None = None
    expires_at: datetime | None = None
    recent_requests: int = 0
    recent_cost_usd: float = 0
    recent_used_at: datetime | None = None
    usage_5h_requests: int = 0
    usage_5h_cost_usd: float = 0
    usage_7d_requests: int = 0
    usage_7d_cost_usd: float = 0


class Sub2ApiGroupSummary(BaseModel):
    name: str = "GPT-5.5"
    total: int = 0
    ready: int = 0
    unavailable: int = 0
    usage_5h_requests: int = 0
    usage_5h_cost_usd: float = 0
    usage_7d_requests: int = 0
    usage_7d_cost_usd: float = 0
    usage_5h: float = 0
    rate_limit_5h: float = 0
    usage_7d: float = 0
    rate_limit_7d: float = 0
    usage_5h_percent: float | None = None
    usage_5h_reset_after_seconds: int | None = None
    usage_7d_percent: float | None = None
    usage_7d_reset_after_seconds: int | None = None
    today_tokens: int = 0
    today_cost_usd: float = 0
    quota_used: float = 0
    quota: float = 0


class Sub2ApiAccountSummary(BaseModel):
    total: int = 0
    ready: int = 0
    attention: int = 0
    recent_requests: int = 0
    recent_cost_usd: float = 0
    by_state: dict[str, int] = Field(default_factory=dict)
    by_platform: dict[str, int] = Field(default_factory=dict)
    gpt_5_5: Sub2ApiGroupSummary = Field(default_factory=Sub2ApiGroupSummary)


class Sub2ApiAccountsResponse(BaseModel):
    status: MonitorStatus
    source: str
    checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    snapshot_age_seconds: float | None = None
    stale: bool = False
    refreshing: bool = False
    error: str | None = None
    summary: Sub2ApiAccountSummary
    accounts: list[Sub2ApiAccount]


class Sub2ApiRefreshResponse(BaseModel):
    status: RefreshStatus
    scheduled: bool
    refreshing: bool


class Sub2ApiMonitorError(RuntimeError):
    pass


class Sub2ApiSnapshotCollector:
    def __init__(self, settings: Sub2ApiSettings) -> None:
        self._settings = settings
        self._refresh_event = asyncio.Event()
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None

    @property
    def refreshing(self) -> bool:
        return self._lock.locked()

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._run(), name="sub2api-snapshot-collector")

    async def stop(self) -> None:
        task = self._task
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        self._task = None

    def request_refresh(self) -> bool:
        was_pending = self._refresh_event.is_set()
        self._refresh_event.set()
        return not was_pending

    async def refresh_once(self) -> Sub2ApiAccountsResponse:
        async with self._lock:
            response = await collect_sub2api_accounts(self._settings)
            try:
                await asyncio.to_thread(
                    save_sub2api_snapshot,
                    self._settings.snapshot_database_path,
                    response,
                )
            except (OSError, sqlite3.DatabaseError) as exc:
                return response.model_copy(
                    update={
                        "status": "error",
                        "error": f"Could not save Sub2API snapshot: {exc}",
                        "last_error_at": datetime.now(UTC),
                        "stale": True,
                    },
                )
            return response

    async def _run(self) -> None:
        while True:
            self._refresh_event.clear()
            await self.refresh_once()
            try:
                await asyncio.wait_for(
                    self._refresh_event.wait(),
                    timeout=self._settings.refresh_interval_seconds,
                )
            except TimeoutError:
                continue


async def collect_sub2api_accounts(settings: Sub2ApiSettings) -> Sub2ApiAccountsResponse:
    source = settings.postgres_container
    if not settings.enabled:
        return Sub2ApiAccountsResponse(
            status="disabled",
            source=source,
            summary=Sub2ApiAccountSummary(),
            accounts=[],
        )

    checked_at = datetime.now(UTC)
    try:
        sql = _build_accounts_sql(settings.recent_window_minutes)
        records = await _run_psql_json(settings, sql)
        gpt_5_5_records = await _run_psql_json(settings, _build_gpt_5_5_summary_sql())
        accounts = [_account_from_record(record, checked_at) for record in records]
        gpt_5_5_metrics = gpt_5_5_records[0] if gpt_5_5_records else {}
    except (Sub2ApiMonitorError, json.JSONDecodeError, OSError, ValueError, ValidationError) as exc:
        return Sub2ApiAccountsResponse(
            status="error",
            source=source,
            checked_at=checked_at,
            last_error_at=checked_at,
            stale=True,
            error=str(exc),
            summary=Sub2ApiAccountSummary(),
            accounts=[],
        )

    return Sub2ApiAccountsResponse(
        status="ok",
        source=source,
        checked_at=checked_at,
        last_success_at=checked_at,
        snapshot_age_seconds=0.0,
        summary=_summarize_accounts(accounts, gpt_5_5_metrics),
        accounts=accounts,
    )


async def get_sub2api_accounts(
    settings: Sub2ApiSettings,
    *,
    refreshing: bool = False,
) -> Sub2ApiAccountsResponse:
    source = settings.postgres_container
    if not settings.enabled:
        return Sub2ApiAccountsResponse(
            status="disabled",
            source=source,
            summary=Sub2ApiAccountSummary(),
            accounts=[],
        )

    try:
        return await asyncio.to_thread(_load_sub2api_snapshot, settings, refreshing)
    except (OSError, sqlite3.DatabaseError, json.JSONDecodeError, ValidationError) as exc:
        return Sub2ApiAccountsResponse(
            status="error",
            source=source,
            stale=True,
            refreshing=refreshing,
            error=f"Could not read Sub2API snapshot: {exc}",
            summary=Sub2ApiAccountSummary(),
            accounts=[],
        )


def save_sub2api_snapshot(path: Path, response: Sub2ApiAccountsResponse) -> None:
    path = Path(path)
    now = datetime.now(UTC)
    with _connect_snapshot_database(path) as connection:
        _ensure_snapshot_schema(connection)
        row = _select_snapshot_row(connection)
        last_error_at = row["last_error_at"] if row else None
        last_success_at = row["last_success_at"] if row else None
        payload = row["payload"] if row else None

        if response.status == "ok":
            success_at = _datetime_to_storage(response.checked_at or now)
            payload_response = response.model_copy(
                update={
                    "last_success_at": response.checked_at or now,
                    "snapshot_age_seconds": 0.0,
                    "stale": False,
                    "refreshing": False,
                    "error": None,
                },
            )
            payload = json.dumps(payload_response.model_dump(mode="json"), ensure_ascii=False)
            status = "ok"
            checked_at = success_at
            last_success_at = success_at
            error = None
        else:
            checked_at = _datetime_to_storage(response.checked_at or now)
            last_error_at = checked_at
            status = "error"
            error = response.error
            if payload is None:
                payload = json.dumps(response.model_dump(mode="json"), ensure_ascii=False)

        connection.execute(
            """
            INSERT INTO sub2api_account_snapshot (
                id,
                payload,
                status,
                source,
                checked_at,
                last_success_at,
                last_error_at,
                error,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                payload = excluded.payload,
                status = excluded.status,
                source = excluded.source,
                checked_at = excluded.checked_at,
                last_success_at = excluded.last_success_at,
                last_error_at = excluded.last_error_at,
                error = excluded.error,
                updated_at = excluded.updated_at
            """,
            (
                SNAPSHOT_ROW_ID,
                payload,
                status,
                response.source,
                checked_at,
                last_success_at,
                last_error_at,
                error,
                _datetime_to_storage(now),
            ),
        )
        connection.commit()


def classify_account(record: dict[str, Any], now: datetime) -> str:
    status = str(record.get("status") or "unknown")
    if _is_past(record.get("expires_at"), now):
        return "expired"
    if _is_future(record.get("temp_unschedulable_until"), now):
        return "temp_unschedulable"
    if _is_future(record.get("overload_until"), now):
        return "overloaded"
    if _is_future(record.get("rate_limit_reset_at"), now):
        return "rate_limited"
    if record.get("error_message") and not bool(record.get("schedulable")):
        return "unschedulable"
    if status != "active":
        return status
    if not bool(record.get("schedulable")):
        return "unschedulable"
    if record.get("error_message"):
        return "error"
    return "ready"


def _load_sub2api_snapshot(
    settings: Sub2ApiSettings,
    refreshing: bool,
) -> Sub2ApiAccountsResponse:
    now = datetime.now(UTC)
    with _connect_snapshot_database(settings.snapshot_database_path) as connection:
        _ensure_snapshot_schema(connection)
        row = _select_snapshot_row(connection)

    if row is None:
        return Sub2ApiAccountsResponse(
            status="error",
            source=settings.postgres_container,
            stale=True,
            refreshing=refreshing,
            error="No Sub2API snapshot is available yet.",
            summary=Sub2ApiAccountSummary(),
            accounts=[],
        )

    payload = json.loads(row["payload"])
    response = Sub2ApiAccountsResponse.model_validate(payload)
    checked_at = _parse_datetime(row["checked_at"]) or response.checked_at
    last_success_at = _parse_datetime(row["last_success_at"]) or response.last_success_at
    last_error_at = _parse_datetime(row["last_error_at"]) or response.last_error_at
    snapshot_age_seconds = _snapshot_age_seconds(last_success_at, now)
    stale = row["status"] == "error" or snapshot_age_seconds is None
    if snapshot_age_seconds is not None:
        stale = stale or snapshot_age_seconds > settings.stale_after_seconds

    return response.model_copy(
        update={
            "status": row["status"],
            "source": row["source"] or settings.postgres_container,
            "checked_at": checked_at,
            "last_success_at": last_success_at,
            "last_error_at": last_error_at,
            "snapshot_age_seconds": snapshot_age_seconds,
            "stale": stale,
            "refreshing": refreshing,
            "error": row["error"],
        },
    )


def _connect_snapshot_database(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _ensure_snapshot_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS sub2api_account_snapshot (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            payload TEXT NOT NULL,
            status TEXT NOT NULL,
            source TEXT NOT NULL,
            checked_at TEXT,
            last_success_at TEXT,
            last_error_at TEXT,
            error TEXT,
            updated_at TEXT NOT NULL
        )
        """,
    )


def _select_snapshot_row(connection: sqlite3.Connection) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            payload,
            status,
            source,
            checked_at,
            last_success_at,
            last_error_at,
            error
        FROM sub2api_account_snapshot
        WHERE id = ?
        """,
        (SNAPSHOT_ROW_ID,),
    ).fetchone()


def _build_accounts_sql(recent_window_minutes: int) -> str:
    return f"""
WITH account_groups_agg AS (
    SELECT
        ag.account_id,
        COALESCE(
            jsonb_agg(g.name ORDER BY ag.priority, g.name) FILTER (WHERE g.id IS NOT NULL),
            '[]'::jsonb
        ) AS groups
    FROM account_groups ag
    JOIN groups g ON g.id = ag.group_id AND g.deleted_at IS NULL
    GROUP BY ag.account_id
),
recent_usage AS (
    SELECT
        account_id,
        count(*)::int AS recent_requests,
        COALESCE(sum(total_cost), 0)::float8 AS recent_cost_usd,
        max(created_at) AS recent_used_at
    FROM usage_logs
    WHERE created_at >= now() - make_interval(mins => {recent_window_minutes})
    GROUP BY account_id
),
usage_windows AS (
    SELECT
        account_id,
        (
            count(*) FILTER (WHERE created_at >= now() - interval '5 hours')
        )::int AS usage_5h_requests,
        (
            COALESCE(
                sum(total_cost) FILTER (WHERE created_at >= now() - interval '5 hours'),
                0
            )
        )::float8 AS usage_5h_cost_usd,
        (
            count(*) FILTER (WHERE created_at >= now() - interval '7 days')
        )::int AS usage_7d_requests,
        (
            COALESCE(
                sum(total_cost) FILTER (WHERE created_at >= now() - interval '7 days'),
                0
            )
        )::float8 AS usage_7d_cost_usd
    FROM usage_logs
    WHERE created_at >= now() - interval '7 days'
    GROUP BY account_id
)
SELECT COALESCE(jsonb_agg(jsonb_build_object(
    'id', a.id,
    'name', a.name,
    'platform', a.platform,
    'type', a.type,
    'status', a.status,
    'schedulable', a.schedulable,
    'priority', a.priority,
    'concurrency', a.concurrency,
    'groups', COALESCE(aga.groups, '[]'::jsonb),
    'error_message', a.error_message,
    'temp_unschedulable_reason', a.temp_unschedulable_reason,
    'last_used_at', a.last_used_at,
    'rate_limited_at', a.rate_limited_at,
    'rate_limit_reset_at', a.rate_limit_reset_at,
    'overload_until', a.overload_until,
    'temp_unschedulable_until', a.temp_unschedulable_until,
    'expires_at', a.expires_at,
    'recent_requests', COALESCE(ru.recent_requests, 0),
    'recent_cost_usd', COALESCE(ru.recent_cost_usd, 0),
    'recent_used_at', ru.recent_used_at,
    'usage_5h_requests', COALESCE(uw.usage_5h_requests, 0),
    'usage_5h_cost_usd', COALESCE(uw.usage_5h_cost_usd, 0),
    'usage_7d_requests', COALESCE(uw.usage_7d_requests, 0),
    'usage_7d_cost_usd', COALESCE(uw.usage_7d_cost_usd, 0)
) ORDER BY a.platform, a.priority, a.name, a.id), '[]'::jsonb)
FROM accounts a
LEFT JOIN account_groups_agg aga ON aga.account_id = a.id
LEFT JOIN recent_usage ru ON ru.account_id = a.id
LEFT JOIN usage_windows uw ON uw.account_id = a.id
WHERE a.deleted_at IS NULL;
""".strip()


def _build_gpt_5_5_summary_sql() -> str:
    return """
WITH target_group AS (
    SELECT id
    FROM groups
    WHERE deleted_at IS NULL AND name = 'GPT-5.5'
    LIMIT 1
),
gpt_accounts AS (
    SELECT a.*
    FROM accounts a
    JOIN account_groups ag ON ag.account_id = a.id
    JOIN target_group tg ON tg.id = ag.group_id
    WHERE a.deleted_at IS NULL
),
codex_usage_candidates AS (
    SELECT
        CASE
            WHEN a.extra->>'codex_5h_used_percent' ~ '^[0-9]+(\\.[0-9]+)?$'
                THEN (a.extra->>'codex_5h_used_percent')::float8
        END AS usage_5h_percent,
        CASE
            WHEN a.extra->>'codex_5h_reset_after_seconds' ~ '^[0-9]+$'
                THEN (a.extra->>'codex_5h_reset_after_seconds')::int
        END AS usage_5h_reset_after_seconds,
        CASE
            WHEN a.extra->>'codex_7d_used_percent' ~ '^[0-9]+(\\.[0-9]+)?$'
                THEN (a.extra->>'codex_7d_used_percent')::float8
        END AS usage_7d_percent,
        CASE
            WHEN a.extra->>'codex_7d_reset_after_seconds' ~ '^[0-9]+$'
                THEN (a.extra->>'codex_7d_reset_after_seconds')::int
        END AS usage_7d_reset_after_seconds,
        a.updated_at
    FROM gpt_accounts a
    WHERE a.status = 'active'
),
codex_usage AS (
    SELECT
        usage_5h_percent,
        usage_5h_reset_after_seconds,
        usage_7d_percent,
        usage_7d_reset_after_seconds
    FROM codex_usage_candidates
    WHERE usage_5h_percent IS NOT NULL OR usage_7d_percent IS NOT NULL
    ORDER BY updated_at DESC NULLS LAST
    LIMIT 1
),
dashboard_today AS (
    SELECT
        (
            COALESCE(input_tokens, 0)
            + COALESCE(output_tokens, 0)
            + COALESCE(cache_creation_tokens, 0)
            + COALESCE(cache_read_tokens, 0)
        )::bigint AS today_tokens,
        COALESCE(total_cost, 0)::float8 AS today_cost_usd
    FROM usage_dashboard_daily
    WHERE bucket_date = current_date
    ORDER BY computed_at DESC NULLS LAST
    LIMIT 1
),
usage_logs_today AS (
    SELECT
        COALESCE(sum(
            COALESCE(input_tokens, 0)
            + COALESCE(output_tokens, 0)
            + COALESCE(cache_creation_tokens, 0)
            + COALESCE(cache_read_tokens, 0)
            + COALESCE(image_output_tokens, 0)
        ), 0)::bigint AS today_tokens,
        COALESCE(sum(total_cost), 0)::float8 AS today_cost_usd
    FROM usage_logs
    WHERE created_at >= date_trunc('day', now())
),
today_usage AS (
    SELECT
        COALESCE(
            (SELECT today_tokens FROM dashboard_today),
            (SELECT today_tokens FROM usage_logs_today),
            0
        ) AS today_tokens,
        COALESCE(
            (SELECT today_cost_usd FROM dashboard_today),
            (SELECT today_cost_usd FROM usage_logs_today),
            0
        ) AS today_cost_usd
)
SELECT jsonb_build_array(jsonb_build_object(
    'usage_5h_percent', cu.usage_5h_percent,
    'usage_5h_reset_after_seconds', cu.usage_5h_reset_after_seconds,
    'usage_7d_percent', cu.usage_7d_percent,
    'usage_7d_reset_after_seconds', cu.usage_7d_reset_after_seconds,
    'today_tokens', tu.today_tokens,
    'today_cost_usd', tu.today_cost_usd
))
FROM today_usage tu
LEFT JOIN codex_usage cu ON true;
""".strip()


async def _run_psql_json(settings: Sub2ApiSettings, sql: str) -> list[dict[str, Any]]:
    process = await asyncio.create_subprocess_exec(
        settings.docker_command,
        "exec",
        settings.postgres_container,
        "psql",
        "-U",
        settings.postgres_user,
        "-d",
        settings.postgres_database,
        "-tA",
        "--set",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=settings.timeout,
        )
    except TimeoutError as exc:
        process.kill()
        await process.communicate()
        raise Sub2ApiMonitorError(
            f"Timed out after {settings.timeout:.1f}s reading sub2api accounts",
        ) from exc

    if process.returncode != 0:
        error = stderr.decode(errors="replace").strip() or "psql command failed"
        raise Sub2ApiMonitorError(error)

    payload = stdout.decode(errors="replace").strip()
    if not payload:
        return []
    loaded = json.loads(payload)
    if not isinstance(loaded, list):
        raise Sub2ApiMonitorError("sub2api account query returned a non-list payload")
    return [record for record in loaded if isinstance(record, dict)]


def _account_from_record(record: dict[str, Any], now: datetime) -> Sub2ApiAccount:
    return Sub2ApiAccount(
        **{
            **record,
            "state": classify_account(record, now),
            "groups": _clean_groups(record.get("groups")),
            "error_message": _clean_text(record.get("error_message")),
            "temp_unschedulable_reason": _clean_text(record.get("temp_unschedulable_reason")),
            "recent_requests": int(record.get("recent_requests") or 0),
            "recent_cost_usd": round(float(record.get("recent_cost_usd") or 0), 6),
            "usage_5h_requests": int(record.get("usage_5h_requests") or 0),
            "usage_5h_cost_usd": round(float(record.get("usage_5h_cost_usd") or 0), 6),
            "usage_7d_requests": int(record.get("usage_7d_requests") or 0),
            "usage_7d_cost_usd": round(float(record.get("usage_7d_cost_usd") or 0), 6),
        },
    )



def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return round(float(value), 6)


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _is_gpt_5_5_available(account: Sub2ApiAccount) -> bool:
    return account.status == "active" and account.state != "expired"


def _summarize_accounts(
    accounts: list[Sub2ApiAccount],
    gpt_5_5_metrics: dict[str, Any] | None = None,
) -> Sub2ApiAccountSummary:
    by_state = Counter(account.state for account in accounts)
    by_platform = Counter(account.platform for account in accounts)
    recent_requests = sum(account.recent_requests for account in accounts)
    recent_cost_usd = sum(account.recent_cost_usd for account in accounts)
    ready = by_state.get("ready", 0)
    gpt_5_5_accounts = [account for account in accounts if "GPT-5.5" in account.groups]
    gpt_5_5_available_accounts = [
        account for account in gpt_5_5_accounts if _is_gpt_5_5_available(account)
    ]
    gpt_5_5_metrics = gpt_5_5_metrics or {}
    return Sub2ApiAccountSummary(
        total=len(accounts),
        ready=ready,
        attention=len(accounts) - ready,
        recent_requests=recent_requests,
        recent_cost_usd=round(recent_cost_usd, 6),
        by_state=dict(sorted(by_state.items())),
        by_platform=dict(sorted(by_platform.items())),
        gpt_5_5=Sub2ApiGroupSummary(
            total=len(gpt_5_5_accounts),
            ready=len(gpt_5_5_available_accounts),
            unavailable=len(gpt_5_5_accounts) - len(gpt_5_5_available_accounts),
            usage_5h_requests=sum(
                account.usage_5h_requests for account in gpt_5_5_available_accounts
            ),
            usage_5h_cost_usd=round(
                sum(account.usage_5h_cost_usd for account in gpt_5_5_available_accounts),
                6,
            ),
            usage_7d_requests=sum(
                account.usage_7d_requests for account in gpt_5_5_available_accounts
            ),
            usage_7d_cost_usd=round(
                sum(account.usage_7d_cost_usd for account in gpt_5_5_available_accounts),
                6,
            ),
            usage_5h=round(float(gpt_5_5_metrics.get("usage_5h") or 0), 6),
            rate_limit_5h=round(float(gpt_5_5_metrics.get("rate_limit_5h") or 0), 6),
            usage_7d=round(float(gpt_5_5_metrics.get("usage_7d") or 0), 6),
            rate_limit_7d=round(float(gpt_5_5_metrics.get("rate_limit_7d") or 0), 6),
            usage_5h_percent=_optional_float(gpt_5_5_metrics.get("usage_5h_percent")),
            usage_5h_reset_after_seconds=_optional_int(gpt_5_5_metrics.get("usage_5h_reset_after_seconds")),
            usage_7d_percent=_optional_float(gpt_5_5_metrics.get("usage_7d_percent")),
            usage_7d_reset_after_seconds=_optional_int(gpt_5_5_metrics.get("usage_7d_reset_after_seconds")),
            today_tokens=int(gpt_5_5_metrics.get("today_tokens") or 0),
            today_cost_usd=round(float(gpt_5_5_metrics.get("today_cost_usd") or 0), 6),
            quota_used=round(float(gpt_5_5_metrics.get("quota_used") or 0), 6),
            quota=round(float(gpt_5_5_metrics.get("quota") or 0), 6),
        ),
    )


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _datetime_to_storage(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _snapshot_age_seconds(last_success_at: datetime | None, now: datetime) -> float | None:
    if last_success_at is None:
        return None
    return round(max(0.0, (now - last_success_at).total_seconds()), 1)


def _is_future(value: Any, now: datetime) -> bool:
    parsed = _parse_datetime(value)
    return parsed is not None and parsed > now


def _is_past(value: Any, now: datetime) -> bool:
    parsed = _parse_datetime(value)
    return parsed is not None and parsed <= now


def _clean_groups(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _clean_text(value: Any, limit: int = 240) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1]}..."
