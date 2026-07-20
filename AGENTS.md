# AGENTS.md

Atlas is a personal system with two co-located applications and independently deployed services.

## Ownership

- `apps/server/` owns the API, domain state, persistence, authentication, and work coordination.
- `apps/console/` is an operator client. It may use only documented Atlas APIs and the operator
  session; it must not acquire agent credentials or direct database access.
- `docs/rfcs/` is authoritative for changes that cross Atlas, Console, Lumio, or future clients.
- `deploy/` directories describe runtime units, but declarative host provisioning remains outside
  this repository.

## Development rules

1. Keep server and console dependencies scoped to their application directories.
2. Do not introduce a monorepo framework unless the root commands can no longer remain trivial.
3. Change the server contract before or together with dependent console behavior.
4. Add backend and console tests for cross-cutting behavior; run `just test` before publishing.
5. Never commit runtime configuration, databases, logs, artifacts, credentials, or personal
   knowledge content.
6. Keep tool and API output bounded so agent tasks do not flood model context.
7. Preserve the Source / Resource / Knowledge boundary and require explicit human confirmation
   before promoting machine output into human-owned knowledge.
