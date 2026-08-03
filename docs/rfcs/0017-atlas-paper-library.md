# RFC 0017: Atlas Paper Library

- **Status:** Superseded by RFC 0023
- **Owner:** Atlas
- **Consumers:** Atlas Console, AtlasRunner, future AtlasApple clients

## Decision

Atlas owns paper-library organization and discovery. Zotero continues to own bibliographic items
and PDF originals, while Atlas owns paper tags, categories, citation links, generated text, search,
and deterministic multi-paper comparison views.

Paper organization is stored on the paper Source metadata under bounded, server-validated keys:

- `paper_tags`
- `paper_categories`
- `paper_citation_source_ids`

The paper APIs provide:

- bounded search over titles, identifiers, organization metadata, Atlas-owned generated text, and
  centrally stored PDF extraction text;
- explicit tag, category, and citation updates;
- a deterministic comparison view for two to eight selected papers.

Comparison views do not claim to be new knowledge and do not silently create Resources. AI synthesis
can be added later as a versioned workflow once its evaluation contract is defined.

## Boundaries

- Zotero remains authoritative for PDF bytes and bibliographic attachment management.
- Atlas is authoritative for generated Artifact content and paper-library organization.
- Citation links reference Atlas paper Source IDs and cannot reference the same Source.
- Search is intentionally bounded to the latest 500 paper Sources and their Atlas-owned summaries.
- All writes require operator or control authentication.
