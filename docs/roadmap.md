# Personal Infrastructure Roadmap

This roadmap is organized by end-to-end capability. It is not three independent repository
backlogs.

## Current state and immediate risks

As observed on 2026-07-12:

- Atlas source passes 87 tests and Ruff, but the repository has no commits yet.
- Port 8000 is still served by an old in-memory `atlas_console.main:app` process.
- The current environment can import `atlas` but no longer imports `atlas_console`, so the old
  command will not restart successfully.
- Current Atlas source already contains an agent registry and direct-message MVP.
- Lumio contains active, uncommitted model/fast-mode changes and a Bilibili summary skill.
- `nix-config` contains broad uncommitted changes and still needs its README and personal host
  boundaries brought in line with current usage.

Do not stop the old Atlas process until the new entry point has been tested on a temporary port and
placed under a service manager.

## Milestone 0: Stable baselines

**Outcome:** Every repository has a recoverable, testable baseline before cross-system work.

### Atlas

- Verify `.gitignore` excludes configuration secrets, databases, logs, caches, and temporary data.
- Create the first commit from the currently passing source.
- Start `atlas.main:app` on a temporary port and verify its OpenAPI routes.
- Define a managed service and a rollback procedure.
- Replace the old `atlas_console` process only after validation.

### Lumio

- Complete and verify the current fast-mode consolidation.
- Verify the Bilibili skill and its dependency boundary.
- Run `npm run check`.
- Commit coherent changes before adding Atlas integration.

### nix-config

- Split or checkpoint the current broad worktree changes by concern.
- Update the README to describe the actual personal configuration and maintained hosts.
- Establish clean format, evaluation, and affected-host build checks.
- Add Atlas/Lumio deployment only after that baseline is recoverable.

**Exit criteria:** Each repository has a clean or intentionally documented worktree, passing local
checks, and a known revision suitable for rollback.

## Milestone 1: Connected Lumio agent

Implement [RFC 0001](rfcs/0001-connected-lumio-agent.md).

**Outcome:** An active Lumio-enabled pi session appears in Atlas with heartbeat, versions, and
capabilities; Atlas failure does not impair local pi use.

This is the first three-repository integration test and should remain deliberately small.

## Milestone 2: Reliable work execution

**Outcome:** Atlas can represent actionable work independently of a specific agent runtime.

Introduce only the domain behavior required by the first real pipeline:

- Project and WorkItem;
- Job and Run separation;
- append-only Events;
- ArtifactRef instead of large message bodies;
- claim lease, retry, expiry, cancellation, and idempotency;
- per-agent authentication with server-derived identity.

Do not build a generic distributed platform. SQLite and polling are sufficient until measured
requirements prove otherwise.

## Milestone 3: Bilibili vertical slice

**Outcome:** A captured Bilibili URL becomes a reviewable AI Resource with traceable source data.

```text
iPhone or Mac capture
  -> Atlas inbox
  -> Mac Lumio obtains metadata/subtitles
  -> Mac or AMAX produces a summary Resource
  -> Atlas exposes processing state and artifact references
  -> the user reviews the original and may write a human comment
```

The transcript and summary are Resources, not human knowledge. The human-comment body is never
generated or silently promoted by AI.

## Milestone 4: Academic source workflow

**Outcome:** Papers can be discovered and triaged without duplicating Zotero's authority.

- DOI/arXiv/Zotero identifiers;
- source-version and page/section anchors;
- PDF extraction and AI summary Resources;
- Zotero links rather than a second bibliography database;
- human comments linked to original evidence;
- explicit human confirmation for semantic relations.

## Milestone 5: Experiment integration

**Outcome:** AMAX experiments are observable and can be referenced from human research comments.

- stable experiment Run IDs;
- Git revision, environment, configuration hash, and dataset identity;
- logs, metrics, figures, and checkpoints as ArtifactRefs;
- GPU and process status integrated with Atlas health views;
- human observations stored outside machine-generated run summaries.

## Milestone 6: Atlas Console

**Outcome:** A separate, mobile-friendly client presents the stable control-plane model.

Initial views:

- overview and health;
- capture inbox;
- projects and actionable work;
- jobs and runs;
- agents and nodes;
- resources awaiting review;
- experiments and notifications.

The console is a client of Atlas. It does not own the backend schema, directly access Atlas SQLite,
or become the only way to operate the system.

## Delivery discipline

For each milestone:

1. Start with a user-visible outcome and acceptance criteria.
2. Write an RFC only when a cross-repository contract changes.
3. Implement Atlas protocol first, Lumio execution second, and Nix deployment third.
4. Test each repository independently.
5. Run one end-to-end smoke test.
6. Record deployed revisions and protocol versions in Atlas.
7. Finish the vertical slice before starting another infrastructure feature.

Avoid parallel expansion of the three repositories. Parallel work is useful only when the protocol
is already accepted and each repository task has a non-overlapping boundary.

