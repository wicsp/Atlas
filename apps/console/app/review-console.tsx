"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { usePictureInPictureComment } from "./use-pip-comment";
import {
  groupResourcesBySource,
  isActiveRun,
  isPaperPreview,
  latestCommentRunsByResource,
  paperFulltextRunForPreview,
  paperFulltextForPreview,
  type CommentRecord,
  type KnowledgeRefRecord,
  type ResourceDocument,
  type ResourceRecord,
  type ReviewStatus,
  type RunRecord,
  type SourceRecord,
} from "./review-model";

type AuthState = "checking" | "anonymous" | "authenticated";
type Filter = ReviewStatus | "all";
type FeedbackTone = "progress" | "success" | "error" | "info";
const ACTIVE_RUN_POLL_INTERVAL_MS = 1_000;

interface Feedback {
  tone: FeedbackTone;
  message: string;
  runId?: string;
}

interface WorkRequestResponse {
  run: RunRecord;
  reused: boolean;
}

interface ResourceIgnoreResponse {
  resource: ResourceRecord;
  evicted_resource_ids: string[];
  cleanup_runs: RunRecord[];
}

interface WorkflowInvocation {
  invocation_id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  step_runs: Record<string, string>;
}

interface PaperFulltextResponse {
  invocation: WorkflowInvocation | null;
  reused: boolean;
  fulltext_resource: ResourceRecord | null;
}

interface CommentCompleteResponse {
  resource: ResourceRecord;
  knowledge_ref: KnowledgeRefRecord;
  comment: CommentRecord;
}

class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, {
    ...init,
    headers,
    credentials: "include",
  });
  const text = await response.text();
  const payload = text ? (JSON.parse(text) as unknown) : null;
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && "detail" in payload
        ? String(payload.detail)
        : `Atlas returned ${response.status}`;
    throw new ApiError(response.status, detail);
  }
  return payload as T;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function shortId(value: string): string {
  return value.length > 22 ? `${value.slice(0, 11)}…${value.slice(-7)}` : value;
}

function sourceKindLabel(kind: SourceRecord["kind"] | undefined): string {
  return (
    {
      video: "视频",
      paper: "论文",
      webpage: "网页",
      dataset: "数据集",
      code: "代码",
      other: "来源",
    } as const
  )[kind ?? "other"];
}

function statusLabel(status: ReviewStatus): string {
  return { pending: "待判断", reviewed: "已评论", dismissed: "已忽略" }[status];
}

function runLabel(run: RunRecord): string {
  if (run.job_name === "vortex-comment-sync-v1") {
    return {
      pending: "等待同步评论",
      claimed: "正在同步评论",
      blocked: "等待前置步骤",
      completed: "评论已同步",
      failed: "评论同步失败",
      cancelled: "同步已取消",
    }[run.status];
  }
  return {
    blocked: "等待前置步骤",
    pending: "等待 Mac Lumio",
    claimed: "正在创建评论",
    completed: "评论已创建",
    failed: "评论创建失败",
    cancelled: "请求已取消",
  }[run.status];
}

function paperRunMessage(run: RunRecord): string {
  if (run.status === "completed") return "PDF 全文总结已生成。";
  if (run.status === "failed" || run.status === "cancelled") {
    return run.error_message || "论文全文处理失败。";
  }
  if (run.status === "claimed") {
    return "PDF 已就绪；正在根据全文生成总结…";
  }
  return "正在等待 Zotero 导入条目、下载并索引 PDF…";
}

function paperProfileLabel(resource: ResourceRecord): string | null {
  if (resource.metadata.profile_id === "paper-preview-v1") return "摘要预览";
  if (resource.metadata.profile_id === "paper-fulltext-v1") return "PDF 全文";
  return null;
}

function generatorLabel(resource: ResourceRecord): string {
  const generator = resource.generator;
  if (generator.mode === "ai") {
    return [generator.model_provider, generator.model_id].filter(Boolean).join(" / ");
  }
  return `${generator.name} v${generator.version}`;
}

function externalIdentity(source: SourceRecord | null): string | null {
  if (!source) return null;
  for (const [key, value] of Object.entries(source.external_ids)) {
    if (typeof value === "string" || typeof value === "number") {
      return `${key.toUpperCase()} ${value}`;
    }
  }
  return null;
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return "发生了未知错误";
}

export function ReviewConsole() {
  const [auth, setAuth] = useState<AuthState>("checking");
  const [password, setPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState("");
  const [atlasVersion, setAtlasVersion] = useState<string | null>(null);
  const [sources, setSources] = useState<SourceRecord[]>([]);
  const [resources, setResources] = useState<ResourceRecord[]>([]);
  const [comparisons, setComparisons] = useState<ResourceRecord[]>([]);
  const [knowledgeRefs, setKnowledgeRefs] = useState<KnowledgeRefRecord[]>([]);
  const [comments, setComments] = useState<CommentRecord[]>([]);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [filter, setFilter] = useState<Filter>("pending");
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [busyResources, setBusyResources] = useState<Set<string>>(new Set());
  const [feedback, setFeedback] = useState<Record<string, Feedback>>({});
  const [openResourceId, setOpenResourceId] = useState<string | null>(null);
  const [documents, setDocuments] = useState<Record<string, ResourceDocument>>({});
  const [documentErrors, setDocumentErrors] = useState<Record<string, string>>({});
  const [loadingDocuments, setLoadingDocuments] = useState<Set<string>>(new Set());
  const [commentDrafts, setCommentDrafts] = useState<Record<string, string>>({});
  const { openPip, pip, closePip } = usePictureInPictureComment();
  const saveCommentRef = useRef<(resourceId: string, body?: string) => Promise<void>>(async () => {});

  const loadReviewData = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    setLoadError("");
    try {
      const [
        nextSources,
        nextResources,
        nextComparisons,
        nextKnowledgeRefs,
        nextComments,
        reviewRuns,
        paperRuns,
      ] =
        await Promise.all([
          api<SourceRecord[]>("/api/sources?limit=500"),
          api<ResourceRecord[]>("/api/resources?kind=summary&limit=500"),
          api<ResourceRecord[]>("/api/resources?kind=comparison&limit=500"),
          api<KnowledgeRefRecord[]>("/api/knowledge-refs?limit=500"),
          api<CommentRecord[]>("/api/comments?limit=500"),
          api<RunRecord[]>("/api/runs?project_id=resource-review&limit=500"),
          api<RunRecord[]>("/api/runs?project_id=paper-library&limit=500"),
        ]);
      const nextRuns = [...reviewRuns, ...paperRuns];
      setSources(nextSources);
      setResources(nextResources);
      setComparisons(nextComparisons);
      setKnowledgeRefs(nextKnowledgeRefs);
      setComments(nextComments);
      setRuns(nextRuns);
      setLastUpdated(new Date());

      const latest = latestCommentRunsByResource(nextRuns);
      setFeedback((current) => {
        const updated = { ...current };
        for (const [resourceId, entry] of Object.entries(current)) {
          if (!entry.runId) continue;
          const run = nextRuns.find((candidate) => candidate.run_id === entry.runId)
            ?? latest[resourceId];
          if (!run || run.run_id !== entry.runId) continue;
          if (run.workflow?.name === "paper.fulltext" || run.workflow?.name === "paper.ingest") {
            updated[resourceId] = {
              tone:
                run.status === "completed"
                  ? "success"
                  : run.status === "failed" || run.status === "cancelled"
                    ? "error"
                    : "progress",
              message: paperRunMessage(run),
              runId: run.run_id,
            };
            continue;
          }
          const comparison = run.job_name === "vortex-comparison-v1";
          const commentSync = run.job_name === "vortex-comment-sync-v1";
          if (run.status === "pending") {
            updated[resourceId] = {
              tone: "progress",
              message: comparison
                ? "正在等待在线的 Mac Lumio 领取候选关系检查…"
                : commentSync
                  ? "正在等待在线的 Mac Lumio 读取并同步本地评论…"
                : "正在等待在线的 Mac Lumio 领取评论任务…",
              runId: run.run_id,
            };
          } else if (run.status === "claimed") {
            updated[resourceId] = {
              tone: "progress",
              message: comparison
                ? "Lumio 已领取；正在比较 Resource 与已写评论…"
                : commentSync
                  ? "Lumio 已领取；正在校验并上传本地 Markdown…"
                : "Lumio 已领取；正在创建空白评论并登记引用…",
              runId: run.run_id,
            };
          } else {
            updated[resourceId] = {
              tone: run.status === "completed" ? "success" : "error",
              message:
                run.status === "completed"
                  ? comparison
                    ? "观点对比已生成；可直接点击“查看对比”。"
                    : commentSync
                      ? "评论正文已同步到 Atlas，Resource 已标记为已评论。"
                    : "空白评论已创建；可通过“已有你的评论”重新打开。"
                  : run.error_message || runLabel(run),
              runId: run.run_id,
            };
          }
        }
        return updated;
      });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setAuth("anonymous");
      } else {
        setLoadError(errorMessage(error));
      }
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    async function initialize() {
      try {
        const health = await api<{ status: string; version: string }>("/api/health");
        if (active) setAtlasVersion(health.version);
      } catch {
        if (active) setLoadError("无法连接 Atlas。请确认 AMAX 与 Tailscale 服务在线。");
      }

      try {
        const session = await api<{ authenticated: boolean }>("/api/auth/me");
        if (!active) return;
        if (session.authenticated) {
          setAuth("authenticated");
          await loadReviewData();
        } else {
          setAuth("anonymous");
        }
      } catch {
        if (active) setAuth("anonymous");
      }
    }
    void initialize();
    return () => {
      active = false;
    };
  }, [loadReviewData]);

  const latestRuns = useMemo(() => latestCommentRunsByResource(runs), [runs]);
  const hasActiveRuns = runs.some(isActiveRun);

  useEffect(() => {
    if (auth !== "authenticated" || !hasActiveRuns) return;
    const interval = window.setInterval(() => {
      void loadReviewData(true);
    }, ACTIVE_RUN_POLL_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [auth, hasActiveRuns, loadReviewData]);

  // BroadcastChannel listener for PiP comment window messages
  useEffect(() => {
    const channel = new BroadcastChannel("atlas-pip-comment");
    const handler = (event: MessageEvent) => {
      const { type, resourceId, text } = event.data ?? {};
      if (!resourceId) return;
      if (type === "draft") {
        setCommentDrafts((current) => ({ ...current, [resourceId]: text }));
      } else if (type === "save") {
        setCommentDrafts((current) => ({ ...current, [resourceId]: text }));
        saveCommentRef.current(resourceId, text).then(
          () => channel.postMessage({ type: "saved", resourceId }),
          (error: unknown) =>
            channel.postMessage({
              type: "save-error",
              resourceId,
              message: errorMessage(error),
            }),
        );
      }
    };
    channel.addEventListener("message", handler);
    return () => {
      channel.removeEventListener("message", handler);
      channel.close();
    };
  }, []);

  const knowledgeByResource = useMemo(() => {
    const index = new Map<string, KnowledgeRefRecord>();
    for (const reference of knowledgeRefs) {
      for (const resourceId of reference.resource_ids) {
        if (!index.has(resourceId)) index.set(resourceId, reference);
      }
    }
    return index;
  }, [knowledgeRefs]);

  const commentByResource = useMemo(() => {
    const index = new Map<string, CommentRecord>();
    for (const comment of comments) {
      for (const resourceId of comment.resource_ids) {
        if (!index.has(resourceId)) index.set(resourceId, comment);
      }
    }
    return index;
  }, [comments]);

  const comparisonByResource = useMemo(() => {
    const index = new Map<string, ResourceRecord>();
    for (const comparison of [...comparisons].sort((left, right) =>
      right.created_at.localeCompare(left.created_at)
      || right.resource_id.localeCompare(left.resource_id)
    )) {
      const comparedResourceId = comparison.metadata.compared_resource_id;
      if (typeof comparedResourceId === "string" && !index.has(comparedResourceId)) {
        index.set(comparedResourceId, comparison);
      }
    }
    return index;
  }, [comparisons]);

  const groups = useMemo(
    () => groupResourcesBySource(sources, resources, knowledgeRefs),
    [knowledgeRefs, sources, resources],
  );
  const visibleGroups = useMemo(
    () =>
      filter === "all"
        ? groups
        : groups.filter((group) =>
            group.resources.some((resource) => resource.review_status === filter),
          ),
    [filter, groups],
  );
  const counts = useMemo(
    () => ({
      pending: resources.filter((item) => item.review_status === "pending").length,
      reviewed: resources.filter((item) => item.review_status === "reviewed").length,
      dismissed: resources.filter((item) => item.review_status === "dismissed").length,
      all: resources.length,
    }),
    [resources],
  );

  async function handleLogin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoginBusy(true);
    setLoginError("");
    try {
      await api<{ authenticated: boolean }>("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      setPassword("");
      setAuth("authenticated");
      await loadReviewData();
    } catch (error) {
      setLoginError(errorMessage(error));
    } finally {
      setLoginBusy(false);
    }
  }

  async function handleLogout() {
    await api<{ authenticated: boolean }>("/api/auth/logout", { method: "POST" });
    setAuth("anonymous");
    setSources([]);
    setResources([]);
    setComparisons([]);
    setKnowledgeRefs([]);
    setComments([]);
    setRuns([]);
  }

  function setResourceBusy(resourceId: string, value: boolean) {
    setBusyResources((current) => {
      const next = new Set(current);
      if (value) next.add(resourceId);
      else next.delete(resourceId);
      return next;
    });
  }

  async function changeReviewStatus(
    resourceId: string,
    status: "dismissed" | "pending",
  ) {
    setResourceBusy(resourceId, true);
    setFeedback((current) => ({
      ...current,
      [resourceId]: {
        tone: "progress",
        message: status === "dismissed" ? "正在忽略…" : "正在恢复…",
      },
    }));
    try {
      const result = await api<ResourceIgnoreResponse>(
        status === "dismissed"
          ? "/api/review-actions/ignore-resource"
          : "/api/review-actions/restore-resource",
        {
          method: "POST",
          body: JSON.stringify({ resource_id: resourceId }),
        },
      );
      const evicted = new Set(result.evicted_resource_ids);
      setResources((current) =>
        current
          .filter((resource) => !evicted.has(resource.resource_id))
          .map((resource) =>
            resource.resource_id === resourceId ? result.resource : resource,
          ),
      );
      if (result.cleanup_runs.length > 0) {
        const cleanupIds = new Set(result.cleanup_runs.map((run) => run.run_id));
        setRuns((current) => [
          ...result.cleanup_runs,
          ...current.filter((run) => !cleanupIds.has(run.run_id)),
        ]);
      }
      setFeedback((current) => ({
        ...current,
        [resourceId]: {
          tone: "success",
          message:
            status === "dismissed"
              ? result.evicted_resource_ids.length > 0
                ? `已忽略；回收站保持 10 项，最旧的 ${result.evicted_resource_ids.length} 项已永久清理。`
                : "已移入忽略列表；最近 10 项内可随时撤销。"
              : `已撤销忽略，恢复为「${statusLabel(result.resource.review_status)}」。`,
        },
      }));
    } catch (error) {
      setFeedback((current) => ({
        ...current,
        [resourceId]: { tone: "error", message: errorMessage(error) },
      }));
    } finally {
      setResourceBusy(resourceId, false);
    }
  }

  async function openResource(
    resource: ResourceRecord,
    existingComment?: CommentRecord,
  ) {
    const resourceId = resource.resource_id;
    if (openResourceId === resourceId) {
      setOpenResourceId(null);
      return;
    }
    setOpenResourceId(resourceId);
    setCommentDrafts((current) => ({
      ...current,
      [resourceId]: current[resourceId] ?? existingComment?.body_markdown ?? "",
    }));
    if (documents[resourceId] || loadingDocuments.has(resourceId)) return;
    setLoadingDocuments((current) => new Set(current).add(resourceId));
    setDocumentErrors((current) => ({ ...current, [resourceId]: "" }));
    try {
      const document = await api<ResourceDocument>(
        `/api/resources/${encodeURIComponent(resourceId)}/content`,
      );
      setDocuments((current) => ({ ...current, [resourceId]: document }));
    } catch (error) {
      setDocumentErrors((current) => ({
        ...current,
        [resourceId]: errorMessage(error),
      }));
    } finally {
      setLoadingDocuments((current) => {
        const next = new Set(current);
        next.delete(resourceId);
        return next;
      });
    }
  }

  async function saveComment(resourceId: string, bodyOverride?: string) {
    const body = bodyOverride ?? commentDrafts[resourceId] ?? "";
    if (!body.trim()) {
      setFeedback((current) => ({
        ...current,
        [resourceId]: { tone: "error", message: "评论不能为空。" },
      }));
      return;
    }
    setResourceBusy(resourceId, true);
    setFeedback((current) => ({
      ...current,
      [resourceId]: { tone: "progress", message: "正在保存评论到 Atlas…" },
    }));
    try {
      const result = await api<CommentCompleteResponse>(
        "/api/review-actions/complete-comment",
        {
          method: "POST",
          body: JSON.stringify({
            resource_id: resourceId,
            body_markdown: body,
          }),
        },
      );
      setResources((current) => current.map((resource) =>
        resource.resource_id === resourceId ? result.resource : resource
      ));
      setKnowledgeRefs((current) => [
        result.knowledge_ref,
        ...current.filter((item) => item.knowledge_ref_id !== result.knowledge_ref.knowledge_ref_id),
      ]);
      setComments((current) => [
        result.comment,
        ...current.filter((item) => item.comment_id !== result.comment.comment_id),
      ]);
      setFeedback((current) => ({
        ...current,
        [resourceId]: {
          tone: "success",
          message: "评论已保存到 Atlas，Resource 已标记为已评论。",
        },
      }));
    } catch (error) {
      setFeedback((current) => ({
        ...current,
        [resourceId]: { tone: "error", message: errorMessage(error) },
      }));
    } finally {
      setResourceBusy(resourceId, false);
    }
  }

  // Keep the ref current so the BroadcastChannel handler always calls the latest version.
  saveCommentRef.current = saveComment;

  async function requestComparison(resourceId: string) {
    setResourceBusy(resourceId, true);
    setFeedback((current) => ({
      ...current,
      [resourceId]: { tone: "progress", message: "正在安排候选观点关系检查…" },
    }));
    try {
      const result = await api<WorkRequestResponse>("/api/review-actions/compare", {
        method: "POST",
        body: JSON.stringify({ resource_id: resourceId }),
      });
      setRuns((current) => [
        result.run,
        ...current.filter((run) => run.run_id !== result.run.run_id),
      ]);
      setFeedback((current) => ({
        ...current,
        [resourceId]: {
          tone: "progress",
          message: result.reused
            ? "已有相同检查正在执行。"
            : "候选关系检查已排队；结果只会生成机器 comparison Resource。",
          runId: result.run.run_id,
        },
      }));
    } catch (error) {
      setFeedback((current) => ({
        ...current,
        [resourceId]: { tone: "error", message: errorMessage(error) },
      }));
    } finally {
      setResourceBusy(resourceId, false);
    }
  }

  async function acceptPaper(resource: ResourceRecord) {
    const resourceId = resource.resource_id;
    setResourceBusy(resourceId, true);
    setFeedback((current) => ({
      ...current,
      [resourceId]: {
        tone: "progress",
        message: "正在安排 PDF 全文总结…",
      },
    }));
    try {
      const result = await api<PaperFulltextResponse>("/api/paper/fulltext", {
        method: "POST",
        body: JSON.stringify({
          source_id: resource.source_id,
          preview_resource_id: resourceId,
        }),
      });
      if (result.fulltext_resource) {
        setResources((current) => [
          result.fulltext_resource as ResourceRecord,
          ...current.filter(
            (item) => item.resource_id !== result.fulltext_resource?.resource_id,
          ),
        ]);
        setFeedback((current) => ({
          ...current,
          [resourceId]: {
            tone: "success",
            message: "这篇论文已有 PDF 全文总结。",
          },
        }));
        await openResource(result.fulltext_resource);
        return;
      }
      const summarizeRunId = result.invocation?.step_runs.summarize;
      if (!summarizeRunId) {
        throw new Error("Atlas 没有返回全文总结任务。");
      }
      setFeedback((current) => ({
        ...current,
        [resourceId]: {
          tone: "progress",
          message: result.reused
            ? "已有相同的 Zotero/PDF 全文任务正在执行。"
            : "已排队：Zotero 导入 → PDF 索引 → 全文总结。",
          runId: summarizeRunId,
        },
      }));
      await loadReviewData(true);
    } catch (error) {
      setFeedback((current) => ({
        ...current,
        [resourceId]: { tone: "error", message: errorMessage(error) },
      }));
    } finally {
      setResourceBusy(resourceId, false);
    }
  }

  if (auth === "checking") {
    return (
      <main className="center-stage" aria-live="polite">
        <div className="connection-mark" aria-hidden="true" />
        <p className="eyebrow">ATLAS · RESOURCE REVIEW</p>
        <h1>正在连接 Atlas…</h1>
        <p>读取会话与控制面状态。</p>
      </main>
    );
  }

  if (auth === "anonymous") {
    return (
      <main className="login-stage">
        <section className="login-context">
          <p className="eyebrow">ATLAS · M3.2</p>
          <h1>把机器材料留在机器层，把你的判断留给你。</h1>
          <p>
            这里是 Source 与 Resource 的审阅入口。它只组织、调度与反馈，永远不会替你写
            Knowledge。
          </p>
          <div className="boundary-note">
            <span>01</span>
            <p>浏览器只使用 HttpOnly 会话；控制凭证不会进入这个页面。</p>
          </div>
        </section>
        <section className="login-panel" aria-labelledby="login-title">
          <div className="brand-lockup">
            <span className="atlas-glyph" aria-hidden="true">A</span>
            <div>
              <strong>Atlas Review</strong>
              <small>{atlasVersion ? `control plane ${atlasVersion}` : "control plane"}</small>
            </div>
          </div>
          <form onSubmit={handleLogin}>
            <h2 id="login-title">进入私人工作台</h2>
            <label htmlFor="atlas-password">Atlas 密码</label>
            <input
              id="atlas-password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
              autoFocus
            />
            {loginError ? <p className="form-error" role="alert">{loginError}</p> : null}
            <button className="primary-button" type="submit" disabled={loginBusy}>
              {loginBusy ? "正在验证…" : "打开 Resource Inbox"}
            </button>
          </form>
          <p className="login-footnote">仅通过你的 Tailscale 网络访问</p>
        </section>
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand-lockup compact">
          <span className="atlas-glyph" aria-hidden="true">A</span>
          <div>
            <strong>Atlas Review</strong>
            <small>human judgment queue</small>
          </div>
        </div>
        <div className="connection-state">
          <span className="live-dot" aria-hidden="true" />
          <span>Atlas {atlasVersion ?? "online"}</span>
          {hasActiveRuns ? <span className="worker-state">Lumio 正在执行</span> : null}
        </div>
        <button className="text-button" type="button" onClick={() => void handleLogout()}>
          退出
        </button>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">M3.2 · RESOURCE REVIEW</p>
          <h1>判断什么值得进入你的思考。</h1>
          <p className="hero-copy">
            Source 是原始材料，Resource 是机器加工结果。评论按钮只创建一张空白纸；内容仍由你写。
          </p>
        </div>
        <div className="hero-count" aria-label={`${counts.pending} 个待判断 Resource`}>
          <strong>{counts.pending.toString().padStart(2, "0")}</strong>
          <span>待判断</span>
        </div>
      </section>

      <section className="review-toolbar" aria-label="Resource 过滤与刷新">
        <div className="filters" role="tablist" aria-label="审阅状态">
          {(
            [
              ["pending", "待判断"],
              ["reviewed", "已评论"],
              ["dismissed", "已忽略"],
              ["all", "全部"],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              type="button"
              role="tab"
              aria-selected={filter === value}
              className={filter === value ? "filter active" : "filter"}
              onClick={() => setFilter(value)}
            >
              {label}<span>{counts[value]}</span>
            </button>
          ))}
        </div>
        <div className="refresh-cluster">
          <span>
            {lastUpdated
              ? `${new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(lastUpdated)} 更新`
              : "尚未更新"}
          </span>
          <button
            className="secondary-button"
            type="button"
            disabled={loading}
            onClick={() => void loadReviewData()}
          >
            {loading ? "同步中…" : "刷新"}
          </button>
        </div>
      </section>

      {loadError ? (
        <div className="global-error" role="alert">
          <strong>读取失败</strong>
          <span>{loadError}</span>
          <button type="button" onClick={() => void loadReviewData()}>重试</button>
        </div>
      ) : null}

      <section className="inbox-heading">
        <div>
          <p className="eyebrow">SOURCE LEDGER</p>
          <h2>{filter === "all" ? "全部来源" : `包含「${statusLabel(filter)}」的来源`}</h2>
        </div>
        <p>{visibleGroups.length} 个来源 · {resources.length} 个 summary 版本</p>
      </section>

      <section className="source-list" aria-busy={loading}>
        {!loading && visibleGroups.length === 0 ? (
          <div className="empty-state">
            <span aria-hidden="true">✓</span>
            <h2>{filter === "pending" ? "Inbox 已清空" : "这个视图还没有 Resource"}</h2>
            <p>
              {filter === "pending"
                ? "目前没有等待你判断的 summary。"
                : "切换状态，或者等待新的 Source 完成处理。"}
            </p>
          </div>
        ) : null}

        {visibleGroups.map((group, groupIndex) => {
          const source = group.source;
          return (
            <article className="source-card" key={group.sourceId}>
              <header className="source-header">
                <div className="source-index">{String(groupIndex + 1).padStart(2, "0")}</div>
                <div className="source-identity">
                  <div className="source-kicker">
                    <span>{sourceKindLabel(source?.kind)}</span>
                    {externalIdentity(source) ? <span>{externalIdentity(source)}</span> : null}
                    <span>{group.resources.length} 个版本</span>
                  </div>
                  <h3>{source?.title || group.resources[0]?.title || "未命名来源"}</h3>
                  <code title={group.sourceId}>{shortId(group.sourceId)}</code>
                </div>
                <div className="source-header-actions">
                  {source ? (
                    <a
                      className="source-link"
                      href={source.canonical_uri}
                      target="_blank"
                      rel="noreferrer"
                    >
                      打开原文 <span aria-hidden="true">↗</span>
                    </a>
                  ) : (
                    <span className="missing-source">Source metadata missing</span>
                  )}
                </div>
              </header>

              <div className="versions">
                {group.resources.map((resource, versionIndex) => {
                  const knowledge = knowledgeByResource.get(resource.resource_id);
                  const comment = commentByResource.get(resource.resource_id);
                  const comparison = comparisonByResource.get(resource.resource_id);
                  const run = latestRuns[resource.resource_id];
                  const activeComparison = runs.find((candidate) =>
                    candidate.job_name === "vortex-comparison-v1"
                    && candidate.input.resource_id === resource.resource_id
                    && isActiveRun(candidate)
                  );
                  const paperPreview = source?.kind === "paper" && isPaperPreview(resource);
                  const fulltextResource = paperPreview
                    ? paperFulltextForPreview(group.resources, resource)
                    : undefined;
                  const paperRun = paperPreview
                    ? paperFulltextRunForPreview(runs, resource.resource_id)
                    : undefined;
                  const activePaperRun = isActiveRun(paperRun);
                  const isBusy = busyResources.has(resource.resource_id);
                  const resourceFeedback = feedback[resource.resource_id];
                  const comparisonOpen = comparison?.resource_id === openResourceId;
                  const readerResource = comparisonOpen ? comparison : resource;
                  const document = documents[readerResource.resource_id];
                  const documentOpen = openResourceId === readerResource.resource_id;
                  const documentLoading = loadingDocuments.has(readerResource.resource_id);
                  return (
                    <section
                      className="resource-version"
                      id={`resource-${resource.resource_id}`}
                      key={resource.resource_id}
                    >
                      <div className="version-rail" aria-hidden="true">
                        <span className="version-dot" />
                        {versionIndex < group.resources.length - 1 ? <span className="version-line" /> : null}
                      </div>
                      <div className="resource-main">
                        <div className="resource-topline">
                          <div className="badges">
                            {versionIndex === 0 ? (
                              <span className="badge latest">时间上最新</span>
                            ) : null}
                            <span className={`badge status-${resource.review_status}`}>
                              {statusLabel(resource.review_status)}
                            </span>
                            <span className="badge generated">AI Resource</span>
                            {paperProfileLabel(resource) ? (
                              <span className="badge generated">{paperProfileLabel(resource)}</span>
                            ) : null}
                          </div>
                          <time dateTime={resource.created_at}>{formatTime(resource.created_at)}</time>
                        </div>
                        <h4>{resource.title}</h4>
                        <dl className="resource-metadata">
                          <div><dt>生成器</dt><dd>{generatorLabel(resource)}</dd></div>
                          <div><dt>Prompt</dt><dd>{resource.generator.prompt_version ?? "deterministic"}</dd></div>
                          <div><dt>Resource</dt><dd title={resource.resource_id}>{shortId(resource.resource_id)}</dd></div>
                        </dl>

                        {documentOpen ? (
                          <section className="resource-reader" aria-busy={documentLoading}>
                            <header>
                              <div>
                                <span className="eyebrow">RESOURCE CONTENT</span>
                                <strong>{readerResource.title}</strong>
                              </div>
                              <button type="button" onClick={() => setOpenResourceId(null)}>
                                收起
                              </button>
                            </header>
                            {documentLoading ? <p>正在从 Atlas 读取正文…</p> : null}
                            {documentErrors[readerResource.resource_id] ? (
                              <p className="reader-error">{documentErrors[readerResource.resource_id]}</p>
                            ) : null}
                            {document ? (
                              <pre className="resource-content">{document.content}</pre>
                            ) : null}
                            {readerResource.kind === "summary" ? (
                              <div className="comment-editor" id="comment">
                                <label htmlFor={`comment-${resource.resource_id}`}>我的评论</label>
                                <textarea
                                  id={`comment-${resource.resource_id}`}
                                  value={commentDrafts[resource.resource_id] ?? ""}
                                  placeholder="在这里记录你的判断、质疑和证据定位。支持 Markdown。"
                                  onChange={(event) => setCommentDrafts((current) => ({
                                    ...current,
                                    [resource.resource_id]: event.target.value,
                                  }))}
                                />
                                <div>
                                  <small>评论直接保存在 Atlas；同步到 Obsidian 是可选操作。</small>
                                  <button
                                    className="comment-button"
                                    type="button"
                                    disabled={isBusy}
                                    onClick={() => void saveComment(resource.resource_id)}
                                  >
                                    {isBusy ? "保存中…" : comment ? "更新评论" : "保存评论"}
                                  </button>
                                </div>
                              </div>
                            ) : null}
                          </section>
                        ) : null}

                        {knowledge ? (
                          <div className="knowledge-strip">
                            <span aria-hidden="true">✎</span>
                            <div>
                              <strong>{comment ? "评论保存在 Atlas" : "已建立知识引用"}</strong>
                              <small>{knowledge.note_id}</small>
                            </div>
                            {knowledge.uri.startsWith("obsidian:") ? (
                              <a href={knowledge.uri}>在 Obsidian 打开</a>
                            ) : null}
                          </div>
                        ) : null}

                        {run ? (
                          <div className={`run-strip run-${run.status}`}>
                            <span className="run-indicator" aria-hidden="true" />
                            <div>
                              <strong>{runLabel(run)}</strong>
                              <small>
                                {shortId(run.run_id)} · attempt {run.attempt_number}/{run.max_attempts}
                              </small>
                            </div>
                            {run.status === "failed" && run.error_message ? (
                              <span>{run.error_message}</span>
                            ) : null}
                          </div>
                        ) : null}

                        <div className="resource-actions">
                          {source ? (
                            <button
                              type="button"
                              onClick={() => {
                                const draft = commentDrafts[resource.resource_id] ?? "";
                                void openPip(resource.resource_id, resource.title, draft);
                                window.open(source.canonical_uri, "_blank", "noopener,noreferrer");
                              }}
                            >
                              原始材料
                            </button>
                          ) : null}
                          <button
                            className="comment-button"
                            type="button"
                            disabled={isBusy}
                            onClick={() => void openResource(resource, comment)}
                          >
                            {documentOpen ? "收起 Resource" : comment ? "阅读与编辑评论" : "阅读与评论"}
                          </button>
                          {paperPreview ? (
                            <button
                              type="button"
                              disabled={isBusy || activePaperRun}
                              onClick={() => fulltextResource
                                ? void openResource(fulltextResource)
                                : void acceptPaper(resource)}
                            >
                              {fulltextResource
                                ? "查看 PDF 全文总结"
                                : activePaperRun
                                  ? "正在处理 PDF"
                                  : "总结全文"}
                            </button>
                          ) : null}
                          {resource.review_status !== "dismissed" && comment ? (
                            <button
                              type="button"
                              disabled={isBusy || Boolean(activeComparison)}
                              onClick={() => void requestComparison(resource.resource_id)}
                            >
                              {activeComparison ? "正在生成对比" : comparison ? "更新观点对比" : "生成观点对比"}
                            </button>
                          ) : null}
                          {comparison ? (
                            <button
                              className="comparison-link"
                              type="button"
                              onClick={() => void openResource(comparison)}
                            >
                              查看对比
                            </button>
                          ) : null}
                          {resource.review_status === "dismissed" ? (
                            <button
                              type="button"
                              disabled={isBusy}
                              onClick={() => void changeReviewStatus(resource.resource_id, "pending")}
                            >
                              撤销忽略
                            </button>
                          ) : (
                            <button
                              className="dismiss-button"
                              type="button"
                              disabled={isBusy}
                              onClick={() => void changeReviewStatus(resource.resource_id, "dismissed")}
                            >
                              忽略
                            </button>
                          )}
                        </div>

                        {resourceFeedback ? (
                          <p className={`inline-feedback ${resourceFeedback.tone}`} role="status">
                            {resourceFeedback.message}
                          </p>
                        ) : null}
                      </div>
                    </section>
                  );
                })}
              </div>
            </article>
          );
        })}
      </section>

      <footer className="console-footer">
        <p>Atlas 保存 Resource、审阅状态与评论。Obsidian 只作为可选的长期知识投影。</p>
        <span>Resource Review Console · RFC 0004</span>
      </footer>
    </main>
  );
}
