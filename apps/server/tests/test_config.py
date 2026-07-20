from atlas.config import AuthSettings, Settings, load_settings


def test_missing_config_file_uses_safe_defaults(tmp_path) -> None:
    settings = load_settings(tmp_path / "missing.toml")

    assert settings.probes == []
    assert settings.server.port == 8000
    assert settings.auth.password_configured is False


def test_environment_password_overrides_config(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_ADMIN_PASSWORD", "from-env")
    monkeypatch.setenv("ATLAS_SESSION_SECRET", "secret-from-env")

    settings = load_settings("/path/that/does/not/exist.toml")

    assert settings.auth.admin_password == "from-env"
    assert settings.auth.session_secret == "secret-from-env"
    assert settings.auth.password_configured is True


def test_settings_report_password_hash_as_configured() -> None:
    settings = Settings(auth=AuthSettings(password_hash="hash-value"))

    assert settings.auth.password_configured is True


def test_sub2api_settings_load_from_config(tmp_path) -> None:
    config_path = tmp_path / "atlas.toml"
    config_path.write_text(
        "[sub2api]\n"
        "enabled = false\n"
        "postgres_container = \"custom-postgres\"\n"
        "snapshot_database_path = \"/tmp/custom-sub2api.sqlite3\"\n"
        "recent_window_minutes = 30\n"
        "refresh_interval_seconds = 45.0\n"
        "stale_after_seconds = 120.0\n",
    )

    settings = load_settings(config_path)

    assert settings.sub2api.enabled is False
    assert settings.sub2api.postgres_container == "custom-postgres"
    assert str(settings.sub2api.snapshot_database_path) == "/tmp/custom-sub2api.sqlite3"
    assert settings.sub2api.recent_window_minutes == 30
    assert settings.sub2api.refresh_interval_seconds == 45.0
    assert settings.sub2api.stale_after_seconds == 120.0


def test_agent_settings_load_from_config(tmp_path) -> None:
    config_path = tmp_path / "atlas.toml"
    database_path = tmp_path / "agents.sqlite3"
    config_path.write_text(
        "[agents]\n"
        f"database_path = \"{database_path}\"\n"
        "shared_token = \"config-token\"\n"
        "heartbeat_ttl_seconds = 45\n",
    )

    settings = load_settings(config_path)

    assert settings.agents.database_path == database_path
    assert settings.agents.shared_token == "config-token"
    assert settings.agents.heartbeat_ttl_seconds == 45


def test_probe_history_and_icmp_probe_load_from_config(tmp_path) -> None:
    config_path = tmp_path / "atlas.toml"
    history_path = tmp_path / "probe-history.sqlite3"
    config_path.write_text(
        "[probe_history]\n"
        f"database_path = \"{history_path}\"\n"
        "retention_hours = 72\n"
        "summary_window_hours = 24\n"
        "\n"
        "[[probes]]\n"
        "name = \"nexus\"\n"
        "type = \"icmp\"\n"
        "host = \"154.21.80.210\"\n"
        "timeout = 2.0\n",
    )

    settings = load_settings(config_path)

    assert settings.probe_history.database_path == history_path
    assert settings.probe_history.retention_hours == 72
    assert settings.probe_history.summary_window_hours == 24
    assert settings.probes[0].name == "nexus"
    assert settings.probes[0].type == "icmp"
    assert settings.probes[0].display_target == "154.21.80.210"


def test_sub2api_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_SUB2API_ENABLED", "false")
    monkeypatch.setenv("ATLAS_SUB2API_POSTGRES_CONTAINER", "env-postgres")
    monkeypatch.setenv("ATLAS_SUB2API_POSTGRES_USER", "env-user")
    monkeypatch.setenv("ATLAS_SUB2API_POSTGRES_DATABASE", "env-db")
    monkeypatch.setenv("ATLAS_SUB2API_SNAPSHOT_DATABASE_PATH", "/tmp/env-sub2api.sqlite3")
    monkeypatch.setenv("ATLAS_SUB2API_REFRESH_INTERVAL_SECONDS", "15.5")
    monkeypatch.setenv("ATLAS_SUB2API_STALE_AFTER_SECONDS", "90")

    settings = load_settings("/path/that/does/not/exist.toml")

    assert settings.sub2api.enabled is False
    assert settings.sub2api.postgres_container == "env-postgres"
    assert settings.sub2api.postgres_user == "env-user"
    assert settings.sub2api.postgres_database == "env-db"
    assert str(settings.sub2api.snapshot_database_path) == "/tmp/env-sub2api.sqlite3"
    assert settings.sub2api.refresh_interval_seconds == 15.5
    assert settings.sub2api.stale_after_seconds == 90


def test_agent_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_AGENT_DATABASE_PATH", "/tmp/env-atlas.sqlite3")
    monkeypatch.setenv("ATLAS_AGENT_SHARED_TOKEN", "env-token")
    monkeypatch.setenv("ATLAS_AGENT_HEARTBEAT_TTL_SECONDS", "30")

    settings = load_settings("/path/that/does/not/exist.toml")

    assert str(settings.agents.database_path) == "/tmp/env-atlas.sqlite3"
    assert settings.agents.shared_token == "env-token"
    assert settings.agents.heartbeat_ttl_seconds == 30


def test_probe_history_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("ATLAS_PROBE_HISTORY_DATABASE_PATH", "/tmp/env-probes.sqlite3")
    monkeypatch.setenv("ATLAS_PROBE_HISTORY_RETENTION_HOURS", "48")
    monkeypatch.setenv("ATLAS_PROBE_HISTORY_SUMMARY_WINDOW_HOURS", "12")

    settings = load_settings("/path/that/does/not/exist.toml")

    assert str(settings.probe_history.database_path) == "/tmp/env-probes.sqlite3"
    assert settings.probe_history.retention_hours == 48
    assert settings.probe_history.summary_window_hours == 12
