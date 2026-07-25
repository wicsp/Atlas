# RFC 0015: Zotero Paper Acceptance and PDF Full-Text Summary

Status: Implemented

## Summary

Atlas exposes one fixed paper action for an abstract-based `paper-preview-v1`
Resource. The action imports the paper into the user's local Zotero library,
waits for Zotero to download and index a PDF, and publishes a separate
`paper-fulltext-v1` summary Resource based on the indexed PDF text.

The abstract preview remains immutable. The full-text summary is another
machine-owned Resource and does not become Knowledge without explicit human
review.

## Contract

The Console calls:

```http
POST /api/paper-actions/accept
Content-Type: application/json

{"resource_id":"res_..."}
```

Atlas accepts only a summary Resource whose profile is `paper-preview-v1`,
whose basis is `abstract`, and whose paper Source has an arXiv identifier. It
returns either:

- the existing `paper-fulltext-v1` Resource;
- the existing active `paper.accept@1` invocation; or
- a newly created `paper.accept@1` invocation.

The client cannot choose a workflow name, implementation, host, grant, URL, or
prompt.

## Workflow

`paper.accept@1` belongs to project `paper-library` and has three ordered
steps:

1. `zotero_import` runs on macsp with `zotero-library:write`;
2. `extract` runs on macsp with `zotero-library:read`;
3. `summarize` runs through the configured Pi adapter.

The first step calls the Atlas Zotero Bridge on
`127.0.0.1:23119`. The plugin uses Zotero's search translators—the same
identifier mechanism as the Zotero lookup UI—to create or reuse an item and
ensure that a local PDF attachment exists. The bridge accepts loopback POSTs
only and requires the `X-Atlas-Zotero: 1` header.

The extraction step reads Zotero's local full-text endpoint for the returned
attachment key. It waits for indexing to complete, bounds the extracted text
to 768 KiB, and publishes a deterministic `paper-pdf-text-v1` extraction
Resource. The PDF itself remains in Zotero and is not copied into Atlas.

The final step creates a `paper-fulltext-v1` summary with:

- `basis: pdf-text`;
- Zotero item and attachment keys;
- indexed and total page counts;
- links to both the preview and extraction Resources;
- `fulltext_human_verified: false`.

## Local installation

Build the Zotero extension from AtlasRunner:

```sh
just package-zotero-plugin
```

Install `dist/atlas-zotero-bridge-0.1.0.xpi` through Zotero's Add-ons manager.
The initial plugin manifest supports Zotero 9.x. AtlasRunner must also
allowlist the three `paper.accept@1` implementations and their declared Zotero
grants; `config/runner.example.json` documents the required entries.

Plugin installation and production Runner configuration are explicit operator
actions and are not performed by the Console.

## Failure behavior

The workflow fails without publishing a full-text summary when Zotero is not
running, no translator is available, no local PDF can be obtained, indexing
does not finish within the bounded retry window, or the extracted text exceeds
the configured safety limit. Retrying the action reuses active work and reuses
an already published full-text summary.
