import assert from "node:assert/strict";
import test from "node:test";

import {
  groupResourcesBySource,
  isActiveRun,
  latestCommentRunsByResource,
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

test("groups every version by Source and orders newest first", () => {
  const older = resource("res_older000", source.source_id, "2026-07-15T11:00:00Z");
  const newer = resource("res_newer000", source.source_id, "2026-07-16T11:00:00Z");
  const orphan = resource("res_orphan00", "src_missing", "2026-07-17T11:00:00Z");

  const groups = groupResourcesBySource([source], [older, orphan, newer]);

  assert.deepEqual(groups.map((group) => group.sourceId), ["src_missing", "src_one"]);
  assert.equal(groups[0].source, null);
  assert.deepEqual(
    groups[1].resources.map((item) => item.resource_id),
    ["res_newer000", "res_older000"],
  );
});

test("tracks only the newest comment run for each Resource", () => {
  const pending = run("run_old", "res_one000", "2026-07-15T11:00:00Z", "pending");
  const claimed = run("run_new", "res_one000", "2026-07-16T11:00:00Z", "claimed");
  const unrelated = { ...pending, run_id: "run_other", job_name: "other-job" };

  const latest = latestCommentRunsByResource([pending, unrelated, claimed]);

  assert.equal(latest.res_one000.run_id, "run_new");
  assert.equal(isActiveRun(latest.res_one000), true);
  assert.equal(isActiveRun({ ...claimed, status: "completed" }), false);
});
