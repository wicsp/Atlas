# RFC 0006: Nightly Bilibili Atlas Queue

- **Status:** Accepted for implementation
- **Milestone:** 3.4
- **Owners:** Atlas protocol and records; Lumio acquisition/orchestration; `nix-config` scheduling
- **Accepted:** 2026-07-19

## Summary

The Bilibili favorites folder named exactly `Atlas` becomes an explicit ingestion queue. At 02:00
on an awake Mac, or after its next wake when the calendar event was missed, one bounded Lumio
controller scans that folder, processes videos sequentially through the existing
`bilibili-summary-v4` Run, verifies publication of a summary Resource, and then removes that one
video from both the `Atlas` favorites folder and Watch Later.

This RFC does not classify all of Watch Later, add a general scheduler to Atlas, or create a second
summary pipeline. The user's act of adding a video to the `Atlas` folder is the classification and
capture decision.

## User-visible outcome

Before going to sleep, the user adds knowledge videos to the Bilibili `Atlas` favorites folder.
The next morning, successfully processed videos appear as pending summary Resources in the Atlas
Console and as rebuildable Resource Cards in Vortex. Failed or unfinished videos remain in the
Bilibili queue. Existing human Knowledge files are never generated or changed.

## Why a dedicated favorites folder

Watch Later mixes entertainment, references, tutorials, and accidental captures. Title-based LLM
classification would be both costly and unsafe because a false positive could delete an item. An
explicit folder provides a deterministic queue boundary while retaining Watch Later as a separate
personal list.

The queue is resolved by the exact, unique title `Atlas`. A missing or duplicate match fails the
whole scan before any mutation. The current Bilibili media ID is an implementation observation,
not durable configuration.

## Ownership and runtime shape

### Atlas

Atlas remains authoritative for Source identity, Run state, Resource publication, provenance, and
review status. RFC 0006 uses the existing RFC 0003/v3 endpoints and adds no schema or runtime API.
The `bilibili-capture` Project and `bilibili-summary-v4` Runs make every attempt visible.

Atlas does not store Bilibili cookies, call Bilibili APIs, or delete external list entries.

### Lumio

Lumio owns the Bilibili adapter and one-shot queue controller. The controller temporarily starts
Pi in its supported RPC/headless mode. Session startup supplies the configured model, registers a
normal Lumio executor, and starts the existing Atlas work poller. No second summary implementation
or permanent background agent is introduced.

### nix-config

`nix-config` provisions one macOS LaunchAgent with `StartCalendarInterval` at 02:00, required
packages and paths, and non-secret configuration. Credentials continue to come from the existing
agenix-managed token file and the browser login store. The LaunchAgent does not contain secret
values.

macOS may defer a calendar job while the MacBook is asleep. The first version runs on the next
wake; this RFC does not claim remote wake or an exact wall-clock guarantee.

## Queue transaction

Only one controller instance may run at a time. It takes a local advisory lock, creates a private
temporary cookie file, and performs these steps for one video at a time:

1. Resolve the exact `Atlas` favorites folder and list all pages.
2. Upsert Source `bilibili:<bvid>` with the canonical video URL.
3. If that Source already has a summary Resource, skip recomputation and continue at step 7.
4. Ensure Project `bilibili-capture` exists and enqueue one `bilibili-summary-v4` Run with
   `max_attempts: 1` and queue-origin metadata.
5. Wait for that Run to become terminal, within the controller's overall nightly deadline.
6. Require status `completed` and a summary Resource whose `source_id` and
   `produced_by_run_id` match this Source and Run.
7. Remove the individual video from the `Atlas` favorites folder.
8. Remove the same individual `aid` from Watch Later when present.

Steps 7 and 8 are independent, idempotent cleanup operations. If only one succeeds, the next scan
sees the existing summary Resource and retries cleanup without rerunning the model.

The controller stops accepting new videos at its deadline, lets no new external mutation begin,
closes the headless Pi child, deletes the temporary cookie file, and releases the lock. Unprocessed
items remain queued for the next run.

## Deletion safety

External deletion is never performed inside the `bilibili-summary-v4` handler or before Atlas has
accepted Resource publication. This preserves the RFC 0002 lease boundary: a locally generated
artifact or ambiguous terminal report is insufficient evidence for deletion.

The automation provides no bulk-clear operation. Every mutation names one canonical BV ID and one
resolved `aid`. API errors are visible and leave the remaining queue untouched. A failed summary,
missing Resource, lost lease, Atlas outage, expired browser login, missing model, over-duration
video, or multipart ASR refusal leaves the video in the queue.

## Credentials and logs

- Browser cookies are copied only to a mode-`0600` temporary file and removed in all outcomes.
- Cookie values, bearer tokens, transcripts, and model responses are never printed by the
  controller.
- The Atlas control credential is read from `ATLAS_AGENT_TOKEN_FILE`; it is not passed in process
  arguments.
- Output is one bounded per-run operational summary plus errors suitable for launchd logs.
- Transcript and summary bytes keep the RFC 0003/0005 ArtifactRef layout and are not copied into
  Atlas SQLite.

## Deliberate non-goals

- classifying or clearing the complete Watch Later list;
- deleting every item from a favorites folder;
- adding Atlas Schedule, Batch, or durable outbox objects;
- storing browser credentials in Atlas;
- parallel video processing;
- retrying expensive work after lease expiry;
- remote wake of a sleeping MacBook;
- converting any AI output into human Knowledge.

## Acceptance checks

1. The queue helper lists every page of the exact `Atlas` folder and fails on missing or ambiguous
   names.
2. Cleanup tests cover present-in-both, present-in-one, absent-in-both, malformed BV ID, and one
   failed Bilibili mutation without any bulk request.
3. Controller tests use fake Atlas, Bilibili, and Pi processes to cover empty queue, existing
   summary, successful publication, failed Run, timeout, duplicate invocation, and guaranteed
   credential cleanup.
4. Lumio's existing 40 Atlas tests and compatibility check remain green.
5. `nix flake check`, affected Darwin evaluation, and a full macsp build pass.
6. A manual dry run lists the real folder without enqueueing or deleting.
7. One real queued video completes through headless Pi, publishes a reviewable summary Resource,
   disappears from both Bilibili lists, and produces no Knowledge prose.
8. A deliberately failed video remains in the folder and is visible as a failed Atlas Run.

## Implementation order

1. Add the safe Lumio queue helper and tests.
2. Add the one-shot controller with fake-process/API tests.
3. Add the LaunchAgent and configuration in `nix-config`.
4. Run a read-only real-folder smoke test.
5. Run one explicit real mutation acceptance video.
6. Record deployed revisions here and mark the RFC Implemented.

## Implementation record

Not yet deployed. The initial read-only queue helper resolved the real `Atlas` folder and observed
`BV1wzNL68EB7` on 2026-07-19 without mutation.
