# Atlas

Atlas is a backend-only personal control plane for system status, internal service probes, and
future agent coordination. It is designed for access through a private network or Tailscale, with
application authentication and agent/service tokens as additional protection layers.

## Backend

Install and run the FastAPI backend with uv:

```bash
uv sync
ATLAS_ADMIN_PASSWORD='change-this-password' ATLAS_SESSION_SECRET='change-this-secret' \
  uv run uvicorn atlas.main:app --reload
```

The API listens on `127.0.0.1:8000` by default when launched by uvicorn directly. For LAN or
Tailscale access, pass uvicorn host and port options:

```bash
uv run uvicorn atlas.main:app --host 0.0.0.0 --port 8000
```

## Scope

Atlas is intentionally a backend service. It does not include a bundled frontend, and it does not
replace SSH, rsync, Syncthing, MinIO/S3, Tailscale, Docker, or systemd. Its job is to coordinate,
persist, and expose state for those tools and for future agents.

## System documentation

Atlas is one part of a three-repository personal infrastructure system:

> Lumio executes. Atlas coordinates. `nix-config` provisions.

- [Personal infrastructure charter](docs/system/charter.md): mission, authority, and shared
  invariants.
- [System boundaries](docs/system/boundaries.md): concrete ownership, dependency, data, and
  knowledge rules.
- [RFC 0001: Connected Lumio Agent](docs/rfcs/0001-connected-lumio-agent.md): the first
  cross-repository implementation slice.
- [RFC 0002: Execution Hardening](docs/rfcs/0002-execution-hardening.md): fenced leases and bounded
  in-memory reliability.
- [RFC 0003: Source, Resource, and Human Review Loop](docs/rfcs/0003-source-resource-review-loop.md):
  the Bilibili-to-Obsidian content boundary.
- [RFC 0004: Resource Review Console](docs/rfcs/0004-resource-review-console.md): the narrow,
  mobile-friendly Resource inbox and human-comment request boundary.
- [Roadmap](docs/roadmap.md): ordered milestones and current stabilization work.
- [Backend control-plane design](docs/superpowers/specs/2026-07-06-atlas-backend-control-plane-design.md):
  the existing backend architecture.

Cross-repository development should follow an accepted RFC and proceed in this order: Atlas
protocol, Lumio execution, `nix-config` deployment, then one end-to-end verification.

Atlas stores Source/Resource provenance and metadata-only KnowledgeRefs. Transcript, summary, PDF,
and experiment bytes remain external ArtifactRefs; human Knowledge prose remains in the user's
Obsidian vault and is never accepted by Atlas APIs.

## Configuration

Copy the example configuration when you want persistent settings:

```bash
cp config/atlas.example.toml config/atlas.toml
```

`config/atlas.toml` is ignored by git. You can also set:

- `ATLAS_CONFIG` to point at another TOML config file.
- `ATLAS_ADMIN_PASSWORD` for a plain environment-provided admin password.
- `ATLAS_SESSION_SECRET` for the session signing secret.
- `ATLAS_AGENT_DATABASE_PATH` to override the agent registry SQLite file.
- `ATLAS_AGENT_SHARED_TOKEN` for agent API bearer-token authentication.
- `ATLAS_AGENT_HEARTBEAT_TTL_SECONDS` to control when agents are considered offline.
- `ATLAS_SUB2API_ENABLED` to enable or disable sub2api account monitoring.
- `ATLAS_SUB2API_POSTGRES_CONTAINER` to override the Postgres container name.
- `ATLAS_PROBE_HISTORY_DATABASE_PATH` to override the probe history SQLite file.

### Probe uptime monitoring

Atlas runs configured probes in the background every 30 seconds and stores probe samples in
`data/probe_history.sqlite3` by default. The API exposes the current status plus a 24-hour summary
for each probe: uptime percentage, sample count, outage count, and last downtime.

Use `icmp` probes when you only have a public IP address:

```toml
[probe_history]
database_path = "data/probe_history.sqlite3"
retention_hours = 168
summary_window_hours = 24

[[probes]]
name = "nexus"
type = "icmp"
host = "154.21.80.210"
timeout = 2.0

[[probes]]
name = "mio"
type = "icmp"
host = "8.135.45.26"
timeout = 2.0
```

The 24-hour view fills in over time. Immediately after enabling a probe, it only reflects the
samples collected since the monitor started.

### Sub2API account monitoring

Atlas can show all non-deleted accounts from a Dockerized sub2api deployment. A background collector periodically reads non-secret account metadata with:

```bash
docker exec sub2api-postgres psql -U sub2api -d sub2api
```

The API reads Atlas' local SQLite snapshot at `data/sub2api_snapshots.sqlite3`, so callers do not
synchronously query the upstream sub2api Postgres container. If collection fails, Atlas keeps the
last successful snapshot and marks it stale with the latest error.

Configure this in `[sub2api]` or disable it with `ATLAS_SUB2API_ENABLED=false`. The monitor does not read the `credentials` or `extra` account columns.

To generate a password hash for `config/atlas.toml`:

```bash
uv run atlas-password-hash
```

### Agent registry

Agents register and heartbeat with bearer-token authentication:

```bash
curl -X POST http://127.0.0.1:8000/api/agents/register \
  -H 'Authorization: Bearer replace-with-a-long-random-agent-token' \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"mac-dev","name":"Mac Dev","capabilities":["messages:send"]}'

curl -X POST http://127.0.0.1:8000/api/agents/mac-dev/heartbeat \
  -H 'Authorization: Bearer replace-with-a-long-random-agent-token'
```

Dashboard or operator clients can list registered agents through the existing session-authenticated
API:

```bash
curl http://127.0.0.1:8000/api/agents
```

### Agent messages

Agents can send direct messages to another agent and the target can poll, claim, and acknowledge
them:

```bash
curl -X POST http://127.0.0.1:8000/api/messages \
  -H 'Authorization: Bearer replace-with-a-long-random-agent-token' \
  -H 'Content-Type: application/json' \
  -d '{"from_agent_id":"mac-dev","to_agent_id":"amax-prod","kind":"prompt","body":"please inspect this"}'

curl http://127.0.0.1:8000/api/agents/amax-prod/messages/inbox \
  -H 'Authorization: Bearer replace-with-a-long-random-agent-token'

curl -X POST http://127.0.0.1:8000/api/messages/msg_example/claim \
  -H 'Authorization: Bearer replace-with-a-long-random-agent-token' \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"amax-prod"}'

curl -X POST http://127.0.0.1:8000/api/messages/msg_example/ack \
  -H 'Authorization: Bearer replace-with-a-long-random-agent-token' \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"amax-prod","result":"queued"}'
```

## Checks

```bash
uv run pytest -q
uv run ruff check .
```
