# RFC 0011: Console-native Resource review

- **Status:** Implemented
- **Owners:** Atlas content contract and Console interaction

## Decision

Atlas is the canonical store for bounded machine-readable Resource content, human Comments, and
review state. The Console reads Resource content and creates or updates Comments directly through
authenticated Atlas APIs. Completing a review does not require Lumio, AtlasRunner, Obsidian, a
local vault, or a node-local filesystem grant.

AtlasRunner retains node-local Artifact files for provenance and large data, but also attaches up
to 1 MiB of UTF-8 text for Resource types intended to be read in clients. Atlas verifies the inline
body against the Artifact size and checksum and stores it separately. Existing Artifact manifests
may be backfilled only with matching immutable content.

## Boundaries

- Atlas owns Resource content, Comment bodies, hashes, references, and review transitions.
- Console renders bounded content as inert text and edits Markdown Comments.
- AtlasRunner publishes readable summary and comparison bodies alongside local ArtifactRefs.
- Lumio may project selected records into Vortex, but projection is optional and never gates review.
- Obsidian remains useful for long-lived, user-curated knowledge, links, and offline Markdown. It is
  not the Resource reader or operational comment editor.

Large transcripts, media, browser state, credentials, and private host data remain node-local. A
client must never dereference an arbitrary `file://` URI supplied by a Runner.
