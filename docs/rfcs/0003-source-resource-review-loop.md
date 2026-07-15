# RFC 0003: Source, Resource, and Human Review Loop

- **Status:** Implemented
- **Decision date:** 2026-07-15
- **Implemented:** 2026-07-15
- **Owners:** Atlas, Lumio, and nix-config
- **Protocol:** `atlas-agent-v3`
- **Milestone:** 3.0

## Summary

RFC 0003 turns the existing Bilibili execution prototype into the first complete content pipeline:

```text
capture URL
  -> Source in Atlas
  -> leased Lumio Run
  -> transcript and AI summary ArtifactRefs
  -> transactionally published Resources
  -> rebuildable Resource Card in Obsidian
  -> optional human-authored Knowledge Comment
  -> metadata-only KnowledgeRef in Atlas
```

The boundary is deliberately asymmetric. Machines may acquire, extract, summarize, classify, and
project Resources. They may create an empty comment template and register its location. They must
never generate, rewrite, or silently promote prose in the human Knowledge layer.

Atlas stores identity, state, provenance, and references. Artifact bytes remain outside SQLite.
Obsidian is the review and writing surface for this milestone, not the authoritative scheduler or
artifact store.

## User outcome

After this RFC:

- capturing the same Bilibili video twice resolves to one stable Source;
- a successful `bilibili-summary-v3` Run publishes a transcript Resource and an AI-summary Resource; the versioned capability prevents legacy v2 agents from claiming the new publication contract;
- each Resource points to an external ArtifactRef and records its generator and content hash;
- Run completion, ArtifactRefs, Source updates, and Resource publication commit atomically;
- a generated Resource Card appears under `Resources/Cards` and is safe to rebuild;
- the user can create a blank Knowledge Comment under `Knowledge/Comments` and write it manually;
- Atlas records only that note's URI and evidence relations, never the note body;
- an Atlas outage may lose an expired attempt report, as accepted by RFC 0002, while already-written
  local artifacts remain intact.

## Invariants

1. **Original identity is separate from derived content.** A Source identifies external material;
   it does not contain transcript or summary bytes.
2. **Bytes stay external.** Transcript and summary bodies are files referenced by ArtifactRefs.
3. **Every Resource has provenance.** It names one Source, one ArtifactRef, the producing Run, a
   content hash, and a typed generator descriptor.
4. **Publication is atomic.** A Run cannot become completed while any declared Source update,
   ArtifactRef, or Resource is invalid or missing.
5. **Machine content remains visibly machine content.** AI output is stored and projected only as a
   Resource with `generated: true` and generator metadata.
6. **Knowledge prose is human-owned.** Atlas' KnowledgeRef API has no content/body field and rejects
   unknown fields. Lumio creates structure only; it never supplies comment prose.
7. **Obsidian projections are disposable.** Resource Cards may be overwritten from their canonical
   Resource artifact. Human comments are never overwritten by projection code.
8. **Review state is metadata, not truth.** `pending`, `reviewed`, and `dismissed` describe the
   user's review action. They do not promote a Resource into Knowledge.
9. **No hidden RAG authority.** Embeddings and indexes are excluded; any later index must be
   rebuildable from Source, Resource, and KnowledgeRef records.
10. **Bounded payloads.** Atlas receives metadata and references only; model prompts, transcripts,
    summaries, credentials, and cookies never enter Run output or SQLite.

## Domain model

### Source

`Source` is a stable identity for external original material.

Required fields:

```text
source_id                 Atlas-generated stable ID
source_key                canonical deduplication key, e.g. bilibili:BV...
kind                      video | paper | webpage | dataset | code | other
canonical_uri
title                     optional until acquisition completes
external_ids              bounded metadata, e.g. {bvid: ...}
metadata                  bounded source metadata only
created_at
updated_at
```

`POST /api/sources` is an idempotent upsert by `source_key`. It may enrich metadata after capture,
but it cannot replace one Source kind with another.

### ArtifactRef

ArtifactRef remains the RFC 0002 external-byte pointer. RFC 0003 does not add blob upload to Atlas.
The Mac artifact root is the initial storage backend; the URI contract permits a later object store
without changing Resource identity.

### Resource

`Resource` is derived assistance, never human knowledge.

Required fields:

```text
resource_id               producer-supplied content-derived ID
source_id
produced_by_run_id
artifact_id
kind                      transcript | summary | extraction | comparison
title
content_hash              sha256:...
generator                 typed deterministic or AI generator descriptor
metadata                  bounded processing metadata
review_status             pending | reviewed | dismissed
created_at
updated_at
```

The producer declares Resources in `RunComplete` using an `artifact_name`. Atlas resolves that name
to the ArtifactRef inserted by the same completion transaction. A missing Source, missing artifact,
duplicate artifact name, or conflicting Resource identity rejects the entire completion.

Resource identity is based on Source, Resource kind, and content hash. Re-running unchanged content
therefore does not create another logical Resource. A changed summary creates a new Resource and
does not mutate the previous generated text.

### KnowledgeRef

`KnowledgeRef` is a metadata pointer to a human-owned Obsidian note:

```text
knowledge_ref_id
note_id                   stable vault-relative note identity
uri                       Obsidian URI or other resolvable note URI
source_ids                evidence Sources
resource_ids              consulted Resources
revision_of               optional earlier KnowledgeRef
created_at
updated_at
```

There is intentionally no title, body, summary, abstract, conclusion, tags generated by AI, or
free-form prose field. Atlas derives Source relations for referenced Resources and rejects unknown
request fields. The Markdown note remains wholly owned by the user and the vault's own history.

## Protocol changes

`RunComplete` adds:

```json
{
  "source_updates": [],
  "artifacts": [],
  "resources": []
}
```

These lists are validated and committed with the terminal state and Event. Because an older Atlas
would silently ignore unknown Pydantic fields, the registration metadata protocol becomes
`atlas-agent-v3`; v3 Lumio must be deployed only after v3 Atlas.

v3 also removes the misleading composite identity from Atlas' canonical key. Lumio registers the
separate fields `node_id`, `agent_kind`, `executor`, `runtime`, and Pi `instance_id`; Atlas derives
and returns an opaque `agt_<digest>` identifier. `lumio` is the executor and `pi` is its runtime,
not two nested agents. Lumio replaces its provisional registration ID with the returned Atlas ID
before heartbeat or work polling.

Control-plane endpoints introduced by this RFC:

```text
POST  /api/sources
GET   /api/sources
GET   /api/sources/{source_id}
GET   /api/resources
GET   /api/resources/{resource_id}
PATCH /api/resources/{resource_id}/review
POST  /api/knowledge-refs
GET   /api/knowledge-refs
```

The personal operator session or the provisioned control credential may use these endpoints. Work
publication itself remains possible only through a valid, live scoped execution attempt.

## Bilibili implementation

1. `/atlas:enqueue` extracts the BV ID and upserts `bilibili:<bvid>` before enqueueing.
2. The Run input carries `source_id`, canonical URL, and capture URL.
3. Lumio obtains metadata and subtitle text without shell interpretation.
4. The transcript is stored content-addressed and declared as a deterministic Resource.
5. Lumio summarizes through the active Pi model. Long transcripts are chunked and synthesized with
   bounded input; model/provider/prompt version are recorded.
6. The Markdown summary is stored content-addressed and declared as an AI Resource.
7. Atlas atomically accepts the terminal report and publishes both Resources.
8. Lumio writes or refreshes only the generated summary card under `Resources/Cards/<resource_id>.md`.

If no model/auth or usable transcript is available, the handler reports visible failure. It does
not mark a metadata-only capture as a successful summary.

## Obsidian boundary

The new vault starts without migrating the old Vortex structure:

```text
Vortex Next/
  Knowledge/
    Inbox/
    Comments/
    Maps/
    Attachments/
  Resources/
    Cards/
    Digests/
      Daily Papers/
      News/
  System/
    Templates/
    Policy.md
```

- `Resources/**` may be generated or replaced by Lumio.
- `Knowledge/**` is user-authored. Lumio may create a new empty template only when explicitly asked.
- The old Vortex remains a backup/reference source and is not bulk imported.
- Zotero remains authoritative for bibliography and PDFs; this RFC adds no second paper database.

## Scope

### Included

- Source upsert and lookup;
- Resource publication through transactional Run completion;
- Source enrichment in the same completion;
- Resource listing and explicit review status;
- metadata-only KnowledgeRef registration;
- Bilibili transcript plus active-Pi-model summary Resources;
- content-addressed summary artifacts;
- generated Obsidian Resource Cards and blank human-comment templates;
- a clean Vortex Next skeleton and nix-config environment provisioning;
- focused unit, API, projection, and real end-to-end smoke tests;
- removal of Lumio's copied generic Todo extension, while retaining Plan mode's ephemeral steps;
- opaque Atlas agent identity derived from separate executor/runtime/session metadata.

Atlas' legacy `/api/todos` endpoints are marked deprecated but are not deleted in this RFC because
production still contains user data. No new Lumio feature consumes them. A later WorkItem migration
must preserve those records before removing the API.

### Excluded

- Atlas Console;
- general WorkItem/Todo migration;
- daily paper/news schedulers;
- Zotero, arXiv, DOI, or PDF ingestion;
- embeddings, vector databases, RAG, graph inference, or automatic backlinks;
- automatic human comments, conclusions, claims, or relation confirmation;
- durable result delivery after lease expiry;
- artifact upload, replication, garbage collection, or cross-node byte availability;
- iPhone UI beyond the authenticated capture API contract.

## Acceptance criteria

RFC 0003 is complete only when all of the following pass:

1. Same `source_key` upserts to one Source and can be enriched without duplication.
2. A live attempt completes with two ArtifactRefs and two Resources in one transaction.
3. Missing Source/artifact or conflicting Resource rejects completion and leaves the Run claimed
   with no partial ArtifactRef or Resource rows.
4. Terminal idempotency creates no duplicate Resources or Events.
5. KnowledgeRef requests containing `body`, `content`, or other unknown fields return validation
   failure, and responses contain no prose field.
6. Bilibili shell-free and credential-redaction tests from RFC 0002 remain green.
7. Summary output records model/provider/prompt version and never appears in Run output.
8. A Resource Card can be rebuilt from the summary ArtifactRef and contains an explicit generated
   warning plus Source/Resource IDs.
9. Creating a comment produces an empty Knowledge note and a metadata-only Atlas KnowledgeRef;
   projection never overwrites that note.
10. Atlas `pytest` and Ruff, Lumio checks, and affected nix evaluation all pass.
11. A real capture reaches Source -> completed Run -> Resource -> Obsidian card, and deployed
    revisions are recorded below.

## Deployment and rollback

Deployment order is Atlas, Lumio, nix-config, then Vortex Next bootstrap. Before deployment, make a
SQLite-consistent database backup. New tables are additive, so rollback to v2 code leaves them
unused. A v3 Lumio must not run against v2 Atlas because Resource declarations could otherwise be
discarded.

## Verification record

- Atlas revision: `5f4cd41` (`atlas.service` restarted at this revision; health reports `0.2.0`).
- Lumio revision: `5ee799a` (Atlas recorded `atlas-agent-v3`, Lumio `0.2.0`, Pi `0.80.6`,
  and this Git revision for agent `agt_ee2644bee0e3d622309ef149`).
- nix-config revision: `6aef46b`.
- Atlas checks: `uv run pytest -q` — 131 passed; `uv run ruff check .` — passed.
- Lumio checks: `npm run check` — 29 tests passed and compatibility check passed against Pi
  `0.80.6`; the bundled extension entrypoint also built successfully with esbuild.
- nix-config checks: `nix eval .#evalTests --show-trace` returned `true`; the macsp Darwin
  configuration and all 15 affected derivations built successfully. Activation was not performed
  because `darwin-rebuild switch` requires the user's local sudo/Touch ID authorization.
- Production safety: SQLite backup
  `/home/wicsp/projects/Atlas/data/backups/atlas-before-rfc0003-20260715.sqlite3` passed
  `integrity_check`; the additive schema preserved existing Runs.
- Real end-to-end smoke, 2026-07-15:
  - Source: `src_1b250bea40fb47d4824428bf399bb290` (`bilibili:BV1cWTQ6PEzd`)
  - Run: `run_c07774c6d15847cfabb066fec9153a30`, completed by
    `agt_219d2003739f5e6703753729` with job `bilibili-summary-v3`
  - transcript Resource: `res_6d9dda584551b698a31a6101796dd5ae`
  - summary Resource: `res_8df166177823f500e9b7f7abb65b7ad7`
  - card: `Vortex Next/Resources/Cards/res_8df166177823f500e9b7f7abb65b7ad7.md`
  - completion Event reports two ArtifactRefs and two Resources; Run output is 483 bytes of
    bounded metadata, while the 4,639-byte transcript and 2,856-byte summary remain mode-0600
    external files whose SHA-256 values match Atlas.

The old Vortex vault was not migrated or written by this implementation. No Knowledge Comment was
created during the production smoke test; the explicit command and non-overwrite boundary are
covered by Lumio tests, so validation did not manufacture a human-owned note.
