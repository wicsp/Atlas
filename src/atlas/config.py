from __future__ import annotations

import os
import secrets
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "atlas.toml"


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)


class AuthSettings(BaseModel):
    password_hash: str | None = None
    admin_password: str | None = Field(default=None, exclude=True, repr=False)
    session_secret: str = Field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    session_max_age_seconds: int = Field(default=60 * 60 * 24 * 7, ge=60)
    cookie_secure: bool = False

    @property
    def password_configured(self) -> bool:
        return bool(self.admin_password or self.password_hash)


class AgentSettings(BaseModel):
    database_path: Path = PROJECT_ROOT / "data" / "atlas.sqlite3"
    shared_token: str | None = Field(default=None, exclude=True, repr=False)
    heartbeat_ttl_seconds: int = Field(default=90, ge=1, le=24 * 60 * 60)

    @field_validator("database_path")
    @classmethod
    def resolve_database_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return PROJECT_ROOT / value


class WorkSettings(BaseModel):
    database_path: Path = PROJECT_ROOT / "data" / "atlas.sqlite3"
    lease_ttl_seconds: int = Field(default=120, ge=1, le=3600)

    @field_validator("database_path")
    @classmethod
    def resolve_database_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return PROJECT_ROOT / value


class Sub2ApiSettings(BaseModel):
    enabled: bool = True
    docker_command: str = "docker"
    postgres_container: str = "sub2api-postgres"
    postgres_user: str = "sub2api"
    postgres_database: str = "sub2api"
    snapshot_database_path: Path = PROJECT_ROOT / "data" / "sub2api_snapshots.sqlite3"
    timeout: float = Field(default=5.0, gt=0, le=60)
    recent_window_minutes: int = Field(default=60, ge=1, le=24 * 60)
    refresh_interval_seconds: float = Field(default=60.0, gt=0, le=60 * 60)
    stale_after_seconds: float = Field(default=180.0, gt=0, le=24 * 60 * 60)

    @field_validator("snapshot_database_path")
    @classmethod
    def resolve_snapshot_database_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return PROJECT_ROOT / value


class ProbeHistorySettings(BaseModel):
    database_path: Path = PROJECT_ROOT / "data" / "probe_history.sqlite3"
    retention_hours: int = Field(default=24 * 7, ge=24, le=24 * 60)
    summary_window_hours: int = Field(default=24, ge=1, le=24 * 30)

    @field_validator("database_path")
    @classmethod
    def resolve_database_path(cls, value: Path) -> Path:
        if value.is_absolute():
            return value
        return PROJECT_ROOT / value


class ProbeTarget(BaseModel):
    name: str = Field(min_length=1)
    type: Literal["http", "tcp", "icmp"]
    timeout: float = Field(default=3.0, gt=0, le=60)
    url: str | None = None
    method: str = "GET"
    expected_status_min: int = Field(default=200, ge=100, le=599)
    expected_status_max: int = Field(default=399, ge=100, le=599)
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("method")
    @classmethod
    def normalize_method(cls, value: str) -> str:
        return value.upper()

    @model_validator(mode="after")
    def validate_target(self) -> ProbeTarget:
        if self.expected_status_min > self.expected_status_max:
            raise ValueError("expected_status_min must be <= expected_status_max")
        if self.type == "http" and not self.url:
            raise ValueError("http probes require url")
        if self.type == "tcp" and (not self.host or self.port is None):
            raise ValueError("tcp probes require host and port")
        if self.type == "icmp" and not self.host:
            raise ValueError("icmp probes require host")
        return self

    @property
    def display_target(self) -> str:
        if self.type == "http":
            return self.url or ""
        if self.type == "icmp":
            return self.host or ""
        return f"{self.host}:{self.port}"


class Settings(BaseModel):
    server: ServerSettings = Field(default_factory=ServerSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    agents: AgentSettings = Field(default_factory=AgentSettings)
    sub2api: Sub2ApiSettings = Field(default_factory=Sub2ApiSettings)
    probe_history: ProbeHistorySettings = Field(default_factory=ProbeHistorySettings)
    work: WorkSettings = Field(default_factory=WorkSettings)
    probes: list[ProbeTarget] = Field(default_factory=list)
    config_path: Path | None = None


def _read_toml(path: Path) -> dict:
    with path.open("rb") as file:
        loaded = tomllib.load(file)
    if not isinstance(loaded, dict):
        return {}
    return loaded


def _env_bool(name: str) -> bool:
    value = os.environ[name].strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value")


def load_settings(config_path: str | Path | None = None) -> Settings:
    selected_path = Path(
        config_path or os.getenv("ATLAS_CONFIG") or DEFAULT_CONFIG_PATH,
    )
    data: dict = {}
    loaded_path: Path | None = None
    if selected_path.exists():
        data = _read_toml(selected_path)
        loaded_path = selected_path

    auth_data = dict(data.get("auth", {}))
    admin_password = os.getenv("ATLAS_ADMIN_PASSWORD")
    session_secret = os.getenv("ATLAS_SESSION_SECRET")
    if admin_password:
        auth_data["admin_password"] = admin_password
    if session_secret:
        auth_data["session_secret"] = session_secret

    agents_data = dict(data.get("agents", {}))
    if agent_database_path := os.getenv("ATLAS_AGENT_DATABASE_PATH"):
        agents_data["database_path"] = agent_database_path
    if agent_shared_token := os.getenv("ATLAS_AGENT_SHARED_TOKEN"):
        agents_data["shared_token"] = agent_shared_token
    if heartbeat_ttl_seconds := os.getenv("ATLAS_AGENT_HEARTBEAT_TTL_SECONDS"):
        agents_data["heartbeat_ttl_seconds"] = heartbeat_ttl_seconds

    sub2api_data = dict(data.get("sub2api", {}))
    if "ATLAS_SUB2API_ENABLED" in os.environ:
        sub2api_data["enabled"] = _env_bool("ATLAS_SUB2API_ENABLED")
    if docker_command := os.getenv("ATLAS_SUB2API_DOCKER_COMMAND"):
        sub2api_data["docker_command"] = docker_command
    if postgres_container := os.getenv("ATLAS_SUB2API_POSTGRES_CONTAINER"):
        sub2api_data["postgres_container"] = postgres_container
    if postgres_user := os.getenv("ATLAS_SUB2API_POSTGRES_USER"):
        sub2api_data["postgres_user"] = postgres_user
    if postgres_database := os.getenv("ATLAS_SUB2API_POSTGRES_DATABASE"):
        sub2api_data["postgres_database"] = postgres_database
    if snapshot_database_path := os.getenv("ATLAS_SUB2API_SNAPSHOT_DATABASE_PATH"):
        sub2api_data["snapshot_database_path"] = snapshot_database_path
    if refresh_interval_seconds := os.getenv("ATLAS_SUB2API_REFRESH_INTERVAL_SECONDS"):
        sub2api_data["refresh_interval_seconds"] = refresh_interval_seconds
    if stale_after_seconds := os.getenv("ATLAS_SUB2API_STALE_AFTER_SECONDS"):
        sub2api_data["stale_after_seconds"] = stale_after_seconds


    work_data = dict(data.get("work", {}))
    if work_lease_ttl := os.getenv("ATLAS_WORK_LEASE_TTL_SECONDS"):
        work_data["lease_ttl_seconds"] = work_lease_ttl

    probe_history_data = dict(data.get("probe_history", {}))
    if probe_history_database_path := os.getenv("ATLAS_PROBE_HISTORY_DATABASE_PATH"):
        probe_history_data["database_path"] = probe_history_database_path
    if probe_history_retention_hours := os.getenv("ATLAS_PROBE_HISTORY_RETENTION_HOURS"):
        probe_history_data["retention_hours"] = probe_history_retention_hours
    if probe_history_summary_window_hours := os.getenv(
        "ATLAS_PROBE_HISTORY_SUMMARY_WINDOW_HOURS"
    ):
        probe_history_data["summary_window_hours"] = probe_history_summary_window_hours

    try:
        return Settings(
            server=ServerSettings(**data.get("server", {})),
            auth=AuthSettings(**auth_data),
            agents=AgentSettings(**agents_data),
            sub2api=Sub2ApiSettings(**sub2api_data),
            probe_history=ProbeHistorySettings(**probe_history_data),
            work=WorkSettings(**work_data),
            probes=[ProbeTarget(**item) for item in data.get("probes", [])],
            config_path=loaded_path,
        )
    except ValidationError as exc:
        raise ValueError(f"Invalid Atlas configuration: {exc}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
