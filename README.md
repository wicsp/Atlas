# Atlas

Atlas is a personal control plane for sources, generated resources, human review, and work routed
to connected agents. The repository keeps the backend protocol and its review console together so
cross-cutting changes can be implemented and validated atomically.

## Repository layout

```text
apps/
├── server/   # FastAPI backend, persistence, domain services, and systemd unit
└── console/  # Private mobile-friendly review console and reverse proxy units
docs/         # System boundaries, RFCs, operations, and roadmap
```

The applications remain separate runtime services:

- `atlas.service` serves the API on port 8000.
- `atlas-console.service` serves the web app on loopback port 8788.
- `atlas-console-proxy.service` exposes the console and proxies `/api/*` over Tailscale.

## Development

Rebuild locked environments and run all checks from the repository root:

```bash
just sync
just ci
```

Or work on one application directly:

```bash
cd apps/server
uv sync
uv run pytest -q
uv run ruff check .

cd ../console
npm ci
npm run lint
npm test
```

See [the server guide](apps/server/README.md), [the console guide](apps/console/README.md), and the
[operations runbook](docs/operations/atlas-milestone-0.md) for configuration and deployment.

On the configured amax host, `just deploy` runs the complete check/build sequence, installs the
three checked-in user units, restarts them, and verifies API and Console health. It is intentionally
an explicit command and is never part of CI.

## System boundary

Atlas coordinates and persists server-owned state and generated Resource bytes. AtlasRunner
executes node-local work; Lumio provides interactive commands and optional Obsidian projections.
Runner-local artifact files are caches, while uploaded `atlas://` Artifacts are authoritative.
Human-authored knowledge remains under explicit user control; an accepted RFC must define any
change that crosses repository boundaries.

Runtime configuration, databases, logs, artifacts, credentials, and Obsidian content must never be
committed.

Atlas execution is runtime-neutral. Node Runners register available executors such as Pi, Codex,
or scripts; versioned Workflows define business behavior and placement requirements. See
[RFC 0010](docs/rfcs/0010-runtime-neutral-workflow-execution.md). The legacy Agent capability
surface remains temporarily available for deployed clients.
