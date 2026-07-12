# Personal Infrastructure Roadmap

This roadmap is organized by end-to-end capability. It is not three independent repository
backlogs.

## Current state and immediate risks

As observed after the AMAX Atlas Milestone 0 cutover on 2026-07-12:

- Atlas source has baseline commit `4b79af1` (`chore: establish atlas baseline`) and passes 87
  tests and Ruff.
- `atlas.service` now runs `atlas.main:app` on port 8000 as an active, enabled systemd user service;
  it passed isolated current-source and rollback canaries plus a production restart-persistence
  check.
- A detached `4b79af1` rollback worktree and a SQLite-consistent pre-cutover backup are the recovery
  anchors for Milestone 0.
- The old `atlas_console` process has been retired and is not a valid rollback target.
- Current Atlas source already contains an agent registry and direct-message MVP.
- Lumio contains active, uncommitted model/fast-mode changes and a Bilibili summary skill.
- `nix-config` contains broad uncommitted changes and still needs its README and personal host
  boundaries brought in line with current usage.

The bootstrap service is operational; long-term Atlas service ownership still needs to move into
`nix-config`.

## Milestone 0: Stable baselines

**Outcome:** Every repository has a recoverable, testable baseline before cross-system work.

### Atlas

**Status:** The Atlas operational portion of Milestone 0 completed on 2026-07-12.

- `.gitignore` excludes configuration secrets, databases, logs, caches, and temporary data.
- Baseline commit `4b79af1` and its detached rollback worktree are verified recovery anchors.
- Current and rollback `atlas.main:app` canaries passed on isolated localhost ports.
- The production systemd user unit, runtime token, persistent agent database, and restart behavior
  are verified on port 8000.
- The old `atlas_console` process is retired and is not used for rollback.
- Move the verified bootstrap service declaration into `nix-config` for long-term ownership.

### Lumio

- Complete and verify the current fast-mode consolidation.
- Verify the Bilibili skill and its dependency boundary.
- Run `npm run check`.
- Commit coherent changes before adding Atlas integration.

### nix-config

- Split or checkpoint the current broad worktree changes by concern.
- Update the README to describe the actual personal configuration and maintained hosts.
- Establish clean format, evaluation, and affected-host build checks.
- Add Atlas/Lumio deployment only after the Atlas canary, environment, and rollback path are
  recoverable.

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

