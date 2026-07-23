# RFC 0007: Source Machine Resource Purge

- **Status:** Superseded by RFC 0014
- **Date:** 2026-07-19
- **Owners:** Atlas control plane, Lumio local executor, Atlas Review Console

## Summary

> The public Source purge operation and Console delete action described here were removed by
> RFC 0014. The verified local cleanup workflow remains an internal retention mechanism for expired
> ignored Resources.

Some captured Sources turn out to have no lasting value. `dismiss` is intentionally reversible: it
changes review state and removes a generated card, but preserves the Resource and its artifact. This
RFC adds a separate, irreversible operation that purges every machine-produced Resource belonging
to one Source while retaining the Source and execution audit.

The operation never deletes human-authored Knowledge, an original external video/page/PDF, or Run
history. If machine material has already become evidence for a KnowledgeRef, purge is rejected.

## Why Source scope

The Console normally displays summary Resources, but one capture may also have transcripts,
multiple summary versions, and several ArtifactRefs. Deleting only the visible summary would create
an incomplete and misleading lifecycle: hidden transcript bytes and stale provenance would remain.

Therefore the public operation accepts a `source_id`, not an arbitrary Resource ID. Its unit is:

```text
all Resource rows for Source
  + their unshared ArtifactRef rows
  + verified local artifact files
  + generated Obsidian Resource cards
```

The Source row and all Run/Event records remain as the minimal audit trail that the capture and purge
occurred.

## API and protection rules

The authenticated control endpoint is:

```http
POST /api/review-actions/purge-source
Content-Type: application/json

{"source_id":"src_..."}
```

Atlas rejects the request when:

1. the Source does not exist;
2. it has no Resources left to purge;
3. any of its Resources is cited by a KnowledgeRef; or
4. any of its Resources has a pending or claimed `vortex-comment-v1` Run; or
5. a pending or claimed producer Run still targets the Source.

An already-active purge for the same Source is returned rather than duplicated. A successful new
request returns the deleted Resource IDs and a `vortex-resource-purge-v1` cleanup Run.

## Transaction boundary

In one SQLite transaction Atlas:

1. validates every protection rule;
2. captures a cleanup manifest containing Resource identity, kind, and eligible ArtifactRef
   metadata;
3. deletes all Resource rows and only ArtifactRef rows not shared by an unpurged Resource;
4. creates the pending Mac cleanup Run and its enqueue Event.

This ordering prevents a concurrent comment request from producing Knowledge that cites already
deleted evidence. Atlas metadata is gone when the API succeeds; local byte/card cleanup can finish
later. If the Mac is offline, the Run remains visible and retryable. If cleanup ultimately fails,
Run diagnostics remain available even though the machine Resource metadata is already gone.

## Lumio cleanup contract

Lumio accepts only the fixed `vortex-resource-purge-v1` manifest created by Atlas. It does not expose
a generic filesystem-delete tool.

For every artifact file Lumio verifies:

- a `file://` URI inside `ATLAS_ARTIFACT_ROOT`;
- lexical and resolved-path containment;
- a regular, non-symlink file;
- the recorded byte size and SHA-256 checksum.

Only after those checks may it unlink the file. Summary Resource cards are removed through the
existing generated-card path under the configured Vortex vault. Missing files and cards count as
success, making retries idempotent. Safety violations fail without deletion and are not retried;
unexpected I/O failures use the bounded Run retry policy.

## Console behavior

Superseded: the Console exposes only **忽略** and **撤销忽略**. It no longer exposes a destructive
Source-scoped action.

## Explicit non-goals

- deleting Source or Run/Event audit records;
- deleting KnowledgeRef rows or human-authored files under `Knowledge/**`;
- deleting the original Bilibili favorite, video, paper, webpage, or Zotero entry;
- bulk purge, retention policies, or automatic value classification;
- a general-purpose remote filesystem deletion API;
- preserving enough machine metadata to reconstruct a purged Resource.

## Acceptance checks

- Atlas tests prove multi-Resource deletion, ArtifactRef cleanup, active-purge reuse, KnowledgeRef
  protection, active-comment protection, and active-producer protection.
- Lumio tests prove verified deletion, idempotent replay, root-containment refusal, and checksum
  mismatch refusal.
- Console tests preserve credential isolation and include an explicit confirmation-gated purge
  action.
- Existing Atlas, Lumio, and Console suites remain green.
