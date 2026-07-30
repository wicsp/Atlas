# RFC 0019: Permanent Knowledge Notes, links, and assessments

- **Status:** Accepted
- **Owner:** Atlas
- **Consumers:** Atlas Console, future AtlasApple clients, future retrieval workflows

## Decision

Atlas distinguishes contextual review from permanent personal knowledge:

- A `Comment` is a human-authored, informal evaluation of one generated `Resource`. It remains
  attached to the reviewed material.
- A `KnowledgeNote` is an independently readable, atomic unit of personal knowledge. It can cite
  any number of Sources, Resources, and Comments as evidence.
- A `KnowledgeLink` is a durable connection between two Knowledge Notes. Ordinary links are
  inferred from stable Markdown wikilinks.
- A `KnowledgeAssessment` is a refreshable AI interpretation such as support, tension, or likely
  duplication. It is advisory rather than part of the authoritative graph.
- The existing `KnowledgeRef` remains a compatibility record for Comment provenance and external
  note locations. It is not the permanent knowledge unit.

Knowledge Notes store a short title, one explicit core claim, optional Markdown elaboration, tags,
lifecycle status, provenance links, a content hash, and a monotonically increasing revision.
Revision checks provide optimistic concurrency control: a client must send the revision it edited,
and Atlas rejects stale updates instead of silently overwriting newer work.

## Lifecycle and authorship

Knowledge Note status is one of:

- `draft`: still being formed or awaiting human review;
- `active`: accepted as current personal knowledge;
- `superseded`: retained for history but replaced by a newer note;
- `archived`: no longer part of the active knowledge system.

AI-origin Notes must start as `draft`. The user does not classify every connection while writing.
Durable links therefore have only two kinds:

- `related`: inferred from `[[kn_<id>|label]]` or explicitly added by a human;
- `supersedes`: an explicit human lifecycle decision that marks the older Note superseded.

AI may refresh `supports`, `tension`, and `duplicate` assessments with a model ID, explanation, and
confidence. Re-running a model replaces its assessment for the same pair and type; it does not
change the durable graph.

## Evidence integrity

Evidence links are normalized rows indexed by Note, evidence type, and target ID. When a Comment is
linked, Atlas automatically expands its Resource and Source provenance. Non-archived Knowledge
Notes protect their Resource evidence from ignored-Resource eviction; the operator must archive or
relink the Note before deleting that evidence.

## API

Atlas exposes control-authenticated endpoints:

- `POST /api/knowledge-notes`
- `GET /api/knowledge-notes`
- `GET /api/knowledge-notes/{note_id}`
- `PATCH /api/knowledge-notes/{note_id}`
- `GET /api/knowledge-notes/{note_id}/neighborhood`
- `POST /api/knowledge-links`
- `GET /api/knowledge-links`
- `POST /api/knowledge-assessments`
- `GET /api/knowledge-assessments`

The neighborhood endpoint returns one-hop durable links and advisory assessments in separate
collections so a client cannot accidentally present model interpretation as human-owned structure.

## Deferred work

This RFC does not select an embedding model, vector index, reranker, automatic Claim extractor, or
global graph visualization. Retrieval will be a discovery layer over this authoritative model:
semantic similarity proposes Notes and refreshes Assessments, while Markdown links remain the
durable graph.
