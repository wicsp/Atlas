# RFC 0020: Project writing workspace

- **Status:** Accepted
- **Owner:** Atlas
- **Consumers:** Atlas Console, future AtlasApple clients

## Decision

The product presents three concepts to the user:

1. **Materials**: Source, AI-derived Resource, and personal informal Comment.
2. **Knowledge**: reusable Knowledge Notes connected by lightweight links.
3. **Projects**: goal-oriented work that turns knowledge into a final Markdown document.

These are two workflows rather than six pages:

```text
Source -> Resource -> Comment -> KnowledgeNote
Project -> WorkItem -> Markdown Document -> Version / future Export
```

`Project` owns a concrete goal, optional audience and deadline, lifecycle status, WorkItems, and
Documents. `WorkItem` is one actionable next step. `Document` is the canonical output and uses
Markdown as its only editable source. A Document may have immutable version snapshots.

The older `Project` object in the execution subsystem groups Runs. Its existing `/api/projects`
contract is retained for deployed execution clients, but it is not shown as a user Project.
Human projects use `/api/writing-projects` until the execution contract is renamed in a versioned
cross-client migration.

## Knowledge while writing

The writing client inserts `[[kn_<id>|title]]` into Markdown. Atlas indexes valid stable IDs on
every save and returns the referenced Knowledge Note IDs with the Document. The index is
rebuildable from Markdown, so it cannot become a second authority.

Obsidian CLI is an optional adapter for opening, importing, exporting, or syncing a local Vault.
It is not a runtime dependency: the CLI requires an Obsidian installation and normally a running
desktop app, while Atlas must remain a central service.

## API

- `POST/GET /api/writing-projects`
- `GET/PATCH /api/writing-projects/{project_id}`
- `POST /api/work-items`
- `PATCH /api/work-items/{work_item_id}`
- `POST /api/documents`
- `GET/PATCH /api/documents/{document_id}`
- `POST/GET /api/documents/{document_id}/versions`

All endpoints require the operator session or control credential and use optimistic revision checks
for mutable records.

## Deferred exports

DOCX, PDF, LaTeX, and Typst are output adapters, not alternate editable sources. A later export
workflow may invoke Pandoc or a specialized renderer and record the result as an Artifact. PDF
bibliography and attachment management remain Zotero-owned until that contract is designed.
