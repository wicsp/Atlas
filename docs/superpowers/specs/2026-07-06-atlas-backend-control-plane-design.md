# Atlas Backend Control Plane Design

## Goal

Atlas becomes a backend-only personal control plane. It coordinates agents, messages, tasks,
events, artifacts, configuration snapshots, and service/system status without replacing SSH,
rsync, Syncthing, MinIO, Tailscale, Docker, or systemd.

## Technical Stack

- Python 3.11+
- FastAPI for HTTP APIs
- Pydantic v2 for request, response, and domain validation
- SQLAlchemy 2.x for persistence
- Alembic for schema migrations
- SQLite first, Postgres-compatible repository boundaries later
- pytest and pytest-asyncio for TDD
- uv for dependency and lockfile management
- ruff for linting

## Backend Boundaries

Atlas is the durable coordination layer. Its core model is protocol-independent:

- Agent: a process or service that can register, heartbeat, publish state, and claim work.
- Message: communication between agents or broadcast topics.
- Task: a work item with explicit claim, lease, completion, failure, cancellation, and expiry.
- Event: append-only fact history.
- ArtifactRef: metadata and location for external files or outputs.
- ConfigSnapshot: versioned configuration content and target scope.

HTTP is the first adapter. WebSocket, SSE, MCP, CLI, and webhook adapters can be added later
without changing the domain model.

## Deployment Shape

The first implementation is a single Atlas server, normally deployed on the most stable private
network node. It remains future-friendly by using global IDs, persisted state, node identifiers,
agent identifiers, leases, idempotency fields, and repository/service boundaries.

Atlas does not execute remote commands by default. Agents actively poll or subscribe, claim work,
and report results.

## Project Shape

The Python package is renamed from `atlas_console` to `atlas`. Frontend assets and Vite/React
tooling are removed. The backend keeps existing system, network, probe, auth, and sub2api behavior
while gaining a clearer structure for control-plane domains.

## Testing Discipline

All behavior changes use TDD:

1. Write a focused failing test.
2. Run it and confirm the expected failure.
3. Implement the smallest passing code.
4. Run focused tests and then the relevant suite.
5. Refactor only while tests stay green.

