# Atlas Milestone 0 Operations

This runbook covers the Milestone 0 bootstrap flow for `atlas.main:app`. The checked-in
`apps/server/deploy/systemd/user/atlas.service` file is the production service bound to
`0.0.0.0:8000`.
Before a cutover, install it without starting it. The canary is a separate transient systemd user
unit on a dynamically chosen localhost port.

The repository baseline already exists at `4b79af1` (`chore: establish atlas baseline`). Keep a
detached rollback worktree at that revision so cutover always has a known-good fallback.

## Completion record

The AMAX Milestone 0 cutover completed on 2026-07-12:

- baseline `4b79af1`, the current-source canary, and the detached rollback canary all passed;
- the unmanaged `atlas_console.main:app` process was retired and is not a rollback target;
- `atlas.service` passed production health, OpenAPI, bearer-auth, and restart-persistence checks;
- the user service is active and enabled with `UMask=0077`, and the agent database is mode `0600`;
- the pre-cutover backup is
  `/home/wicsp/.local/share/atlas/backups/20260712T094347Z`.

Long-term declarative ownership of the service still belongs in `nix-config`; this unit is the
verified bootstrap deployment.

## Artifacts

- Production unit: `apps/server/deploy/systemd/user/atlas.service`
- Production config: `apps/server/config/atlas.toml`
- User env file: `%h/.config/atlas/atlas.env`
- Detached rollback worktree rooted at `4b79af1`

`apps/server/config/atlas.toml` already carries the auth values. The user env file only needs
`ATLAS_AGENT_SHARED_TOKEN`.

Do not commit runtime config, databases, logs, or secrets.

## Preflight

Run this from the repository root:

```bash
just test-server
```

## Canary

Launch a transient systemd user canary on a random localhost port. Run the launch and checks in the
same shell so `tmpdir` and `port` stay in scope. The canary reuses the real production config,
overrides the SQLite paths into fresh `/tmp` files, and disables sub2api:

```bash
tmpdir=$(mktemp -d /tmp/atlas-m0-XXXXXX)
port=$(apps/server/.venv/bin/python - <<'PY'
import socket
s = socket.socket()
s.bind(("127.0.0.1", 0))
print(s.getsockname()[1])
s.close()
PY
)
systemd-run --user --unit=atlas-m0-canary.service --collect \
  -p WorkingDirectory=/home/wicsp/projects/Atlas/apps/server \
  -p Environment=ATLAS_CONFIG=/home/wicsp/projects/Atlas/apps/server/config/atlas.toml \
  -p Environment=ATLAS_AGENT_DATABASE_PATH=$tmpdir/agents.sqlite3 \
  -p Environment=ATLAS_PROBE_HISTORY_DATABASE_PATH=$tmpdir/probe-history.sqlite3 \
  -p Environment=ATLAS_SUB2API_SNAPSHOT_DATABASE_PATH=$tmpdir/sub2api-snapshots.sqlite3 \
  -p Environment=ATLAS_SUB2API_ENABLED=false \
  -p EnvironmentFile=%h/.config/atlas/atlas.env \
  /home/wicsp/projects/Atlas/apps/server/.venv/bin/python -m uvicorn atlas.main:app --host 127.0.0.1 --port "$port"
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS "http://127.0.0.1:${port}/api/health" >/tmp/atlas-health.json; then
    break
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:${port}/api/health" >/tmp/atlas-health.json
curl -fsS "http://127.0.0.1:${port}/openapi.json" >/tmp/atlas-openapi.json

status=$(curl -o /dev/null -sS -w '%{http_code}' \
  -X POST "http://127.0.0.1:${port}/api/agents/register" \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"atlas-m0-missing-token","name":"Atlas M0"}')
test "$status" = 401

set -a
. ~/.config/atlas/atlas.env
set +a
printf -v atlas_auth_header 'Authorization: %s %s' Bearer "$ATLAS_AGENT_SHARED_TOKEN"

curl -fsS -X POST "http://127.0.0.1:${port}/api/agents/register" \
  -H "$atlas_auth_header" \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"atlas-m0-canary","name":"Atlas M0 Canary","capabilities":["health:read"],"metadata":{"canary":true}}' \
  >/tmp/atlas-canary-register.json
curl -fsS -X POST "http://127.0.0.1:${port}/api/agents/register" \
  -H "$atlas_auth_header" \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":"atlas-m0-peer","name":"Atlas M0 Peer"}' \
  >/tmp/atlas-canary-peer-register.json
curl -fsS -X POST "http://127.0.0.1:${port}/api/agents/atlas-m0-canary/heartbeat" \
  -H "$atlas_auth_header" \
  >/tmp/atlas-canary-heartbeat.json
curl -fsS -X POST "http://127.0.0.1:${port}/api/messages" \
  -H "$atlas_auth_header" \
  -H 'Content-Type: application/json' \
  -d '{"from_agent_id":"atlas-m0-canary","to_agent_id":"atlas-m0-peer","kind":"prompt","body":"atlas m0 inbox check","metadata":{"source":"milestone-0"}}' \
  >/tmp/atlas-canary-message.json
curl -fsS "http://127.0.0.1:${port}/api/agents/atlas-m0-peer/messages/inbox" \
  -H "$atlas_auth_header" \
  >/tmp/atlas-canary-inbox.json
unset ATLAS_AGENT_SHARED_TOKEN
unset atlas_auth_header
```

Stop and collect only the canary after verification:

```bash
systemctl --user stop atlas-m0-canary.service
journalctl --user -u atlas-m0-canary.service -n 200 --no-pager
```

## Install

Install the production unit without starting it:

```bash
mkdir -p ~/.config/systemd/user ~/.config/atlas
cp apps/server/deploy/systemd/user/atlas.service ~/.config/systemd/user/atlas.service
systemctl --user daemon-reload
```

Create `~/.config/atlas/atlas.env` with only the shared token:

```bash
install -m 700 -d ~/.config/atlas
tmp_env=$(mktemp ~/.config/atlas/.atlas.env.XXXXXX)
trap 'rm -f "$tmp_env"' EXIT
printf 'ATLAS_AGENT_SHARED_TOKEN=%s\n' "$(openssl rand -hex 32)" > "$tmp_env"
chmod 600 "$tmp_env"
mv "$tmp_env" ~/.config/atlas/atlas.env
trap - EXIT
```

## Cutover

1. Confirm the canary passed health, OpenAPI, missing-token 401, bearer registration, heartbeat,
   message send, and inbox checks.
2. Confirm the detached `4b79af1` rollback worktree is still available and matches the verified
   `atlas.main:app` entry point.
3. Confirm `apps/server/deploy/systemd/user/atlas.service` is installed but still not started.
4. Create a SQLite-consistent, permission-restricted backup of persistent data and runtime config.
5. Gracefully stop the unmanaged process, then confirm that port 8000 is free. Do not use a forced
   kill if graceful shutdown fails.
6. Start `atlas.service` and verify post-cutover health on port 8000.
7. Verify a bearer heartbeat survives one managed service restart, then enable the unit:

```bash
systemctl --user start atlas.service
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:8000/openapi.json >/tmp/atlas-openapi.json
systemctl --user status atlas.service
journalctl --user -u atlas.service -n 100 --no-pager
systemctl --user enable atlas.service
```

## Rollback

If post-cutover checks fail, stop the production unit and run the baseline source from a transient
user unit. Keep the production repository as the working directory and keep its ignored config so
relative persistent-data paths do not move into the rollback worktree:

```bash
ROLLBACK_WT=/home/wicsp/.local/share/atlas/releases/4b79af1
systemctl --user stop atlas.service
systemd-run --user --unit=atlas-m0-rollback-live.service --collect \
  -p WorkingDirectory=/home/wicsp/projects/Atlas/apps/server \
  -p Environment=PYTHONPATH=$ROLLBACK_WT/src \
  -p Environment=ATLAS_CONFIG=/home/wicsp/projects/Atlas/apps/server/config/atlas.toml \
  -p EnvironmentFile=%h/.config/atlas/atlas.env \
  /home/wicsp/projects/Atlas/apps/server/.venv/bin/python -m uvicorn atlas.main:app --host 0.0.0.0 --port 8000
curl -fsS http://127.0.0.1:8000/api/health
```

Do not restart `atlas_console`; it is not a valid rollback target. Do not delete or overwrite the
SQLite files while diagnosing.

## Unit Validation

`systemd-analyze --user verify apps/server/deploy/systemd/user/atlas.service` can catch unit-file
syntax issues.
Inside the Codex sandbox it may still print user-manager bus/socket permission errors, so treat it
as a syntax check only. Final validation requires installing the unit in the real user manager and
checking `systemctl --user status atlas.service` during cutover.
