# RFC 0019: Permanent Knowledge Notes and typed relations

- **Status:** Accepted
- **Owner:** Atlas
- **Consumers:** Atlas Console, future AtlasApple clients, future retrieval workflows

## Decision

Atlas distinguishes contextual review from permanent personal knowledge:

- A `Comment` is a human-authored, informal evaluation of one generated `Resource`. It remains
  attached to the reviewed material.
- A `KnowledgeNote` is an independently readable, atomic unit of personal knowledge. It can cite
  any number of Sources, Resources, and Comments as evidence.
- A `KnowledgeRelation` is a directed, typed, explainable edge between two Knowledge Notes.
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

Relations use:

- `suggested`: a candidate edge awaiting human judgment;
- `confirmed`: part of the authoritative knowledge graph;
- `rejected`: retained so the same weak suggestion need not be rediscovered.

AI-origin Notes must start as `draft`. AI-origin Relations must start as `suggested`. AI therefore
may discover and explain candidate structure, but it cannot publish permanent knowledge or graph
edges without an operator action.

## Relation vocabulary

The first version supports directed relations:

- `supports`
- `contradicts`
- `extends`
- `refines`
- `example_of`
- `applies_to`
- `supersedes`
- `related_to`

Every relation requires a Markdown rationale. A graph edge is therefore inspectable evidence, not
only a similarity score.

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
- `POST /api/knowledge-relations`
- `GET /api/knowledge-relations`
- `GET /api/knowledge-relations/{relation_id}`
- `PATCH /api/knowledge-relations/{relation_id}`

The neighborhood endpoint returns one-hop confirmed relations by default. Clients may explicitly
include suggested relations for review.

## Deferred work

This RFC does not select an embedding model, vector index, reranker, automatic Claim extractor, or
global graph visualization. Retrieval will be a discovery layer over this authoritative model:
semantic similarity proposes candidates, while confirmed typed Relations remain the durable graph.
