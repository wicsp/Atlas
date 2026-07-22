# RFC 0012: Atlas-owned Bilibili favorites schedule

- **Status:** Implemented
- **Decision date:** 2026-07-22
- **Supersedes:** RFC 0006 scheduling and Lumio-controller ownership

## Decision

Atlas owns a persistent daily Schedule for 02:00 in `Asia/Shanghai`. Each occurrence idempotently
invokes `bilibili.favorites-scan@1`. The scan requires node `macsp`, executor `script`, and grant
`bilibili-cookie:read`, so only the data-local AtlasRunner can claim it.

The macOS LaunchAgent and Lumio nightly controller are removed. Lumio is not a scheduler or a
background execution plane.

## Flow

```text
Atlas Schedule (02:00 Asia/Shanghai)
  -> bilibili.favorites-scan@1:scan on macsp
  -> read exact favorites folder "Atlas"
  -> remove each successfully read item from that folder
  -> complete the scan with bounded video identities
  -> Atlas upserts Sources and idempotently fans out bilibili.summary@5 invocations
  -> AtlasRunner executes acquire and replaceable agent summary steps
```

Atlas catches up after restart: once local time has passed 02:00, a missing occurrence is created.
If macsp is offline, the scan Run remains pending until its matching Runner returns.

## Removal and retry semantics

The user's favorites folder is an ingestion inbox, not durable storage. A valid video is removed as
soon as the scan adapter has read its bounded identity. The adapter does not alter Watch Later.

Because external removal precedes Atlas completion, AtlasRunner stores a private per-Run receipt.
Each successfully removed item is durably marked before the attempt completes. A retry replays that
receipt, preventing a transient Atlas or lease failure from losing the summary input. Items whose
removal failed stay in the favorites folder and are retried by a later scan.

Atlas fan-out is also idempotent. Schedule occurrences and per-video summary invocations derive
stable identities, and a fan-out ledger prevents repeated reconciliation from creating duplicate
work. Existing summary Resources are reused instead of recomputed.

## Boundaries

- Atlas stores schedules, occurrences, scan Runs, Sources, fan-out state, and summary workflows.
- AtlasRunner owns browser-cookie access, the narrow Bilibili adapter, receipts, and execution.
- Lumio owns interactive Pi UX only.
- `nix-config` no longer provisions a Bilibili queue LaunchAgent.
