# RFC 0005: Bilibili Subtitle-First Local ASR Fallback

- **Status:** Implemented
- **Decision date:** 2026-07-16
- **Implemented:** 2026-07-16
- **Owners:** Atlas, Lumio, and nix-config
- **Protocol:** `atlas-agent-v3` (unchanged)
- **Milestone:** 3.3

## Summary

RFC 0005 closes the largest practical gap in the first Bilibili vertical slice: a public video
without platform subtitles can now become a transcript and AI-summary Resource without pretending
that an empty subtitle response is a successful transcript.

```text
captured Bilibili Source
  -> bilibili-summary-v4 Run on Mac Lumio
  -> try optional browser cookies and platform subtitles
  -> if unavailable: bounded yt-dlp audio download
  -> ffmpeg 16 kHz mono PCM normalization
  -> local whisper.cpp transcription
  -> delete temporary media
  -> transcript ArtifactRef + Resource with acquisition provenance
  -> active Pi model summary ArtifactRef + Resource
  -> existing Atlas publication and Vortex review loop
```

The design follows the useful shape observed in
[BiliNote](https://github.com/JefferyHcool/BiliNote): use source-provided subtitles first and pay
the download/ASR cost only when they are absent. Lumio does not depend on BiliNote, its server,
frontend, database, or dependency harness; the smaller personal pipeline is implemented locally
with the existing Atlas execution boundary.

## User outcome

After this RFC:

- a public single-part Bilibili video without subtitles falls back to local ASR automatically;
- failure to read Dia or Chrome cookies no longer blocks anonymous metadata, subtitle, or audio
  acquisition for a public video;
- Atlas and Vortex show whether a transcript came from a platform subtitle or local ASR;
- the ASR engine, model, detected language, duration, and normalization format are traceable;
- downloaded audio, normalized WAV, and whisper JSON are deleted after success, failure, or
  cancellation;
- the transcript and summary remain machine-generated Resources and never become human Knowledge
  without an explicit human comment.

## Invariants

1. **Subtitles remain first choice.** Local ASR is not run when a usable platform subtitle exists.
2. **Cookie extraction is optional.** Lumio uses a temporary cookie file when available and
   continues anonymously when extraction fails. Cookie content never enters Atlas, logs, prompts,
   Resource metadata, or artifacts.
3. **Execution is shell-free.** `uv`, `yt-dlp`, `ffmpeg`, and `whisper-cli` receive argument arrays
   through direct process execution. Source URLs and paths are never interpreted by a shell.
4. **ASR is bounded.** The default duration ceiling is 7200 seconds. Unknown duration is rejected
   instead of starting unbounded work.
5. **No misleading partial summaries.** Subtitle acquisition may join all parts as before, but
   local ASR explicitly rejects a multi-part video until every part can be transcribed.
6. **Raw media is ephemeral.** Audio, WAV, and whisper JSON live in one exclusive task temporary
   directory and are removed in a `finally` boundary. Atlas stores no raw-media ArtifactRef.
7. **Provenance is explicit.** Transcript Resource metadata distinguishes
   `platform_subtitle` from `local_asr`; ASR records engine, model, language, duration, and audio
   normalization. The summary records the transcript Resource and acquisition mode it consumed.
8. **Run output stays bounded.** Transcript/summary bytes remain external ArtifactRefs; Run output
   contains only source metadata, lengths, acquisition mode, and bounded ASR identifiers.
9. **Knowledge remains human-owned.** ASR and summary outputs are Resources. Nothing in this RFC
   writes human-authored comment prose or confirms semantic relations.
10. **Failure is visible and cheap to recover.** Configuration, duration, multipart, conversion,
    ASR, and empty-transcript failures have explicit codes. The user may fix the cause and enqueue
    a new Run; no durable local outbox or post-lease replay is added.

## Capability contract

Lumio replaces the capture command's execution target with:

```json
{
  "job_name": "bilibili-summary-v4",
  "capabilities_required": ["bilibili-summary-v4"]
}
```

The Atlas wire schema and `atlas-agent-v3` authentication/publication protocol do not change.
Capability routing already prevents an older subtitle-only Lumio from claiming v4 work. Existing
terminal v3 Runs and their Resources remain immutable; a failed v3 capture is rerun by explicitly
enqueueing a new v4 Run.

## Acquisition contract

### Platform subtitle path

Lumio attempts browser-cookie extraction but treats failure as an anonymous session. It fetches
bounded source metadata, invokes the existing WBI-signed subtitle script with an optional cookie
file, and reads a separate bounded status JSON containing only:

- BVID and cids;
- part count;
- requested and selected language codes;
- whether the request used a cookie file;
- `available` or `unavailable` status and character count.

An empty subtitle file is `unavailable`, not success. API failure also permits the local ASR path;
the subsequent download has its own explicit terminal diagnostics.

### Local ASR path

For one video item:

1. use Bilibili metadata duration, or ask `yt-dlp` for bounded metadata when it is missing;
2. reject unknown duration, duration above the configured ceiling, or a multi-part source;
3. download `bestaudio/best` with `--no-playlist` into an exclusive temporary directory;
4. reject any reported path outside that directory;
5. normalize through `ffmpeg` to `pcm_s16le`, 16000 Hz, mono WAV;
6. run multilingual whisper.cpp with JSON output and the requested/detected language;
7. join `transcription[].text`, reject empty or malformed output, and publish only the resulting
   transcript text;
8. recursively remove the exclusive temporary directory in all outcomes.

The first implementation uses whisper.cpp `small`, which is a deliberate local quality/cost
balance for the Mac. Moving ASR to AMAX, using faster-whisper/SenseVoice, diarization, or routing by
language requires measured need and a later capability version rather than hidden replacement.

## Failure policy

| Code | Meaning | Automatic retry |
| --- | --- | --- |
| `asr_not_configured` | model or required binary is missing | no |
| `multipart_asr_unsupported` | complete multi-part ASR is not implemented | no |
| `media_duration_unknown` | duration cannot be bounded | no |
| `media_too_long` | configured duration ceiling exceeded | no |
| `media_probe_failed` | remote metadata probe failed | yes, within normal Atlas attempt policy |
| `audio_download_failed` | remote audio acquisition failed | yes, within normal Atlas attempt policy |
| `audio_conversion_failed` | ffmpeg cannot normalize the acquired bytes | no |
| `asr_failed` | whisper process or JSON output failed | no |
| `empty_asr_transcript` | ASR completed without usable text | no |

Lease loss still aborts the current process pipeline and suppresses late publication under RFC
0002. This RFC does not add persisted credentials, durable result delivery, or reconciliation.

## Resource provenance

Platform transcript Resources use a deterministic generator named
`lumio-bilibili-platform-subtitle`. Local ASR transcript Resources use this complete AI-generator
provenance required by the Atlas publication schema:

```json
{
  "mode": "ai",
  "name": "whisper.cpp",
  "version": "1",
  "model_provider": "local",
  "model_id": "whisper.cpp/small",
  "prompt_version": "audio-transcription-v1"
}
```

Both paths record `acquisition_mode` and language. Local ASR additionally records:

```json
{
  "asr_engine": "whisper.cpp",
  "asr_model": "small",
  "duration_seconds": 1224.938,
  "audio_normalization": "pcm_s16le/16000Hz/mono",
  "retained_media": false
}
```

The summary Resource retains its model/provider/prompt provenance and adds the transcript Resource
ID, acquisition mode, and transcript language. Changing transcript bytes creates a new
content-derived Resource identity under the existing RFC 0003 rules.

## nix-config contract

The macsp Home Manager profile provides:

- official `yt-dlp` 2026.07.04, pinned for this host because the locked nixpkgs 2026.06.09 build
  receives HTTP 412 for the acceptance video;
- `whisper-cpp` (including `whisper-cli` and `whisper-cpp-download-ggml-model`);
- the already-provisioned `ffmpeg`;
- `BILIBILI_ASR_MODEL=~/Library/Caches/Lumio/asr/whisper/ggml-small.bin`;
- `BILIBILI_ASR_MAX_DURATION_SECONDS=7200`;
- a mode-0700 model-cache directory.

Model weights are rebuildable cache data and are not committed to Git, copied into Atlas, or
treated as Nix business state. The explicit one-time setup is:

```bash
whisper-cpp-download-ggml-model small "$HOME/Library/Caches/Lumio/asr/whisper"
```

## Scope

### Included

- subtitle-first automatic fallback for public single-part Bilibili videos;
- anonymous operation when browser cookies are unavailable;
- direct shell-free `yt-dlp`, `ffmpeg`, and whisper.cpp execution;
- duration, path, timeout, cancellation, cleanup, and bounded-output guards;
- transcript and summary provenance changes;
- focused Lumio decision/provenance/configuration tests;
- real no-subtitle-video ASR smoke verification;
- minimal macsp Nix provisioning.

### Excluded

- complete multi-part ASR;
- speaker diarization, chapter reconstruction, OCR, frame sampling, or multimodal video analysis;
- automatic ASR engine benchmarking or model selection;
- AMAX GPU ASR workers and cross-node artifact upload;
- retaining raw audio or exposing it in the Console;
- reprocessing every historical v3 Resource;
- daily video queues or generic media ingestion;
- any AI-authored Knowledge Comment.

## Acceptance criteria

RFC 0005 is complete only when all of the following pass:

1. A usable platform subtitle prevents audio download and ASR.
2. A public video can continue anonymously when cookie extraction fails.
3. No subtitle activates local ASR and publishes a non-empty transcript plus AI summary through
   `bilibili-summary-v4`.
4. Missing model/binary, excessive or unknown duration, multipart input, conversion failure,
   invalid JSON, and empty ASR each produce explicit bounded failures.
5. URLs and paths reach every child process only as argument-array elements.
6. Cancellation terminates active work; success and failure leave no task media directory.
7. Transcript and summary Resource metadata contain the specified provenance, while Run output and
   Atlas SQLite contain no transcript, summary, cookie, audio, WAV, or model bytes.
8. Existing v3 Source/Resource publication, Vortex projection, review, comment, and lease tests
   remain green.
9. Lumio checks, nix evaluation, and the affected Darwin build pass.
10. `BV1NG9xBUEju`, which has no platform subtitle, produces a non-empty Chinese local-ASR
    transcript in a real smoke test and leaves no temporary media directory.

## Rollback

Rollback restores the prior Lumio revision and nix generation. v4 Runs remain ordinary Atlas Runs
but cannot be claimed without a v4-capable agent. Existing v3 and v4 Sources/Resources remain
valid under the unchanged v3 publication schema. The model cache may be deleted independently.

## Verification record

Implemented and verified on 2026-07-16:

- **Atlas:** base revision `f6a8ed8`; protocol remains `atlas-agent-v3`; 135 tests passed and Ruff
  passed. This RFC changes no Atlas runtime schema or endpoint.
- **Lumio:** `3c009b8` implemented the v4 acquisition path; `b4b5c8f` added the complete Atlas AI
  provenance contract found by the real publication test. `npm run check` passed 40 tests, Pi
  compatibility 0.80.6, and full extension bundling.
- **nix-config:** `b6c19e8`; `nix eval .#evalTests` returned true and the full
  `darwinConfigurations.macsp.system` build passed. The official yt-dlp 2026.07.04 derivation
  successfully probed the acceptance video. Interactive `darwin-rebuild switch` remains a normal
  user activation step because it requires sudo/Touch ID; it is not an implementation failure.
- **Model:** official multilingual `ggml-small.bin`, 487,601,967 bytes,
  `sha256:1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b`, stored in the
  rebuildable Lumio cache.
- **Local smoke:** `BV1NG9xBUEju` had no platform subtitle, completed local ASR through the final
  Nix yt-dlp/ffmpeg/whisper.cpp binaries, produced a 7,526-character Chinese transcript, and left
  no `lumio-bili-asr-*` task directory.
- **Production E2E:** Run `run_c8355fa656904897b5f9f5e84596b62c` completed on attempt 1. Atlas
  stored a bounded 1,480-byte Run output, a 17,321-byte transcript ArtifactRef, a 5,353-byte
  summary ArtifactRef, and two pending Resources. The transcript generator is
  `local / whisper.cpp/small / audio-transcription-v1`; the summary generator is
  `deepseek / deepseek-v4-pro / bilibili-summary-v1`. Both artifact checksums matched the Mac
  files, and Vortex projected Resource Card `res_2dff064492ee5ecb6fdec84316b5a229` without writing
  human Knowledge.
- **Contract discovery:** pre-fix Run `run_224e95daca4b4ae2904b56e5ef694c0d` proved that Atlas
  correctly rejects incomplete AI provenance with HTTP 422. The Lumio fixture had mirrored the
  incomplete generator and therefore missed the cross-repository constraint; the regression test
  now asserts all three required AI provenance fields.
