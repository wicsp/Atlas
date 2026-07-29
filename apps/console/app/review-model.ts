export type ReviewStatus = "pending" | "reviewed" | "dismissed";
export type RunStatus =
  | "blocked"
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

export interface ArtifactRef {
  artifact_id: string;
  run_id: string;
  name: string;
  uri: string;
  content_type: string | null;
  size_bytes: number | null;
  checksum: string | null;
  created_at: string;
}

export interface ResourceDocument {
  resource: ResourceRecord;
  source: SourceRecord;
  artifact: ArtifactRef;
  content: string;
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

export interface CommentRecord {
  comment_id: string;
  knowledge_ref_id: string;
  note_id: string;
  source_ids: string[];
  resource_ids: string[];
  body_markdown: string;
  content_hash: string;
  format: "text/markdown";
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
  workflow: {
    name: string;
    version: string;
    digest: string;
  } | null;
  step_name: string | null;
  workflow_invocation_id: string | null;
  depends_on_run_ids: string[];
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface RunnerRecord {
  runner_id: string;
  name: string | null;
  node: { node_id: string; labels: string[] };
  last_seen_at: string;
  online: boolean;
}

export interface ReviewGroup {
  source: SourceRecord | null;
  sourceId: string;
  resources: ResourceRecord[];
  newestAt: string;
}

export function resourceProfileId(resource: ResourceRecord): string {
  const declared = resource.metadata.profile_id;
  if (typeof declared === "string" && declared.trim()) return declared.trim();
  const generator = resource.generator;
  return [
    resource.kind,
    generator.name,
    generator.version,
    generator.model_provider ?? "deterministic",
    generator.model_id ?? "deterministic",
    generator.prompt_version ?? "deterministic",
  ].join(":");
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
  knowledgeRefs: KnowledgeRefRecord[] = [],
): ReviewGroup[] {
  const sourceById = new Map(sources.map((source) => [source.source_id, source]));
  const resourcesBySource = new Map<string, ResourceRecord[]>();
  const referenced = new Set(knowledgeRefs.flatMap((reference) => reference.resource_ids));
  const currentBySlot = new Map<string, ResourceRecord>();

  for (const resource of resources) {
    const slot = `${resource.source_id}\0${resourceProfileId(resource)}`;
    const current = currentBySlot.get(slot);
    if (!current || newestFirst(resource, current, resource.resource_id, current.resource_id) < 0) {
      currentBySlot.set(slot, resource);
    }
  }

  for (const resource of resources) {
    const slot = `${resource.source_id}\0${resourceProfileId(resource)}`;
    if (currentBySlot.get(slot)?.resource_id !== resource.resource_id && !referenced.has(resource.resource_id)) {
      continue;
    }
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
    if (!["vortex-comment-v1", "vortex-comment-sync-v1"].includes(run.job_name)) continue;
    const resourceId = run.input.resource_id;
    if (typeof resourceId === "string" && !latest[resourceId]) {
      latest[resourceId] = run;
    }
  }
  return latest;
}

export function isActiveRun(run: RunRecord | undefined): boolean {
  return (
    run?.status === "blocked"
    || run?.status === "pending"
    || run?.status === "claimed"
  );
}

export function isPaperPreview(resource: ResourceRecord): boolean {
  return (
    resource.kind === "summary"
    && resource.metadata.profile_id === "paper-preview-v1"
    && (resource.metadata.basis === "abstract" || resource.metadata.basis === "pdf-leading")
  );
}

export function paperFulltextForPreview(
  resources: ResourceRecord[],
  preview: ResourceRecord,
): ResourceRecord | undefined {
  return resources.find((resource) =>
    resource.source_id === preview.source_id
    && resource.kind === "summary"
    && resource.metadata.profile_id === "paper-fulltext-v1"
    && resource.metadata.source_preview_resource_id === preview.resource_id
  );
}

export function paperFulltextRunForPreview(
  runs: RunRecord[],
  previewResourceId: string,
): RunRecord | undefined {
  return runs.find((run) => {
    const workflowInput = run.input.workflow_input;
    return (
      run.workflow?.name === "paper.fulltext"
      && run.step_name === "summarize"
      && typeof workflowInput === "object"
      && workflowInput !== null
      && "preview_resource_id" in workflowInput
      && workflowInput.preview_resource_id === previewResourceId
    );
  });
}

function isVortexCommentUri(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const uri = new URL(value);
    const file = uri.searchParams.get("file");
    return (
      uri.protocol === "obsidian:" &&
      uri.hostname === "open" &&
      uri.searchParams.get("vault") === "Vortex" &&
      file !== null &&
      file.startsWith("Knowledge/Comments/")
    );
  } catch {
    return false;
  }
}

/**
 * Return only the bounded Vortex deep link created by the comment workflow.
 * KnowledgeRef is authoritative; completed Run output is a same-refresh fallback.
 */
export function commentNoteUri(
  run: RunRecord | undefined,
  knowledgeRef: KnowledgeRefRecord | undefined,
): string | null {
  if (isVortexCommentUri(knowledgeRef?.uri)) return knowledgeRef.uri;
  const runUri = run?.status === "completed" ? run.output?.note_uri : null;
  return isVortexCommentUri(runUri) ? runUri : null;
}
