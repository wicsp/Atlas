# RFC 0018: Atlas-native Resource review

- **Status:** Accepted
- **Owner:** Atlas
- **Consumers:** Atlas Console, AtlasRunner, Lumio, future AtlasApple clients

## Decision

Atlas is the sole authority for Resource comments, review state, and ignored-Resource retention.
The Console reads Resource content and writes Markdown comments directly through
`POST /api/review-actions/complete-comment`. Obsidian and Zotero integrations may project or manage
copies later, but they are not part of the comment completion contract.

The following node-local workflows and their public request interfaces are retired:

- `vortex.comment@1`
- `vortex.comment-sync@1`
- `vortex.resource-purge@1`
- `POST /api/review-actions/comment`
- `POST /api/review-actions/sync-comment`

Retired workflow definitions are removed from the active catalog at startup and cannot be
registered again. Historical Runs and invocations remain available as audit records, but the
Console does not attach their status or attempt metadata to Resource cards.

## Retention

Ignoring a Resource is an Atlas transaction. Atlas keeps the ten most recently ignored Resources;
when the limit is exceeded, it deletes the oldest Resource and its unshared central Artifact
content, Comment, and KnowledgeRef directly. It no longer creates a Runner cleanup Run or exposes
the obsolete `cleanup_runs` and `remove_comment` fields.

Optional local projections converge independently from Atlas state. Their absence or delay does
not affect review completion, retention, or central data integrity.
