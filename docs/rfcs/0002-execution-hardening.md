# RFC 0002: Execution Hardening

- **Status:** Implemented
- **Decision date:** 2026-07-13
- **Owners:** Atlas, Lumio, and nix-config
- **Protocol:** `atlas-agent-v2`
- **Gate:** Required before expanding the Bilibili slice or starting the academic-source workflow

## Summary

Atlas and Lumio demonstrate the complete control loop: a Lumio session registers and heartbeats,
polls Atlas for work, claims a leased run, executes a handler, and reports a result. This RFC makes
that path a trustworthy execution boundary without turning Lumio into a durable message broker.

The reliability policy is **safety without durable delivery**:

- transient Atlas failures are tolerated while the current execution lease remains valid;
- every claim has an immutable execution-attempt identity and an in-memory claim token;
- retries of one terminal report are idempotent and bounded by the lease;
- once the lease expires, the old attempt loses all publication rights and its late report is
  abandoned;
- useful files already written by the handler remain local artifacts and are not deleted merely
  because Atlas did not record completion;
- Lumio does not persist an outbox, claim credentials, or work reports for restart replay.

This deliberately accepts that Atlas can show a failed or retried Run while a useful local artifact
still exists. Atlas is the control plane; it is not the authority for experiment outputs or acquired
content bytes.

## User outcome

After this RFC:

- an authenticated worker cannot impersonate another agent;
- concurrent pollers cannot both own the same execution attempt;
- an expired or superseded attempt cannot overwrite current state;
- ambiguous terminal responses can be retried safely while the lease is valid;
- a long Atlas outage produces visible lease expiry, retry, or failure rather than a hidden
  recovery queue;
- unsupported jobs fail visibly instead of succeeding silently;
- captured URLs and other user input never become shell syntax;
- transcripts and generated resources are stored outside Atlas SQLite and referenced as artifacts;
- machine-generated Resources remain separate from human-authored KnowledgeComments.

## Current implementation position

As of the decision date:

- scoped agent credentials and server-derived identity are implemented;
- atomic claim, terminal idempotency, transactional Events, shell-free execution, typed handler
  results, and external transcript artifacts are implemented;
- Atlas has an `ExecutionAttempt` record and returns an `attempt_id` plus `claim_token` on claim;
- an experimental public Reconcile API was implemented while durable outbox delivery was being
  considered;
- Lumio has bounded terminal-report retries, but still needs lease-deadline-aware handling of
  transient heartbeat and report failures.

The Reconcile API is not part of the accepted contract. It is experimental overdesign and must be
removed before this RFC is marked Implemented. Its internal transactional and compare-and-set ideas
remain applicable to ordinary claim, heartbeat, complete, and fail transitions.

## Safety invariants

The implementation must preserve all of these invariants:

1. **Server-derived identity:** route handlers derive the acting agent from authenticated server
   state. Query parameters and JSON bodies never establish identity.
2. **Fenced ownership:** only the authenticated owner of the current execution attempt, presenting
   its claim token, can heartbeat, complete, or fail the Run. A successor attempt permanently
   fences every older attempt.
3. **Claim before execution:** a pending Run cannot transition directly to completed or failed.
4. **Atomic claim:** claim, attempt creation, token-digest storage, and the claimed Event commit in
   one transaction. Concurrent pollers produce at most one winner.
5. **Strict lease guard:** heartbeat, complete, and fail require an unexpired lease according to
   Atlas time. Expiry immediately removes publication authority, even before a cleanup sweep runs.
6. **Narrow idempotent reporting:** replaying the same terminal operation with the same
   `Idempotency-Key` and payload returns the accepted state without duplicate Events or
   ArtifactRefs. A conflicting terminal intent or payload returns a stable `409`.
7. **Visible failure:** unsupported jobs, lost leases, rejected reports, and exhausted retries never
   appear as successful work.
8. **No shell interpretation:** user-controlled values are passed as argument vectors, not shell
   command strings.
9. **Bounded control-plane payloads:** large content is stored in external files or object storage
   and represented in Atlas by ArtifactRef.
10. **Transactional history:** a state transition and its Event commit together or both fail.
11. **Knowledge separation:** automated output may create a Source or Resource, but never writes
   human KnowledgeComment prose.
12. **Bounded recovery:** retry state and the raw claim token exist only in the active Lumio process.
   A Lumio restart does not replay an earlier attempt.

## Implementation disposition

| Mechanism | Decision | Why |
| --- | --- | --- |
| Scoped agent credential and `AgentPrincipal` | Keep | Prevents client-asserted identity and cross-agent impersonation. |
| `ExecutionAttempt`, `attempt_id`, and per-claim `claim_token` | Keep, simplified | Provides cheap execution identity and fencing. The token is memory-only in Lumio; Atlas stores only its digest. |
| Atomic claim and transactional Event | Keep | Prevents duplicate ownership and false history under concurrency. |
| Lease heartbeat and guards on heartbeat/complete/fail | Keep | Bounds ownership and prevents stale workers from publishing. |
| Same-key terminal idempotency | Keep, narrow | Handles an accepted request whose response was lost without creating a general deduplication platform. |
| Retry after transient network or 5xx failures | Keep, bounded | Covers ordinary short interruptions while the lease is still valid. |
| External ArtifactRefs and handler-owned files | Keep | Preserves useful bytes without putting large data in SQLite. |
| Public Reconcile API accepting an expired attempt | Remove | There is no outbox consumer, it contradicts final lease expiry, and it expands the state machine and attack surface. |
| Durable Lumio outbox and persisted claim token | Do not implement | The operational value does not justify filesystem transactions, secret persistence, replay, retention, and conflict handling. |
| Startup scanning and automatic report replay | Do not implement | A restarted Lumio process has no authority to revive an expired attempt. |
| Superseded-result retention and state merging | Do not implement | Local artifacts may remain, but Atlas does not merge or promote a stale result. |
| Generic `EXPIRED` Run state | Do not add now | Attempt expiry can return a retryable Run to pending or fail an exhausted Run; add a new Run state only for a measured user need. |

## Scope

### Included

- scoped agent or session credentials and an authenticated `AgentPrincipal`;
- protocol migration to `atlas-agent-v2`;
- immutable execution-attempt identity and per-claim fencing token;
- strict, atomic Run transitions and transactional Events;
- idempotent terminal reporting within a live lease;
- lease-deadline-aware, in-memory retry for transient Atlas failures;
- explicit capability routing and unsupported-job behavior;
- asynchronous, shell-free subprocess execution in Lumio;
- typed handler results with bounded output and ArtifactRefs;
- external transcript and generated-resource storage;
- focused fake-server, concurrency, lease-loss, cancellation, and redaction tests;
- minimal secret and environment provisioning changes in nix-config;
- removal of the experimental Reconcile API.

### Excluded

- durable delivery after lease expiry;
- persisted outbox bundles, persisted claim credentials, restart replay, and result reconciliation;
- WebSocket or push scheduling;
- multi-user authorization or organization-level RBAC;
- arbitrary remote prompt execution;
- a generic plugin marketplace for workers;
- Atlas Console development;
- Zotero, arXiv, PDF, embedding, or RAG workflows;
- automatic creation of human-authored knowledge;
- replacing SQLite or polling without measured evidence.

## Authentication and identity

The shared `atlas-agent-v1` token may remain temporarily for registration during migration, but it
must not authorize work execution after this RFC is deployed.

The `atlas-agent-v2` flow is:

1. nix-config provisions a bootstrap credential for a known node or worker principal.
2. Lumio registers a session using that credential and a non-secret session nonce.
3. Atlas creates the canonical agent ID, binds it to the authenticated principal, and returns a
   scoped session credential.
4. Atlas stores only a secure digest of the scoped credential.
5. Subsequent work operations authenticate the scoped credential.
6. A FastAPI dependency resolves an `AgentPrincipal`; services use its canonical agent ID rather
   than trusting an ID in a URL or JSON body.
7. A rejected scoped credential causes Lumio to re-register with bounded backoff. This credential
   lifecycle is distinct from recovering an expired execution attempt.

Interactive pi sessions may continue using identities shaped like:

```text
<node>.lumio.pi.<server-approved-session-id>
```

A persistent worker uses a separate principal and lifecycle. Secrets never appear in URLs, process
arguments, logs, Events, metadata, or Git.

## Execution-attempt and claim-token contract

Every successful claim creates an immutable execution attempt containing at least:

```text
attempt_id
run_id
attempt_number
agent_id
claim_token_digest
status
lease_expires_at
created_at
finished_at
result_digest             optional audit field
```

Atlas returns the raw claim token once with the claim response and stores only its digest. Lumio
keeps the raw token in memory for the active attempt. It must not write the token to an outbox,
manifest, log, Event, artifact, or environment file. Releasing the active attempt releases the
token; a restarted process does not recover it.

`attempt_number` is not an authorization credential. A successor claim creates a new attempt and
token, marks or treats the older attempt as superseded, and permanently prevents the older attempt
from heartbeat or terminal publication.

## Run state and lease contract

The existing Run lifecycle remains:

```text
pending -> claimed -> completed
                   -> failed
        -> cancelled
claimed -> pending      when its attempt lease expires and attempts remain
        -> failed       when its final allowed attempt expires
        -> cancelled
```

Lease expiry applies to an attempt even when the Run is later retried. Atlas may create a successor
attempt only through a new atomic claim. A late result from the older attempt is discarded rather
than reconciled.

Required behavior:

- `claim-next` selects a compatible Run, changes it to claimed, creates the attempt and claim token,
  and appends the Event in one transaction;
- required capabilities are a subset of the authenticated agent capabilities;
- heartbeat, complete, and fail check Run status, agent owner, attempt identity, claim-token digest,
  and lease deadline;
- normal complete and fail reject an expired lease with a stable `409 lease_expired` response;
- cancellation prevents later completion and is visible to a running Lumio handler;
- attempt exhaustion produces a stable terminal failure reason;
- the accepted terminal request, Event, idempotency record, output, ArtifactRefs, and attempt state
  commit transactionally;
- a complete/expiry or claim/claim race is resolved by Atlas-side conditional updates or equivalent
  serialized transactions, never by an unconditional ORM read-then-write transition.

Retryable, inexpensive, and idempotent work may use `max_attempts > 1`. Expensive,
non-idempotent, or externally managed experiment jobs should use `max_attempts=1` so a lost lease
cannot automatically launch a duplicate experiment. Retrying such work is an explicit new Run.

## Reliability budget and expiration

A configured lease TTL is not an outage guarantee. In particular, a 120-second TTL does not mean
that the system can always survive a full 120-second Atlas outage. At the moment an interruption
starts, part of that lease may already have elapsed.

The usable recovery budget is approximately:

```text
current lease_expires_at
  - current time
  - request timeout
  - clock-skew and scheduling-jitter margin
```

With periodic heartbeats, a conservative planning estimate after the last successful heartbeat is:

```text
lease TTL - heartbeat interval - request timeout - safety margin
```

If a full 120-second interruption must be tolerated, the TTL must be greater than 120 seconds plus
those margins; for example, a measured 180-to-240-second TTL with a 30-second heartbeat may be a
reasonable starting point. This is configuration guidance, not a new protocol requirement.

Lumio behavior is:

1. A successful claim establishes the current `lease_expires_at` deadline.
2. A successful heartbeat replaces that deadline with the returned value.
3. A network error, timeout, or 5xx is ambiguous. Lumio keeps the handler running and retries in
   memory with bounded backoff while the deadline has safe time remaining.
4. A `401`, `403`, or lease/state `409` is definitive. Lumio signals lease loss immediately.
5. When the local deadline plus safety margin is reached, Lumio signals lease loss, stops all
   terminal-report retries, forgets the attempt credential, and never calls a reconciliation path.
6. An Atlas-controlled child process should honor the abort signal. A separately managed experiment
   process is outside the lease lifecycle; its own repository and output directory remain
   authoritative even when Atlas loses observability.
7. A locally completed file may remain even when the report is abandoned. Lumio records at most a
   concise runtime diagnostic; it does not persist a replayable control-plane bundle.

## Terminal reporting

Success and failure use the normal complete and fail endpoints only. Lumio generates one stable
`Idempotency-Key` for that terminal operation and reuses the same key and identical payload after an
ambiguous response. Heartbeats continue while a terminal report is being retried.

Retries stop when Atlas accepts the report, Atlas returns a definitive client or state error, the
lease deadline is reached, or Lumio shuts down. There is no Reconcile fallback. If a request may
have been accepted but its response is lost and the lease then expires, Lumio reports the local
outcome as unknown or abandoned; Atlas remains authoritative for whether it committed the request.

## Lumio execution contract

Lumio maintains a registry of explicitly supported jobs and advertises those names as capabilities.
It must never intentionally claim work outside that set.

Handlers return a typed result:

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

- a defensive post-claim check reports `unsupported_job` while the lease is live;
- enqueue requests include `capabilities_required` explicitly;
- subprocesses use `execFile` or `spawn` with argument arrays and `shell: false`;
- subprocess execution is asynchronous so the event loop can maintain the lease;
- cancellation, shutdown, definitive lease loss, and lease expiry signal the handler to stop;
- generated artifacts are written atomically where appropriate before their ArtifactRefs are
  reported;
- ambiguous terminal failures retry only in memory with the same idempotency key and live lease;
- a single ambiguous heartbeat failure does not immediately abort a handler;
- no code creates an outbox, persists a claim token, scans old reports at startup, or calls
  Reconcile.

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

Artifact storage uses a configured data root with private default permissions, atomic writes,
content hashes, and stable URIs. Handler-specific provenance manifests are allowed, but they are
content records rather than Lumio outbox entries and are never used to replay an expired report.
Atlas owns metadata and lifecycle state; it does not become the authority for the bytes.

## Repository responsibilities

### Atlas

- resolve authenticated agent identity and scoped credentials;
- create and fence execution attempts with memory-only client claim tokens;
- implement atomic claims and strict live-lease terminal transitions;
- commit Events and ArtifactRefs transactionally with transitions;
- provide narrow idempotency and stable error codes;
- enforce output and event-body size limits;
- remove the experimental Reconcile route, request model, service/repository path, and tests;
- test concurrency, impersonation, lease expiry, duplicate terminal requests, and Atlas restart.

### Lumio

- implement v2 registration and scoped credential refresh;
- keep attempt credentials only in active-process memory;
- handle transient heartbeat failures until the remaining lease budget is exhausted;
- retry ambiguous terminal requests with one idempotency key and no disk persistence;
- stop reporting immediately after definitive lease loss or local deadline expiry;
- keep the poller capability-safe and handlers result-aware;
- use asynchronous, shell-free subprocess execution;
- store transcript and generated Resource bytes outside Run output;
- add fake-Atlas and fake-subprocess tests;
- keep the repository check command deterministic and offline after dependencies are installed.

### nix-config

- provision the bootstrap credential through agenix or the existing secret store;
- provide artifact-root and endpoint paths without committing secrets;
- keep interactive Lumio sessions distinct from persistent workers;
- configure lease and heartbeat values with an explicit measured safety margin;
- build or evaluate affected hosts before switching;
- remove the v1 shared execution credential only after v2 acceptance passes.

## Verification

### Required automated cases

- concurrent agents race for one Run and exactly one attempt becomes owner;
- one authenticated agent cannot act as another agent by changing a URL or JSON field;
- a wrong token, old attempt, pending Run, cancelled Run, or expired lease cannot complete or fail;
- heartbeat extends only the current, unexpired attempt;
- one transient heartbeat network failure within the lease does not abort the handler, and a later
  success updates its deadline;
- a definitive lease/state `409` aborts the Atlas-controlled handler and prevents publication;
- a repeated identical completion with the same key is safe, creates no duplicate Event or
  ArtifactRef, and a conflicting report returns `409`;
- a lost terminal response is retried with the same idempotency key only while the lease is live;
- retries stop at lease expiry and no outbox directory, claim-token file, or startup replay appears;
- a Lumio restart does not replay an earlier terminal report;
- unknown and capability-mismatched jobs are never reported successful;
- a shell-metacharacter URL is delivered literally to the child process;
- cancellation and shutdown terminate Atlas-controlled children and clean sensitive temp files;
- transcript bytes are absent from `runs.output_json` and present behind a valid ArtifactRef;
- local artifacts remain readable after an abandoned report;
- secrets are absent from Git, process arguments, logs, Events, metadata, and artifacts;
- AI output cannot populate a human KnowledgeComment body.

### Repository checks

Atlas must pass its complete pytest and Ruff suites. Lumio must have a self-contained check command
that runs type checks plus focused tests without contacting npm or AMAX. nix-config must pass
formatting, evaluation, and the affected-host build without switching first.

### End-to-end acceptance

1. Start two Lumio sessions with different scoped credentials.
2. Enqueue one capability-constrained Bilibili Run and confirm exactly one session owns it.
3. Introduce a short Atlas interruption that ends with safe time remaining in the current lease.
4. Confirm Lumio does not abort on the first ambiguous heartbeat failure, renews the lease after
   Atlas returns, and reaches exactly one terminal state.
5. Repeat with Atlas unavailable beyond the remaining lease budget.
6. Confirm Lumio abandons the old attempt, makes no late complete/fail/Reconcile request, writes no
   outbox, and does not replay the report after restart.
7. Confirm any transcript or other artifact already written remains private, readable, hashed, and
   separate from Atlas SQLite.
8. Allow Atlas to retry an inexpensive Run and confirm the successor attempt fences the old token.
9. Run an expensive case with `max_attempts=1` and confirm lease loss does not launch a duplicate.

## Rollout order

1. Record this reliability decision and freeze new workflow and console features.
2. Remove the experimental Atlas Reconcile API and its tests.
3. Add Atlas tests that require lease checks on normal complete and fail, then enforce them.
4. Add Lumio fake-server tests for transient heartbeat failure, definitive lease loss, expiry, and
   same-key terminal retry.
5. Implement lease-deadline-aware in-memory retry and explicit abandonment in Lumio.
6. Verify handler artifact writes and remove any outbox or persisted-attempt placeholders.
7. Update only the necessary nix-config lease, heartbeat, endpoint, secret, and artifact settings.
8. Run repository checks plus the short-interruption and expiry acceptance cases.
9. Deploy Atlas first, Lumio second, and nix-config last with rollback revisions recorded.
10. Mark this RFC Implemented before expanding Milestone 3 or starting Milestone 4.

## Stop-the-line rule

Until the accepted checks in this RFC pass:

- do not add paper, Zotero, arXiv, embedding, or RAG execution;
- do not add arbitrary command or prompt jobs;
- do not build Atlas Console on top of the unstable work contract;
- do not treat the current execution path as a trusted remote-execution system.
