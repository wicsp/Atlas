# RFC 0016: Atlas-Central Generated Artifact Content

Status: Implemented for bounded text

## Decision

Atlas is the authoritative store for generated Resource content. Bounded text Artifacts are
uploaded with Run completion, verified against their declared size and SHA-256 checksum, and
addressed as `atlas://artifacts/{artifact_id}`.

Runner-local files are execution caches. A downstream workflow step receives verified content from
Atlas in its dependency context and therefore does not require placement on the producer's node.

## Scope

The initial bound is 8 MiB per text Artifact. It covers:

- Bilibili transcripts and summaries;
- rendered web extractions and summaries;
- paper metadata, preview, Zotero PDF-text extraction, and full-text summary;
- comparison and other generated Markdown Resources.

The API continues to support one-time backfill for older Artifact manifests. Backfill changes the
canonical URI from a local `file://` URI to `atlas://`. AtlasRunner performs one bounded,
checksum-verified legacy text backfill at startup.

## Integrity and lifecycle

Atlas validates byte length and SHA-256 on initial completion and backfill. Content is immutable
after the first accepted upload. Resource publication and inline Artifact content are committed
with the terminal Run transaction.

Purge and ignore policies continue to operate on Atlas metadata and content. Local cache cleanup
must never be required for another node to read an accepted Resource.

## Deferred binary storage

PDF originals remain Zotero-managed. A later RFC must define attachment identity, maximum size,
streaming upload/download, deduplication, retention, backup, and Zotero synchronization before
Atlas accepts PDF bytes as authoritative binary Artifacts.
