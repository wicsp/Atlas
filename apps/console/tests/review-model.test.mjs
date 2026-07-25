import assert from "node:assert/strict";
import test from "node:test";

import {
  commentNoteUri,
  groupResourcesBySource,
  isActiveRun,
  latestCommentRunsByResource,
  paperAcceptRunForPreview,
  paperFulltextForPreview,
} from "../app/review-model.ts";

const source = {
  source_id: "src_one",
  source_key: "bilibili:BV1",
  kind: "video",
  canonical_uri: "https://example.com/video",
  title: "One source",
  external_ids: { bvid: "BV1" },
  metadata: {},
  created_at: "2026-07-15T10:00:00Z",
  updated_at: "2026-07-15T10:00:00Z",
};

function resource(id, sourceId, createdAt, status = "pending") {
  return {
    resource_id: id,
    source_id: sourceId,
    produced_by_run_id: "run_producer",
    artifact_id: `artifact_${id}`,
    kind: "summary",
    title: id,
    content_hash: `sha256:${"a".repeat(64)}`,
    generator: {
      mode: "ai",
      name: "test",
      version: "1",
      model_provider: "openai",
      model_id: "test-model",
      prompt_version: "v1",
    },
    metadata: {},
    review_status: status,
    created_at: createdAt,
    updated_at: createdAt,
  };
}

function run(id, resourceId, createdAt, status) {
  return {
    run_id: id,
    project_id: "resource-review",
    job_name: "vortex-comment-v1",
    capabilities_required: ["vortex-comment-v1"],
    input: { resource_id: resourceId },
    output: null,
    status,
    agent_id: null,
    lease_expires_at: null,
    attempt_number: 0,
    max_attempts: 3,
    priority: 0,
    metadata: {},
    error_message: null,
    created_at: createdAt,
    started_at: null,
    completed_at: null,
  };
}

test("shows one current Resource per generation profile", () => {
  const older = resource("res_older000", source.source_id, "2026-07-15T11:00:00Z");
  const newer = resource("res_newer000", source.source_id, "2026-07-16T11:00:00Z");
  const orphan = resource("res_orphan00", "src_missing", "2026-07-17T11:00:00Z");

  const groups = groupResourcesBySource([source], [older, orphan, newer]);

  assert.deepEqual(groups.map((group) => group.sourceId), ["src_missing", "src_one"]);
  assert.equal(groups[0].source, null);
  assert.deepEqual(groups[1].resources.map((item) => item.resource_id), ["res_newer000"]);
});

test("keeps referenced history and parallel declared analysis profiles", () => {
  const older = resource("res_older000", source.source_id, "2026-07-15T11:00:00Z");
  const newer = resource("res_newer000", source.source_id, "2026-07-16T11:00:00Z");
  const analysis = {
    ...resource("res_analysis0", source.source_id, "2026-07-16T12:00:00Z"),
    metadata: { profile_id: "argument-map-v1" },
  };
  const knowledgeRef = {
    knowledge_ref_id: "kref_old",
    note_id: "Knowledge/Comments/res_older000",
    uri: "obsidian://open?vault=Vortex&file=Knowledge%2FComments%2Fres_older000",
    source_ids: [source.source_id],
    resource_ids: [older.resource_id],
    revision_of: null,
    created_at: "2026-07-17T11:00:00Z",
    updated_at: "2026-07-17T11:00:00Z",
  };

  const groups = groupResourcesBySource([source], [older, newer, analysis], [knowledgeRef]);
  assert.deepEqual(
    groups[0].resources.map((item) => item.resource_id),
    ["res_analysis0", "res_newer000", "res_older000"],
  );
});

test("tracks only the newest comment run for each Resource", () => {
  const pending = run("run_old", "res_one000", "2026-07-15T11:00:00Z", "pending");
  const claimed = {
    ...run("run_new", "res_one000", "2026-07-16T11:00:00Z", "claimed"),
    job_name: "vortex-comment-sync-v1",
    capabilities_required: ["vortex-comment-sync-v1"],
  };
  const unrelated = { ...pending, run_id: "run_other", job_name: "other-job" };

  const latest = latestCommentRunsByResource([pending, unrelated, claimed]);

  assert.equal(latest.res_one000.run_id, "run_new");
  assert.equal(isActiveRun(latest.res_one000), true);
  assert.equal(isActiveRun({ ...claimed, status: "completed" }), false);
});

test("links a paper preview to its full-text Resource and workflow", () => {
  const preview = {
    ...resource("res_preview", source.source_id, "2026-07-20T11:00:00Z"),
    metadata: { profile_id: "paper-preview-v1", basis: "abstract" },
  };
  const fulltext = {
    ...resource("res_fulltext", source.source_id, "2026-07-21T11:00:00Z"),
    metadata: {
      profile_id: "paper-fulltext-v1",
      basis: "pdf-text",
      source_preview_resource_id: preview.resource_id,
    },
  };
  const summaryRun = {
    ...run("run_summary", preview.resource_id, "2026-07-21T10:00:00Z", "blocked"),
    project_id: "paper-library",
    input: { workflow_input: { preview_resource_id: preview.resource_id } },
    workflow: { name: "paper.accept", version: "1", digest: "sha256:test" },
    step_name: "summarize",
  };

  assert.equal(
    paperFulltextForPreview([preview, fulltext], preview)?.resource_id,
    fulltext.resource_id,
  );
  assert.equal(
    paperAcceptRunForPreview([summaryRun], preview.resource_id)?.run_id,
    summaryRun.run_id,
  );
  assert.equal(isActiveRun(summaryRun), true);
});

test("returns only a completed Vortex Knowledge Comment deep link", () => {
  const validUri =
    "obsidian://open?vault=Vortex&file=Knowledge%2FComments%2F2026-07-17-res_one000";
  const completed = {
    ...run("run_done", "res_one000", "2026-07-17T11:00:00Z", "completed"),
    output: { note_uri: validUri },
  };
  const knowledgeRef = {
    knowledge_ref_id: "kref_one",
    note_id: "Knowledge/Comments/2026-07-17-res_one000",
    uri: validUri,
    source_ids: [source.source_id],
    resource_ids: ["res_one000"],
    revision_of: null,
    created_at: "2026-07-17T11:00:00Z",
    updated_at: "2026-07-17T11:00:00Z",
  };

  assert.equal(commentNoteUri(completed, knowledgeRef), validUri);
  assert.equal(commentNoteUri(completed, undefined), validUri);
  assert.equal(
    commentNoteUri({ ...completed, status: "claimed" }, undefined),
    null,
  );
  assert.equal(
    commentNoteUri(
      { ...completed, output: { note_uri: "https://example.com/not-obsidian" } },
      undefined,
    ),
    null,
  );
  assert.equal(
    commentNoteUri(
      completed,
      { ...knowledgeRef, uri: "obsidian://open?vault=Vortex&file=Resources%2FCards%2Fres_one000" },
    ),
    validUri,
  );
});
