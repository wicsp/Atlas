export type ReviewStatus = "pending" | "reviewed" | "dismissed";
export type RunStatus =
  | "pending"
  | "claimed"
  | "completed"
  | "failed"
  | "cancelled";

export interface SourceRecord {
  source_id: string;
  source_key: string;
  kind: "video" | "paper" | "webpage" | "dataset" | "code" | "other";
  canonical_uri: string;
  title: string | null;
  external_ids: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ResourceGenerator {
  mode: "deterministic" | "ai";
  name: string;
  version: string;
  model_provider: string | null;
  model_id: string | null;
  prompt_version: string | null;
}

export interface ResourceRecord {
  resource_id: string;
  source_id: string;
  produced_by_run_id: string;
  artifact_id: string;
  kind: "transcript" | "summary" | "extraction" | "comparison";
  title: string;
  content_hash: string;
  generator: ResourceGenerator;
  metadata: Record<string, unknown>;
  review_status: ReviewStatus;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeRefRecord {
  knowledge_ref_id: string;
  note_id: string;
  uri: string;
  source_ids: string[];
  resource_ids: string[];
  revision_of: string | null;
  created_at: string;
  updated_at: string;
}

export interface RunRecord {
  run_id: string;
  project_id: string;
  job_name: string;
  capabilities_required: string[];
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  status: RunStatus;
  agent_id: string | null;
  lease_expires_at: string | null;
  attempt_number: number;
  max_attempts: number;
  priority: number;
  metadata: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ReviewGroup {
  source: SourceRecord | null;
  sourceId: string;
  resources: ResourceRecord[];
  newestAt: string;
}

function newestFirst<T extends { created_at: string }>(
  left: T,
  right: T,
  leftId: string,
  rightId: string,
): number {
  const byTime = right.created_at.localeCompare(left.created_at);
  return byTime || rightId.localeCompare(leftId);
}

export function groupResourcesBySource(
  sources: SourceRecord[],
  resources: ResourceRecord[],
): ReviewGroup[] {
  const sourceById = new Map(sources.map((source) => [source.source_id, source]));
  const resourcesBySource = new Map<string, ResourceRecord[]>();

  for (const resource of resources) {
    const bucket = resourcesBySource.get(resource.source_id) ?? [];
    bucket.push(resource);
    resourcesBySource.set(resource.source_id, bucket);
  }

  return [...resourcesBySource.entries()]
    .map(([sourceId, versions]) => {
      const ordered = [...versions].sort((left, right) =>
        newestFirst(left, right, left.resource_id, right.resource_id),
      );
      return {
        source: sourceById.get(sourceId) ?? null,
        sourceId,
        resources: ordered,
        newestAt: ordered[0]?.created_at ?? "",
      };
    })
    .sort(
      (left, right) =>
        right.newestAt.localeCompare(left.newestAt) ||
        right.sourceId.localeCompare(left.sourceId),
    );
}

export function latestCommentRunsByResource(
  runs: RunRecord[],
): Record<string, RunRecord> {
  const latest: Record<string, RunRecord> = {};
  const ordered = [...runs].sort((left, right) =>
    newestFirst(left, right, left.run_id, right.run_id),
  );

  for (const run of ordered) {
    if (run.job_name !== "vortex-comment-v1") continue;
    const resourceId = run.input.resource_id;
    if (typeof resourceId === "string" && !latest[resourceId]) {
      latest[resourceId] = run;
    }
  }
  return latest;
}

export function isActiveRun(run: RunRecord | undefined): boolean {
  return run?.status === "pending" || run?.status === "claimed";
}
