# RFC 0023: Atlas-hosted Resource media

## Status

Accepted for implementation.

## Problem

Paper Resources may contain figures whose upstream arXiv HTML conversion later disappears. A
Resource that embeds those external URLs is therefore not durable even though its prose and
provenance are stored in Atlas.

## Decision

Runner may publish bounded image artifacts as base64 data URLs in the existing inline artifact
content field. Atlas exposes authenticated, same-origin decoded bytes at:

`GET /api/runs/{run_id}/artifacts/{artifact_name}/media`

The endpoint resolves the artifact by its immutable producing Run and name, accepts only PNG,
JPEG, WebP, and GIF content types, requires the stored data URL media type to match the artifact,
and returns immutable private caching headers. Resource Markdown references this Atlas URL rather
than the upstream image URL.

The encoded representation remains subject to the existing 8 MiB inline artifact bound. Its
`size_bytes` and checksum describe the canonical stored data URL; the media endpoint is only a
decoded presentation of those content-addressed bytes.

`paper.fulltext@3` first downloads and validates selected arXiv HTML images. When arXiv reports
that HTML conversion is unavailable, Runner reads the official source archive, associates
`includegraphics` assets with their captions, and rasterizes bounded PDF figures before publishing
them. `paper-reading-brief-v3` embeds only the resulting Atlas media URLs. Existing v2 Resources
remain immutable; the backfill creates replacement v3 Resources.

## Consequences

- Reading a Resource no longer depends on arXiv HTML availability.
- Authentication and CSP remain same-origin.
- Images stay covered by Source purge and ArtifactRef lifecycle rules.
- PDF or SVG are not served by this endpoint; Runner must convert selected figures to a supported
  raster format before publication.
