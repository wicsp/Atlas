# RFC 0023: Project-context paper workflow

- **Status:** Accepted
- **Owner:** Atlas
- **Consumers:** Atlas Console and AtlasRunner

## Decision

Paper retrieval belongs in the writing-project workspace, where the project goal, current
Document, and explicit query provide the reason for finding a paper. The Materials landing page
does not expose a general-purpose paper-library editor or deterministic comparison panel.

Atlas keeps its bounded paper search index, but presents matching papers alongside Knowledge Pages
and Comments as writing references. A paper result links to its original Source and current reading
Resource; it does not become part of a Document until the person explicitly uses it.

## Organization suggestions

Tags and categories are proposed by `paper.organize@1` while a person is reading and writing a
Comment. Atlas supplies the workflow with:

- the selected paper and bounded Resource evidence;
- the paper's currently confirmed tags and categories;
- the distinct tags and categories already confirmed on other paper Sources.

The model must prefer an existing label when it has the same meaning. It may propose a new label
only when the existing vocabulary has a real semantic gap, and must mark every proposal as either
`reuse` or `new`. Suggestions are machine output: they are not written to Source metadata until the
person places them in the Comment editor, changes them if needed, and saves.

Confirmed organization remains Atlas-owned Source metadata under `paper_tags` and
`paper_categories`. Reference-list citation edges are not manually authored in this workflow; a
future extraction contract may derive them from paper evidence.

## Boundaries

- Zotero remains authoritative for bibliography records, PDF bytes, and attachment lifecycle.
- Atlas search and AI suggestions do not silently modify Comments, Documents, or Knowledge.
- Internal Source IDs are never requested as paper-organization input in the Console.
- Cross-paper synthesis belongs to an explicit project writing or Knowledge workflow, not a
  metadata-only library comparison view.
