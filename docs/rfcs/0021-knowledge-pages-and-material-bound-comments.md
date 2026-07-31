# RFC 0021: Knowledge Pages and material-bound Comments

Status: accepted

## Decision

Atlas exposes three user workspaces that follow the actual writing workflow:

1. **Materials** handles a Source and its machine-produced Resource. A Comment is the user's durable insight about that material. It is edited in place and is not a staging record that must be promoted.
2. **Knowledge Base** maintains topic-oriented Knowledge Pages. A page has a title, a core claim, a Markdown body, tags, and evidence links to any number of Sources, Resources, and Comments.
3. **Projects** maintains goals, WorkItems, and final Markdown Documents. A Document may quote a Comment directly, link a Knowledge Page with `[[kn_id|label]]`, or live-embed the current page with `{{knowledge-page:kn_id}}`.

The API keeps the existing `knowledge_note_id` identifier and `/api/knowledge-notes` route for compatibility. Console language presents this aggregate as a **Knowledge Page**, not an atomic note.

## Material bundle

The four relevant views of one material are all preserved:

- Source: the first-hand external item and provenance.
- Extraction: deterministic or acquired content used by later processing.
- Resource: a relatively objective, machine-generated interpretation with generator provenance.
- Comment: the user's own judgment, question, disagreement, or insight.

Creating or updating a Knowledge Page from a Comment automatically retains the Comment's Resource and Source evidence. A Comment may support zero, one, or many Knowledge Pages; there is no one-to-one promotion state.

## AI assistance

`knowledge.suggest@1` runs on an allowlisted AtlasRunner agent and supports two modes:

- recommend new multi-material Knowledge Pages;
- recommend improvements to one existing Knowledge Page.

AI output is always a proposal. The Console puts an accepted proposal into the editor, and only a separate explicit save or publish action changes human-owned knowledge. AI cannot directly publish a Knowledge Page.

## Markdown output

Markdown remains canonical. Atlas indexes both links and live embeds. The rendered-Markdown endpoint resolves a live embed to the current title, claim, and body of its Knowledge Page, allowing a project document to reuse maintained knowledge without copying it manually.

LaTeX, Typst, PDF, and Zotero-specific output remain downstream concerns. Atlas remains the central authority for metadata, Markdown, relationships, and history; Zotero may remain the PDF library without becoming the knowledge database.
