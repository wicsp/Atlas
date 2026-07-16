# RFC 0004: Resource Review Console

- **Status:** Accepted
- **Decision date:** 2026-07-16
- **Owners:** Atlas, Atlas Console, and Lumio
- **Protocol:** `atlas-agent-v3` (unchanged)
- **Milestone:** 3.2

## Summary

RFC 0004 adds the smallest useful mobile and desktop operating surface for the review loop created
by RFC 0003. It is a Resource Review Console, not the general Atlas Console planned for Milestone 6.

```text
browser on iPhone or Mac
  -> authenticated Atlas read/review API
  -> Source-grouped Resource inbox
  -> dismiss or restore metadata directly in Atlas
  -> request a human comment Run
  -> connected Mac Lumio creates the empty note locally
  -> Atlas records the KnowledgeRef and reviewed state
  -> Console observes the terminal Run and refreshes
```

Atlas remains the authority for Source, Resource, review, Run, and KnowledgeRef metadata. Lumio
remains the only component that mutates the Mac-local Vortex vault. The Console stores no domain
state, receives no shared control credential, writes no Knowledge prose, and does not read Atlas'
SQLite database directly.

## User outcome

After this RFC, the user can open one Tailscale-only page from an iPhone or Mac and:

- find every pending summary Resource without copying an ID;
- see Resources grouped by their original Source, with all generated versions ordered newest first;
- distinguish the chronological latest version without treating it as the automatically preferred
  or true version;
- open the original Source or its generated Vortex Resource Card;
- request an empty human comment and see whether the Mac executor is pending, working, completed,
  or failed;
- dismiss an irrelevant Resource and later restore it;
- receive action feedback next to the affected Resource instead of inferring success from a later
  synchronization command.

## Why this is Milestone 3.2

The present command interface proves the lifecycle but exposes implementation IDs and hides the
inbox. Those are workflow problems, not evidence that Atlas needs a broad dashboard. A narrow
review client closes the RFC 0003 loop before paper ingestion adds more Sources.

The following remain Milestone 6 concerns: general Projects and WorkItems, agent administration,
GPU and node dashboards, experiment views, notification routing, and a generic task launcher.

## Invariants

1. **Knowledge remains human-owned.** The Console cannot send prose, summaries, titles, tags, or
   conclusions to a KnowledgeComment. It may request only an empty comment template.
2. **Atlas remains authoritative.** The Console uses public Atlas APIs and never reads or writes
   SQLite directly.
3. **Local writes stay local.** Only a connected Lumio process on the Mac may create or project
   files in Vortex.
4. **The browser has no machine credential.** It authenticates with the existing HttpOnly operator
   session cookie. The shared control token and scoped agent credentials never enter browser code,
   HTML, storage, or logs.
5. **Actions are narrow.** The comment endpoint accepts a Resource ID and can enqueue only the
   fixed `vortex-comment-v1` job. It is not a browser-accessible generic Run enqueue API.
6. **Duplicate execution is harmless.** An active comment request is reused when found; duplicate
   Runs are still safe because note creation, KnowledgeRef registration, review transition, and
   projection are independently idempotent.
7. **Versions are not collapsed into truth.** Source grouping preserves every Resource version.
   “Latest” means only greatest `created_at` with a stable ID tie-breaker.
8. **Bytes remain external.** This milestone displays bounded metadata and deep links. It does not
   copy Mac-local summary or transcript bytes into Atlas merely to render them on AMAX or iPhone.
9. **Projection remains disposable.** Dismiss and restore change Atlas review metadata; Lumio
   reconciliation converges generated cards without touching `Knowledge/**`.

## Architecture and deployment

The Console is a separate responsive web client hosted on AMAX and reachable only through
Tailscale. A same-origin reverse proxy routes browser `/api/*` requests to the existing Atlas
service and all other requests to the Console application. This avoids cross-origin credential
handling and keeps Atlas' operator session cookie HttpOnly.

```text
iPhone / Mac browser
        |
        | Tailscale HTTP
        v
AMAX reverse proxy
  /api/*  -----------------> Atlas :8000
  /*      -----------------> Atlas Console
                                  |
                                  | metadata only
                                  v
                            no local artifact access

Mac Lumio <--------- Atlas claim/lease API
    |
    +-----------> Vortex file mutation queue
```

The Console may construct an `obsidian://open` URI for the stable generated card path. On a device
without that vault or application, the link may not resolve; this is not an Atlas failure.

## Review read model

The first implementation composes existing bounded APIs in the client:

```text
GET /api/sources?limit=500
GET /api/resources?kind=summary&limit=500
GET /api/knowledge-refs?limit=500
GET /api/runs/{run_id}
```

No denormalized Console table is added. The client groups Resources by `source_id`, sorts each
group by descending `created_at` and then `resource_id`, and derives whether a KnowledgeRef cites a
Resource. The filters are `pending`, `reviewed`, `dismissed`, and `all`; the default is `pending`.

The personal 500-record bound is explicit for this slice. Pagination or a server-side inbox read
model requires measured need and does not block M3.2.

## Action contract

### Dismiss and restore

The Console uses the existing endpoint:

```text
PATCH /api/resources/{resource_id}/review
```

- dismiss sends `{"review_status":"dismissed"}`;
- restore sends `{"review_status":"pending"}`;
- Atlas continues to reject dismissal of a Resource cited by a KnowledgeRef;
- the Console renders the returned Resource state or the conflict next to the action;
- Lumio startup or manual reconciliation later removes or rebuilds the generated card.

The Console does not claim that card projection has completed merely because Atlas accepted the
metadata transition.

### Request human comment

RFC 0004 introduces one operator endpoint:

```text
POST /api/review-actions/comment
Content-Type: application/json

{"resource_id":"res_..."}
```

It is protected by the existing control-auth dependency, which accepts the operator session cookie
without exposing the shared control token. Atlas validates that the Resource exists and is a
summary, upserts the fixed `resource-review` Project, and enqueues:

```json
{
  "project_id": "resource-review",
  "job_name": "vortex-comment-v1",
  "capabilities_required": ["vortex-comment-v1"],
  "input": {"resource_id": "res_..."},
  "max_attempts": 3,
  "metadata": {"requested_via": "atlas-console"}
}
```

If a matching pending or claimed Run exists, Atlas returns it with `reused: true`. If the Resource
already has a KnowledgeRef, Atlas returns a conflict rather than creating another comment identity.
This active-Run reuse is a usability guard, not an exactly-once guarantee; end-to-end idempotence is
the correctness boundary.

The response contains the Run and `reused`. The Console polls only that Run while it is pending or
claimed, then refreshes Sources, Resources, and KnowledgeRefs after a terminal result.

## Lumio execution contract

A connected Mac Lumio registers capability `vortex-comment-v1`. Its handler:

1. validates the bounded `resource_id` input;
2. fetches the Resource bundle from Atlas;
3. creates the empty Vortex KnowledgeComment template through Pi's file mutation queue;
4. never replaces an existing note at the stable comment path;
5. upserts the metadata-only KnowledgeRef;
6. marks the Resource `reviewed`;
7. refreshes the generated Resource Card;
8. reports only bounded identifiers, URIs, and action flags in Run output.

The existing `/atlas:comment <resource_id>` command calls the same workflow. A retry after any
partial failure converges on the same note and KnowledgeRef. No note body is read into Run output or
sent to Atlas.

Adding a capability does not change the v3 wire schema. Older agents cannot claim the job because
capability routing already fences them, so `atlas-agent-v3` remains the protocol version.

## User-interface behavior

The page is deliberately one workbench rather than a navigation shell:

- a compact header reports connection state and counts;
- Source cards show original identity once and contain their Resource versions;
- status filters change discoverability without deleting records;
- every action has disabled, in-progress, success, and error states local to its Resource;
- a pending comment request exposes its Run status and can be refreshed without resubmission;
- Resource and Run IDs are visible for diagnosis but are never required as manual input;
- an expired login returns to an explicit login form rather than silently appearing empty.

The first release does not render summary bodies because the current ArtifactRefs are Mac-local
`file://` URIs. The Source and Obsidian links make that limitation explicit.

## Scope

### Included

- a separate responsive Atlas Console project;
- operator session login/logout;
- pending/reviewed/dismissed/all filters;
- Source-grouped summary Resource versions;
- original Source and generated Vortex card deep links;
- dismiss, restore, and request-comment actions with local feedback;
- a narrow Atlas comment-request endpoint and active-Run reuse;
- `vortex-comment-v1` execution in Lumio using the existing safe comment workflow;
- Tailscale-only AMAX deployment and focused Atlas, Lumio, Console, and end-to-end tests.

### Excluded

- full Artifact body replication or browser rendering;
- direct browser writes to Vortex, SSH, SQLite, or local files;
- AI-authored Knowledge prose or automatic best-summary selection;
- bulk review, deletion, Resource garbage collection, or irreversible purge;
- daily paper/news generation, Zotero integration, RAG, embeddings, or semantic graph inference;
- generic Project/WorkItem management, arbitrary Run enqueue, agent control, GPU monitoring,
  experiment dashboards, or public Internet hosting;
- automatic dismissal or automatic comment creation.

## Acceptance criteria

RFC 0004 is complete only when all of the following pass:

1. An unauthenticated browser sees a login form and protected review/action APIs reject it.
2. The browser bundle and storage contain neither the Atlas control token nor an agent credential.
3. Pending summary Resources are discoverable without entering an ID and are grouped by Source.
4. Multiple Resource versions remain visible and deterministically ordered; latest is labeled as
   chronological only.
5. Dismiss and restore return clear inline state; Knowledge-referenced dismissal still conflicts.
6. One comment click creates or reuses only a fixed `vortex-comment-v1` Run and the Console shows
   its pending, claimed, completed, or failed state.
7. Repeating the request or retrying a partially completed handler neither overwrites human prose
   nor creates a second KnowledgeRef identity.
8. A successful handler creates an empty note, registers its metadata-only KnowledgeRef, marks the
   Resource reviewed, and refreshes the generated card.
9. Run output and Atlas SQLite contain no comment body, transcript, summary body, credential, or
   cookie.
10. Atlas tests and Ruff, Lumio checks, Console tests/lint/build, and a deployed read-only browser
    smoke test pass.
11. Production validation does not create, dismiss, restore, or modify human-owned content merely
    for testing; action semantics are verified against isolated data unless the user chooses a real
    Resource.

## Rollback

The Atlas endpoint and Lumio capability are additive. Rollback stops the Console service and
returns Atlas/Lumio to their prior revisions. Pending `vortex-comment-v1` Runs are harmless if no
capable agent remains; they may be cancelled through the existing work API. Any already-created
KnowledgeComment remains human-owned and is never removed by rollback. No database column or table
migration is required by this RFC.

## Verification record

To be completed after implementation and deployment:

- Atlas revision and service version;
- Atlas Console revision and deployed Tailscale URL;
- Lumio revision, package version, and registered capability;
- repository check results;
- isolated retry/non-overwrite verification;
- production read-only browser smoke result.
