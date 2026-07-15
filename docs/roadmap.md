# Personal Infrastructure Roadmap

This roadmap is organized by end-to-end capability. It is not three independent repository
backlogs.

## Current state and immediate risks

As observed during RFC 0003 implementation on 2026-07-15:

- `atlas.service` runs `atlas.main:app` on port 8000 and production contains live Lumio heartbeats
  and completed work Runs.
- A detached `4b79af1` rollback worktree and a SQLite-consistent pre-cutover backup remain the
  Milestone 0 recovery anchors; the old `atlas_console` process is retired.
- RFC 0001 and RFC 0002 are implemented. Atlas/Lumio use fenced attempts, scoped credentials,
  strict leases, narrow terminal idempotency, bounded in-memory retry, shell-free execution, and
  external ArtifactRefs. The rejected Reconcile API and durable outbox are absent.
- RFC 0003 defines Source, Resource, and metadata-only KnowledgeRef records. A v3 Run completion
  publishes Source enrichment, ArtifactRefs, Resources, terminal state, and Event atomically.
- Lumio produces content-addressed Bilibili transcript and AI-summary artifacts, then reconciles
  generated Resource Cards in Vortex. Human Knowledge comments remain separate and manual.
- Successful Pi startup runs Resource Card reconciliation. The same operation is available through
  `/atlas:reconcile`; unchanged cards are not rewritten, and dismissed cards are absent.
- nix-config provisions Atlas endpoint, node identity, artifact root, Obsidian vault path, and the
  agenix-managed control credential.

The immediate operational risk is byte locality: Atlas can reference a Mac-local `file://` artifact
that AMAX or a future mobile Console cannot read directly. This is accepted for the first personal
slice; measured cross-node review demand should drive a later artifact-store RFC. v3 Lumio must not
be deployed before v3 Atlas acknowledges the protocol.

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

**Status:** Implemented.

**Outcome:** An active Lumio-enabled pi session appears in Atlas with heartbeat, versions, and
capabilities; Atlas failure does not impair local pi use.

See [RFC 0001](rfcs/0001-connected-lumio-agent.md) for the accepted contract and revisions.

## Milestone 2: Reliable work execution

**Status:** Implemented for the current Run-execution slice.

**Outcome:** Atlas can represent actionable work independently of a specific agent runtime.

Introduce only the domain behavior required by the first real pipeline:

- Project (durable WorkItem remains deferred until a real actionable-work UI needs it);
- Job and Run separation;
- append-only Events;
- ArtifactRef instead of large message bodies;
- claim lease, retry, expiry, cancellation, and idempotency;
- per-agent authentication with server-derived identity.

Do not build a generic distributed platform. SQLite and polling are sufficient until measured
requirements prove otherwise.

## Milestone 2.5: Execution Hardening

**Status:** Implemented on 2026-07-13.

Implement [RFC 0002](rfcs/0002-execution-hardening.md).

**Outcome:** The existing Atlas/Lumio execution loop becomes a trustworthy boundary before more
sources, workers, or user interfaces depend on it.

This is a stop-the-line gate, not a durable-delivery platform. Its policy is safety without durable
delivery: retry transient failures only while the current lease remains valid, then abandon the old
attempt while preserving any handler-owned local artifact.

It requires:

- per-agent or per-session credentials with server-derived identity;
- atomic claim plus a lightweight `ExecutionAttempt`, `attempt_id`, and memory-only claim token;
- strict lease guards on heartbeat, complete, and fail;
- narrow same-key terminal idempotency and transactional Events;
- lease-deadline-aware, in-memory retry for transient Atlas failures;
- irreversible attempt expiry and successor-attempt fencing;
- explicit capability routing and visible unsupported-job failure;
- asynchronous shell-free subprocess execution;
- bounded run output with transcripts and generated Resources stored as ArtifactRefs;
- fake-server, concurrency, transient-outage, expiry, cancellation, and redaction tests;
- deterministic green checks in Atlas, Lumio, and nix-config.

M2.5 explicitly does not include a durable Lumio outbox, persisted claim token, startup replay,
superseded-result merge, or a public API that accepts reports after lease expiry. The experimental
Reconcile endpoint is removed; ordinary claim and terminal transitions still use transactional
guards internally.

**Exit criteria:** Every accepted RFC 0002 check passes, deployed revisions and protocol versions
are recorded, and the Bilibili slice:

- produces one owner in a two-agent race;
- survives a transient Atlas interruption that ends within the remaining lease budget;
- abandons an attempt cleanly when that budget expires, without a late report, outbox, or restart
  replay;
- retries an ambiguous terminal response with the same key and without duplicate state;
- preserves any already-written local artifact without putting transcript bytes or secrets in
  SQLite.

## Milestone 3: Bilibili vertical slice

**Status:** Implemented on 2026-07-15.

**Outcome:** A captured Bilibili URL becomes a reviewable AI Resource with traceable source data.

```text
iPhone or Mac capture API
  -> Atlas Source + Run
  -> Mac Lumio obtains metadata/subtitles and uses the active Pi model
  -> Atlas atomically publishes transcript and summary Resources
  -> Lumio rebuilds a generated Obsidian Resource Card
  -> the user reviews the original and may create a human Knowledge Comment
```

The transcript and summary are Resources, not human knowledge. The human-comment body is never
generated or silently promoted by AI.

See [RFC 0003](rfcs/0003-source-resource-review-loop.md) for the accepted domain, protocol,
Obsidian boundary, deployed revisions, and real Source-to-Resource-to-card verification record.

### Milestone 3.1: Review projection lifecycle

**Status:** Implemented on 2026-07-15.

- `/atlas:comment` registers a metadata-only KnowledgeRef, marks the Resource reviewed, and updates
  its generated card immediately.
- `/atlas:dismiss` hides an unreferenced Resource and removes only its rebuildable card;
  Knowledge-referenced Resources are protected with a conflict response.
- `/atlas:restore` returns a dismissed Resource to pending and rebuilds its card.
- Startup and manual reconciliation converge every summary card to Atlas review metadata without
  modifying human-authored files under `Knowledge/**`.

## Milestone 4: Academic source workflow

**Status:** Ready for a focused RFC; not started.

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
