# RFC 0013: arXiv abstract preview

## Status

Initial vertical slice.

## Problem

An arXiv paper should be understandable before its PDF is downloaded or the item is accepted into
Zotero. The preview must use real bibliographic metadata and the author's abstract, must not imply
that the full paper was read, and must fit the existing Source / Resource / Knowledge boundary.

This slice deliberately handles one explicit arXiv identifier at a time. Query-based discovery,
automatic recommendation, PDF acquisition, Zotero writes, citation refresh, and full-text analysis
remain later work.

## Ownership

- Atlas owns the `paper.preview@1` workflow contract and the paper Source/Resource records.
- AtlasRunner acquires bounded metadata from the arXiv Atom API and runs the summary implementation.
- Lumio only parses the human-supplied arXiv ID or URL, upserts the Source, and invokes the workflow.
- Zotero remains authoritative for accepted bibliography, notes, and PDFs. Preview creates no
  Zotero item and downloads no PDF.

## Contract

`paper.preview@1` contains two ordered steps:

1. `acquire` resolves the identifier through the arXiv Atom API and publishes a deterministic
   `extraction` Resource containing bounded JSON metadata and the abstract.
2. `summarize` reads only that verified artifact and publishes an AI `summary` Resource with
   `profile_id=paper-preview-v1` and `basis=abstract`.

The invocation input contains `source_id`, normalized `arxiv_id`, and canonical arXiv abstract URL.
The acquire step may enrich the Source with title, DOI, and `journal_ref` when arXiv reports them.
It records a PDF URL as metadata but must never download it.

The summary must state that it is abstract-based, distinguish author claims from verified results,
and avoid inventing method details, numerical results, limitations, or publication status. Missing
abstracts fail the workflow instead of prompting the model to reconstruct one.

## API and rate behavior

Version 1 does not require an API key. AtlasRunner uses the arXiv Atom API as the authoritative
source for an explicit arXiv preview, sends a descriptive User-Agent, serializes requests with at
least three seconds between them, and performs bounded retry handling for throttling or transient
server errors. Semantic Scholar remains an optional future discovery/enrichment source; its
availability must not block an arXiv abstract preview.

## Identity and idempotency

- Source key: `arxiv:<lowercase-id-with-version-if-supplied>`.
- Canonical URI: `https://arxiv.org/abs/<id>`.
- `arxiv_id` is retained even when arXiv metadata reports a DOI or journal reference.
- Resource identity remains content-addressed under the existing Atlas completion contract.
- Re-running preview may create a new current profile version when metadata or summary content
  changes; existing human Knowledge references continue to point at their original Resource.

## Acceptance criteria

1. Lumio accepts a bare arXiv ID and `/abs/` or `/pdf/` URL, rejects unrelated input, and invokes
   `paper.preview@1` without fetching paper metadata itself.
2. Atlas advertises the immutable two-step workflow and routes acquire to a script executor and
   summarize to an agent executor.
3. AtlasRunner validates arXiv Atom data, stores a private content-addressed metadata artifact,
   and publishes `paper-metadata-v1` plus `paper-preview-v1` Resources.
4. The preview prompt and Resource metadata make the abstract-only evidence boundary explicit.
5. No PDF is requested and no Zotero mutation occurs.
6. Atlas, AtlasRunner, Lumio, and workspace checks pass before a deployment checkpoint.
