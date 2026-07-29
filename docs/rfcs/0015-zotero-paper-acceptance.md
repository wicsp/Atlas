# RFC 0015: Zotero Paper Ingest and Full-Text Summary

Status: Implemented

## Summary

Atlas exposes two domain actions for arXiv papers:

- `POST /api/paper/ingest` creates or reuses a `paper-preview-v1` Resource;
- `POST /api/paper/fulltext` creates or reuses a `paper-fulltext-v1` Resource for one validated
  preview.

Clients cannot select the underlying workflow. Direct generic invocation of `paper.ingest` and
`paper.fulltext` is rejected so validation and idempotency cannot be bypassed.

## Ingest contract

The client first upserts a paper Source with an `arxiv_id`, then calls:

```http
POST /api/paper/ingest
Content-Type: application/json

{"source_id":"src_..."}
```

Atlas accepts only a paper Source with an arXiv identifier. It reuses an existing semantically
valid preview or active `paper.ingest@1` invocation. Invalid previews are dismissed rather than
treated as successful cached work.

The Runner imports or reuses the Zotero item and PDF, prefers the author abstract, falls back to
bounded PDF-leading text, and renders the versioned `paper-preview-v1` prompt. Prompt rendering
fails if any template placeholder remains unresolved. The result adapter requires the expected
preview sections and rejects missing-input responses.

## Full-text contract

```http
POST /api/paper/fulltext
Content-Type: application/json

{"source_id":"src_...","preview_resource_id":"res_..."}
```

Atlas verifies that the Source is a paper, the preview exists, belongs to that Source, and is a
`paper-preview-v1` summary. Reuse is keyed by both Source and preview Resource.

`paper.fulltext@1` imports or reuses the Zotero item, waits for Zotero full-text indexing, uploads
the bounded extracted text to Atlas, and publishes extraction and summary Resources. The final
summary records the exact source preview and extraction IDs.

## Identifier scope

The current contract supports arXiv identities. DOI-only auto-ingest is rejected at the local
ingress instead of enqueueing work that is guaranteed to fail. DOI support requires a later RFC
covering canonical identity, metadata provider, versioning, and PDF availability.

## Local security

The Zotero-to-Runner auto-ingest endpoint binds to loopback and also requires a random ingress
token. The token is stored outside source control in the Runner configuration and in a private
Zotero preference. Loopback alone is not treated as authorization.

The Zotero observer unregisters using the identifier returned by `registerObserver`. Items created
by the Atlas bridge are suppressed from auto-ingest to avoid feedback loops.

## Storage

Atlas owns Source metadata, extracted text, summaries, provenance, and review state. Generated text
is stored centrally as an Atlas Artifact. Zotero currently owns the original PDF bytes and
attachment lifecycle; central PDF storage is deliberately deferred until attachment identity and
synchronization semantics are defined.
