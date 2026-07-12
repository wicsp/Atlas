# RFC 0002: Execution Hardening

- **Status:** Proposed
- **Owners:** Atlas, Lumio, and nix-config
- **Protocol:** `atlas-agent-v2`
- **Gate:** Required before expanding the Bilibili slice or starting the academic-source workflow

## Summary

Atlas and Lumio now demonstrate the complete control loop: a Lumio session registers and
heartbeats, polls Atlas for work, claims leased runs, executes a Bilibili handler, and reports a
result. Production data confirms that the loop works.

The current implementation is a functional prototype, not yet a trustworthy execution boundary.
It still uses one shared bearer token with client-asserted agent IDs, permits terminal transitions
without a strict claimed owner, can treat an unsupported job as successful, passes user-controlled
arguments through a shell command string, and stores transcript content in run output.

This RFC hardens that existing slice. It does not add a generic distributed system or a new user
feature. The purpose is to make the current execution path safe, recoverable, testable, and
consistent with [System Boundaries](../system/boundaries.md).

## User outcome

After this RFC:

- an authenticated worker cannot impersonate another agent;
- a run is executed at most by its current lease owner;
- duplicate requests and temporary Atlas failures do not create false completion states;
- unsupported jobs fail visibly instead of succeeding silently;
- captured URLs and other user input never become shell syntax;
- transcripts and generated resources are stored outside Atlas SQLite and referenced as artifacts;
- Atlas remains a control plane, while Lumio remains the execution and acquisition layer;
- machine-generated Resources remain separate from human-authored KnowledgeComments.

## Current evidence and gaps

Observed on 2026-07-12:

- RFC 0001 is implemented and live Lumio sessions heartbeat successfully.
- Atlas has Project, Run, Event, ArtifactRef, lease, retry, cancellation, and polling primitives.
- Lumio has work polling and a working `bilibili-summary` handler.
- Production contains completed smoke runs and completed Bilibili runs.
- Atlas has 106 passing tests, but Ruff still reports one broad-exception assertion.
- Lumio has no focused fake-Atlas tests, and `npm run check` is not self-contained.
- The Bilibili handler currently stores transcript text directly in `runs.output_json`.

These facts prove utility, but they do not satisfy the execution safety invariants below.

## Safety invariants

The implementation must preserve all of these invariants:

1. **Server-derived identity:** route handlers derive the acting agent from authenticated server
   state. Query parameters and JSON bodies never establish identity.
2. **Strict ownership:** only the active lease owner can heartbeat, complete, or fail a run.
3. **Claim before execution:** a pending run cannot transition directly to completed or failed.
4. **Atomic claim:** concurrent pollers cannot both obtain ownership of the same run.
5. **Idempotent reporting:** retrying an accepted terminal report returns the accepted state;
   conflicting reports fail explicitly.
6. **Visible failure:** unsupported jobs, lost leases, rejected results, and exhausted retries never
   appear as successful work.
7. **No shell interpretation:** user-controlled values are passed as argument vectors, not shell
   command strings.
8. **Bounded control-plane payloads:** large content is stored in external files or object storage
   and represented in Atlas by ArtifactRef.
9. **Transactional history:** the state transition and its Event are committed together or both
   fail.
10. **Knowledge separation:** automated output may create a Source or Resource, but never writes
    human KnowledgeComment prose.

## Scope

### Included

- per-agent or per-session credentials;
- an authenticated `AgentPrincipal` resolved by Atlas;
- protocol migration from `atlas-agent-v1` to `atlas-agent-v2`;
- strict and atomic run state transitions;
- idempotent claim and terminal reporting behavior;
- explicit capability routing and unsupported-job behavior;
- asynchronous, shell-free subprocess execution in Lumio;
- lease-loss, cancellation, retry, and Atlas-restart recovery;
- typed handler results containing bounded output, ArtifactRefs, or a structured error;
- transcript and generated-resource artifact storage;
- deterministic checks and focused tests in both repositories;
- minimal secret and environment provisioning changes in nix-config.

### Excluded

- WebSocket or push scheduling;
- multi-user authorization or organization-level RBAC;
- arbitrary remote prompt execution;
- a generic plugin marketplace for workers;
- Atlas Console development;
- Zotero, arXiv, PDF, embedding, or RAG workflows;
- automatic creation of human-authored knowledge;
- replacing SQLite or polling without measured evidence.

## Authentication and identity

The shared `atlas-agent-v1` token may remain temporarily for registration and heartbeat during
migration, but it must not authorize work execution after this RFC is deployed.

The `atlas-agent-v2` flow is:

1. nix-config provisions a bootstrap credential for a known node or worker principal.
2. Lumio registers an interactive session using that credential and a non-secret session nonce.
3. Atlas creates the canonical agent ID, binds it to the authenticated principal, and returns a
   scoped session credential.
4. Atlas stores only a secure digest of the scoped credential.
5. Subsequent heartbeat, inbox, claim, run-heartbeat, complete, and fail requests authenticate the
   scoped credential.
6. A FastAPI dependency resolves an `AgentPrincipal`; services receive its canonical agent ID
   instead of accepting an agent ID from query or body data.
7. A rejected or expired scoped credential causes Lumio to re-register with bounded backoff.

Interactive pi sessions may continue using identities shaped like:

```text
<node>.lumio.pi.<server-approved-session-id>
```

A persistent worker uses a separate principal and lifecycle. Secrets never appear in URLs, process
arguments, logs, events, metadata, or Git.

## Run state and lease contract

The allowed lifecycle is:

```text
pending -> claimed -> completed
                   -> failed
        -> cancelled
claimed -> pending      when a lease expires and attempts remain
        -> failed       when the final allowed attempt expires
        -> cancelled
```

Required behavior:

- `claim-next` selects and claims in one database transaction.
- Required capabilities must be a subset of the authenticated agent capabilities.
- `complete` and `fail` require `status=claimed`, an unexpired lease, and the authenticated owner.
- A run heartbeat extends only the caller's current lease.
- Cancellation prevents later completion and is visible to a running Lumio handler.
- Every state transition appends its Event in the same transaction.
- Attempt exhaustion produces a stable terminal failure reason.
- Claim and terminal operations accept an idempotency key or equivalent request identity.
- Repeating the same accepted operation returns the existing state; a conflicting operation
  returns `409` with a stable machine-readable error code.

## Lumio execution contract

Lumio maintains a registry of explicitly supported jobs. It advertises those names as
capabilities and must never claim work outside that set.

Handlers return a typed result instead of mutating `RunRecord` with private fields:

```ts
type HandlerResult =
  | {
      status: "success";
      output: Record<string, JsonValue>;
      artifacts: ArtifactRefCreate[];
    }
  | {
      status: "failure";
      code: string;
      message: string;
      retryable: boolean;
    };
```

Additional requirements:

- unknown job names are not claimed; a defensive post-claim check fails them as
  `unsupported_job`;
- enqueue requests include `capabilities_required` explicitly;
- subprocesses use `execFile` or `spawn` with argument arrays and `shell: false`;
- subprocess execution is asynchronous so the event loop can maintain the run lease;
- timeout, cancellation, and shutdown terminate the child process and clean sensitive temp files;
- Lumio reports local success only after Atlas accepts the terminal transition;
- ambiguous network failures retry the same idempotent request instead of assuming success;
- lease loss stops publication of results and produces one concise diagnostic.

## Artifact and Resource boundary

Run output remains small and structured. It may contain identifiers, hashes, provenance, counts,
status, and ArtifactRefs, but not complete transcripts, PDFs, videos, model responses, or logs.

For the Bilibili slice:

```text
Source metadata
  -> transcript file + ArtifactRef
  -> AI summary Resource file + ArtifactRef
  -> bounded Run output with provenance and hashes
  -> optional empty human-comment template
```

Artifact storage must use a configured data root with private default permissions, atomic writes,
content hashes, stable URIs, and cleanup rules. Atlas owns metadata and lifecycle state; it does not
become the authority for the content bytes.

## Repository responsibilities

### Atlas

- define `AgentPrincipal` and scoped credential persistence;
- remove client-controlled identity from work service calls;
- implement atomic claims and strict terminal transitions;
- commit Events transactionally with transitions;
- add stable error codes and HTTP mappings;
- enforce output and event-body size limits;
- expose idempotent work APIs and migration-compatible protocol metadata;
- test concurrency, impersonation, lease expiry, retries, and Atlas restart.

### Lumio

- implement v2 registration and scoped credential refresh;
- replace shell-string subprocess execution;
- make the poller capability-safe and result-aware;
- introduce typed handler results and ArtifactRefs;
- move transcript bytes out of run output;
- add fake-Atlas and fake-subprocess tests;
- make the repository check command deterministic and offline after dependencies are installed.

### nix-config

- provision the bootstrap credential through agenix or the existing secret store;
- provide artifact-root and endpoint paths without committing secrets;
- keep interactive Lumio sessions distinct from persistent workers;
- build/evaluate affected hosts before switching;
- remove the v1 shared execution credential only after v2 acceptance passes.

## Verification

### Required automated cases

- two agents race for one run and exactly one becomes owner;
- one authenticated agent cannot act as another agent by changing a URL or JSON field;
- complete/fail on a pending, expired, cancelled, or foreign run is rejected;
- repeated identical completion is safe and a conflicting completion returns `409`;
- unknown and capability-mismatched jobs are never reported successful;
- a shell-metacharacter URL is delivered literally to the child process;
- a long-running subprocess continues to renew its lease;
- cancellation and shutdown terminate the child and remove cookie files;
- Atlas restart during execution recovers through re-registration and idempotent reporting;
- transcript bytes are absent from `runs.output_json` and present behind a valid ArtifactRef;
- secrets are absent from Git, process arguments, logs, Events, and metadata;
- AI output cannot populate a human KnowledgeComment body.

### Repository checks

Atlas must pass its complete pytest and Ruff suites. Lumio must have a self-contained check command
that runs type checks plus focused tests without contacting npm or AMAX. nix-config must pass
formatting, evaluation, and the affected-host build without switching first.

### End-to-end acceptance

1. Start two Lumio sessions with different scoped credentials.
2. Enqueue one capability-constrained Bilibili run.
3. Confirm exactly one session owns and heartbeats the lease.
4. Restart Atlas while the handler is active.
5. Confirm the same run reaches one terminal state with one accepted output.
6. Confirm the transcript and summary are private external artifacts with hashes and provenance.
7. Stop the session and confirm credentials, child processes, and sensitive temp files are cleaned.

## Rollout order

1. Freeze new workflow and console features.
2. Add failing Atlas security and state-machine tests.
3. Implement Atlas identity, atomic transition, Event, and idempotency changes.
4. Add Lumio fake-server and subprocess tests.
5. Implement the v2 Lumio client, poller, and typed handlers.
6. Move the Bilibili transcript to artifact storage.
7. Update nix-config secrets and paths without switching.
8. Run repository checks and the two-agent end-to-end acceptance test.
9. Deploy Atlas first, Lumio second, and nix-config last with rollback revisions recorded.
10. Mark this RFC Implemented before expanding Milestone 3 or starting Milestone 4.

## Stop-the-line rule

Until every acceptance check in this RFC passes:

- do not add paper, Zotero, arXiv, embedding, or RAG execution;
- do not add arbitrary command or prompt jobs;
- do not build Atlas Console on top of the unstable work contract;
- do not treat the current M2/M3 prototype as a trusted remote-execution system.
