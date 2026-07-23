# RFC 0014: Bounded Resource Ignore Queue

- **Status:** Accepted and implemented
- **Date:** 2026-07-23
- **Owners:** Atlas control plane, Atlas Review Console, Lumio, AtlasRunner
- **Supersedes:** RFC 0007 public purge API and Console action

## Summary

Resource removal is one operator concept: **ignore**. Ignoring is initially reversible, works for
both pending and reviewed Resources, and preserves a saved Comment and KnowledgeRef while it remains
inside the undo window. **Undo ignore** restores the Resource to the review state it had before it
was ignored.

Atlas retains only the 10 most recently ignored Resources. Ignoring another Resource permanently
expires the oldest ignored Resource and its dependent machine and review material. This bounded
queue gives every Resource a simple remove-and-undo interaction without accumulating an unbounded
trash collection.

## API

The authenticated Console endpoints are:

```http
POST /api/review-actions/ignore-resource
{"resource_id":"res_..."}

POST /api/review-actions/restore-resource
{"resource_id":"res_..."}
```

Both return the current Resource, any Resource IDs expired by retention, and cleanup Runs created for
local material. The legacy `PATCH /api/resources/{resource_id}/review` route delegates `dismissed`
and restoration transitions to the same service. The public `purge-source` endpoint is removed.

## Ignore and undo semantics

On the first ignore transition Atlas stores the previous `pending` or `reviewed` state in private
Resource metadata and moves the Resource to `dismissed`. Repeating ignore is idempotent and does not
move the Resource to the front of the queue. Undo removes the private metadata and restores the
recorded state; older dismissed rows without that metadata restore to `pending`.

The private previous-state field is never exposed through Resource API metadata. Completing a new
Comment clears stale previous-state metadata because the Resource is authoritatively `reviewed`.

## Retention and permanent expiry

After every new ignore, Atlas orders all dismissed Resources by ignore time and retains the newest
10. In the same database transaction it expires every overflow Resource:

1. delete its Resource row;
2. delete an attached Comment and its KnowledgeRef;
3. detach it from any non-comment KnowledgeRef;
4. delete its unshared ArtifactRef and inline content;
5. enqueue a fixed `vortex.resource-purge` cleanup Run grouped by Source.

The cleanup manifest may request deletion of the verified artifact, generated Resource card, and
`Knowledge/Comments/{resource_id}.md` projection. AtlasRunner performs those local mutations with the
existing fixed workflow and grant checks. Missing local files are successful no-ops, so retry is
idempotent.

Once an ignored Resource expires from the queue, undo returns not found. Source and Run/Event audit
records remain.

## User interface

Each Resource card exposes exactly one **忽略** action. A saved Comment follows its Resource through
ignore and undo; the Comment strip does not add a second action. The ignored view shows
**撤销忽略** and explains that only the latest 10 entries are recoverable. There is no separate
delete button or confirmation flow.

## Acceptance checks

- Pending Resources undo to pending; reviewed Resources with Comments undo to reviewed.
- Ignoring a commented Resource does not immediately remove its Comment or KnowledgeRef.
- The eleventh ignored Resource expires the oldest entry and creates a local cleanup Run.
- Expiry removes the Atlas Comment/KnowledgeRef and Runner removes the projected comment note.
- The public Source purge endpoint and Console delete control are absent.
