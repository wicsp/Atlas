# RFC 0009: Atlas Server and Console Monorepo

- **Status:** Accepted
- **Date:** 2026-07-20
- **Owner:** wicsp

## Context

Atlas server and Atlas Console were separate repositories but evolved as one personal product.
Review features repeatedly required coordinated API, UI, documentation, test, deployment, and
service-restart changes. Separate repositories added task-context loss and version drift without a
corresponding independent team, release, or reuse boundary.

Lumio remains separate because it is a broader personal pi package with capabilities unrelated to
Atlas. Future iOS and watchOS clients also retain their own Apple build and release lifecycle.

## Decision

Atlas server and Console live in one repository:

```text
apps/server/
apps/console/
docs/
```

They remain independent runtime services and dependency graphs. The repository root provides only
small orchestration commands; no monorepo framework is introduced.

The server owns protocols and durable state. The Console is an API client and may not access the
database or agent credentials. A feature may be implemented in one shared development task and one
atomic commit while still deploying either service independently.

## Migration

1. Publish the existing Atlas `main` history as the new repository baseline.
2. Import the complete Atlas Console history under `apps/console`.
3. Move backend build inputs under `apps/server` without changing its Python package name.
4. Update service units and runbooks to the new paths.
5. Validate backend tests and lint, Console lint/build/tests, secret scanning, and unit syntax.
6. Keep the existing production directories active until the merged branch is reviewed and a
   controlled cutover is complete.

## Consequences

- API and Console changes can be reviewed and committed atomically.
- A single Codex feature task can retain both implementation contexts.
- Deployments and rollbacks still identify the server and Console services separately.
- Lumio and Apple clients continue to integrate through documented Atlas protocols rather than
  source-level dependencies.
