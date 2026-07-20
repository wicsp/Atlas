# RFC 0008: Local-first review and knowledge operations

- **Status:** Implemented
- **Decision date:** 2026-07-20
- **Owners:** Atlas, Atlas Console, and Lumio
- **Protocol:** `atlas-agent-v3` (unchanged)

## Summary

Review initiation is now local-first. Starting a comment creates and opens a deterministic Vortex
note immediately; it does not create a KnowledgeRef and does not change Resource review state.
Only the explicit completion action asks an online Lumio agent to read the local draft and upload
it to Atlas. Atlas stores the Markdown Comment, registers its KnowledgeRef, and changes the
Resource from `pending` to `reviewed` in one transaction.

```text
write comment
  -> browser opens Resource Card
  -> browser creates/opens Knowledge/Comments/<resource_id>.md
  -> human writes locally while Resource remains pending
  -> complete comment
  -> Atlas enqueues vortex-comment-sync-v1
  -> Lumio reads and validates the deterministic local note
  -> Lumio uploads Markdown plus its sha256 hash
  -> Atlas atomically stores Comment + KnowledgeRef and marks Resource reviewed
```

Atlas is the canonical store after completion. Obsidian remains the local writing and reading
surface. The deterministic note identity is constructed by Atlas rather than accepted from the
browser, and the submitted hash is verified before any review state changes.

## Analysis profiles

`Resource.metadata.profile_id` is the semantic identity of an analysis purpose. Generator and
model metadata remain provenance, not the purpose itself.

- the current unreferenced Resource for one `(source_id, profile_id)` is shown and projected;
- older unreferenced generations in the same slot are hidden and their disposable cards removed;
- Resources with different profiles are peers, not revisions;
- any historical Resource cited by a KnowledgeRef remains visible and projected so human evidence
  links do not break;
- legacy Resources without `profile_id` use their complete generator signature as a conservative
  fallback profile.

The Bilibili pipeline declares `bilibili-transcript-v1` and `bilibili-overview-v1` profiles.

## Generated operations

Lumio produces two deterministic, rebuildable Vortex reports from Atlas metadata and local note
presence:

- `Resources/Digests/Daily Papers/<date>.md` lists pending current Resources, unfinished local
  drafts, and failed Runs;
- `Resources/Digests/Audits/<date>.md` reports duplicate active profile slots, missing or blank
  KnowledgeRef notes, reviewed Resources without KnowledgeRefs, and stale pending Resources.

The daily report refreshes after successful Atlas startup reconciliation. Sunday startup also
refreshes the weekly audit. Manual `/atlas:digest` and `/atlas:audit` commands use the same code.

## Friction comparison

Friction analysis is explicit, never automatic. Atlas Console or `/atlas:compare` enqueues the
fixed `vortex-comparison-v1` capability. Lumio reads the selected machine Resource and bounded
Comments from Atlas, then produces a machine-owned `comparison` Resource with
candidate `supports`, `contradicts`, `updates`, or `related` relations.

The comparison prompt treats both sides as untrusted quoted data, requires evidence from both
sides, and cannot edit Knowledge notes or confirm relations. The result carries profile
`friction-comparison-v1` and is projected as a generated Resource Card.

## Compatibility

The old `POST /api/review-actions/comment` and `vortex-comment-v1` capability remain temporarily
for in-flight clients, but the handler now creates only a pending local draft. New Console clients
use local Obsidian URIs plus `POST /api/review-actions/sync-comment`; only Lumio calls the
content-bearing `POST /api/review-actions/complete-comment` endpoint.

No agent protocol bump is required. Atlas adds a `comments` table through its existing additive
SQLite bootstrap; old metadata-only KnowledgeRefs remain visible and can be synchronized by
running completion again.
