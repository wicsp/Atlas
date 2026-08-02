# RFC 0022: Paper Reading Brief v2

Status: accepted

## Decision

`paper.fulltext@2` publishes `paper-reading-brief-v2`, a layered reading brief rather than a
section-by-section compression of the paper. Existing `paper-fulltext-v1` Resources remain
immutable history. The Console treats both profiles as one paper-fulltext slot and shows the v2
Resource when it exists.

The brief answers, in order:

1. what problem the paper addresses;
2. whether the method trains or fine-tunes a model, or instead uses prompting, rules, retrieval,
   memory, search, or tools;
3. what information and prior knowledge each mechanism uses;
4. whether the reported improvement is large, modest, mixed, or insufficiently supported;
5. how the method differs from the closest compared work;
6. what the strongest evidence, weakness, and unresolved review questions are.

Raw metrics, formulas, split details, and appendix evidence remain available in a collapsed
evidence layer. Every metric in the visible brief is paired with its direction and plain-language
meaning. Formulas are omitted from the visible layer unless the formula itself is a claimed
contribution.

## Figures

For arXiv Sources, the Mac-local extraction step may read the public arXiv HTML representation and
provide a bounded catalog of figure captions and `https://arxiv.org/` image URLs to the summarizer.
The summarizer may embed at most two catalogued figures: normally one motivation/problem figure and
one method/framework figure. It may not invent or rewrite image URLs. If no reliable catalog is
available, the brief says so and remains text-only.

The Console Content Security Policy permits images only from itself, data URLs, and
`https://arxiv.org`. A figure is supporting context, not authoritative evidence; the brief links the
reader back to the original paper for verification.

## Regeneration and history

`POST /api/paper/fulltext` targets workflow version 2 and reuses only an existing
`paper-reading-brief-v2` for the same preview Resource. Therefore every Source that currently has
only `paper-fulltext-v1` can be backfilled through the same validated domain endpoint without
mutating or deleting the old Resource.

Comments and KnowledgeRefs remain attached to the Resource version on which the human wrote them.
The v2 backfill does not promote AI prose into human-owned knowledge.

