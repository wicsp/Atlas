"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { api, ApiError } from "../../console-api";
import { MarkdownPreview, PaperReadingBrief } from "../../markdown-preview";
import {
  isPaperReadingBrief,
  type CommentRecord,
  type KnowledgeRefRecord,
  type ResourceDocument,
  type ResourceRecord,
} from "../../review-model";

interface CommentCompleteResponse {
  resource: ResourceRecord;
  knowledge_ref: KnowledgeRefRecord;
  comment: CommentRecord;
}

interface PaperRecord {
  tags: string[];
  categories: string[];
}

interface WorkflowInvocation {
  step_runs: Record<string, string>;
}

interface RunRecord {
  status: string;
  output: { text?: string } | null;
  error_message: string | null;
}

interface OrganizationLabel {
  value: string;
  decision: "reuse" | "new";
  matched_existing: string | null;
}

interface OrganizationSuggestion {
  tags: OrganizationLabel[];
  categories: OrganizationLabel[];
  rationale: string;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function messageFor(error: unknown): string {
  return error instanceof Error ? error.message : "发生了未知错误";
}

function parseLabels(value: string): string[] {
  return Array.from(new Set(value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean)));
}

function parseOrganizationSuggestion(text: string): OrganizationSuggestion {
  const cleaned = text.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  const parsed = JSON.parse(cleaned) as OrganizationSuggestion;
  if (!Array.isArray(parsed.tags) || !Array.isArray(parsed.categories)) {
    throw new Error("AI 返回了无效的标签建议。");
  }
  return parsed;
}

export function ResourceWorkbench({ resourceId }: { resourceId: string }) {
  const [document, setDocument] = useState<ResourceDocument | null>(null);
  const [comment, setComment] = useState<CommentRecord | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [authenticated, setAuthenticated] = useState(true);
  const [paper, setPaper] = useState<PaperRecord | null>(null);
  const [paperTags, setPaperTags] = useState("");
  const [paperCategories, setPaperCategories] = useState("");
  const [organizationSuggestion, setOrganizationSuggestion] = useState<OrganizationSuggestion | null>(null);
  const [organizationBusy, setOrganizationBusy] = useState(false);

  const draftKey = useMemo(() => `atlas:comment-draft:${resourceId}`, [resourceId]);

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const [nextDocument, comments] = await Promise.all([
          api<ResourceDocument>(`/api/resources/${encodeURIComponent(resourceId)}/content`),
          api<CommentRecord[]>("/api/comments?limit=500"),
        ]);
        if (!active) return;
        const existing = comments.find((item) => item.resource_ids.includes(resourceId)) ?? null;
        const localDraft = window.sessionStorage.getItem(draftKey);
        setDocument(nextDocument);
        setComment(existing);
        setDraft(localDraft ?? existing?.body_markdown ?? "");
        if (nextDocument.source.kind === "paper") {
          const nextPaper = await api<PaperRecord>(
            `/api/papers/${encodeURIComponent(nextDocument.source.source_id)}`,
          );
          if (!active) return;
          setPaper(nextPaper);
          setPaperTags(nextPaper.tags.join(", "));
          setPaperCategories(nextPaper.categories.join(", "));
        }
      } catch (loadError) {
        if (!active) return;
        if (loadError instanceof ApiError && loadError.status === 401) {
          setAuthenticated(false);
          setError("请先回到材料页登录，再打开阅读工作台。");
        } else {
          setError(messageFor(loadError));
        }
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [draftKey, resourceId]);

  useEffect(() => {
    if (loading) return;
    if (draft.trim() && draft !== comment?.body_markdown) {
      window.sessionStorage.setItem(draftKey, draft);
    } else {
      window.sessionStorage.removeItem(draftKey);
    }
  }, [comment?.body_markdown, draft, draftKey, loading]);

  async function saveComment() {
    if (!draft.trim()) {
      setMessage("评论不能为空。");
      return;
    }
    setSaving(true);
    setMessage("正在保存…");
    try {
      if (document?.source.kind === "paper" && paper) {
        const updated = await api<PaperRecord>(
          `/api/papers/${encodeURIComponent(document.source.source_id)}`,
          {
            method: "PATCH",
            body: JSON.stringify({
              tags: parseLabels(paperTags),
              categories: parseLabels(paperCategories),
            }),
          },
        );
        setPaper(updated);
        setPaperTags(updated.tags.join(", "));
        setPaperCategories(updated.categories.join(", "));
      }
      const result = await api<CommentCompleteResponse>(
        "/api/review-actions/complete-comment",
        {
          method: "POST",
          body: JSON.stringify({ resource_id: resourceId, body_markdown: draft }),
        },
      );
      setDocument((current) => current ? { ...current, resource: result.resource } : current);
      setComment(result.comment);
      setDraft(result.comment.body_markdown);
      window.sessionStorage.removeItem(draftKey);
      setMessage("已保存。之后仍可继续修改。");
    } catch (saveError) {
      setMessage(messageFor(saveError));
    } finally {
      setSaving(false);
    }
  }

  async function requestOrganizationSuggestion() {
    if (!document || document.source.kind !== "paper") return;
    setOrganizationBusy(true);
    setMessage("AI 正在参考现有标签与分类；建议不会自动保存。");
    setOrganizationSuggestion(null);
    try {
      const invocation = await api<WorkflowInvocation>(
        `/api/papers/${encodeURIComponent(document.source.source_id)}/organization-suggestions`,
        {
          method: "POST",
          body: JSON.stringify({ resource_id: resourceId }),
        },
      );
      const runId = invocation.step_runs.suggest;
      if (!runId) throw new Error("Atlas 没有返回论文组织建议任务。");
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const run = await api<RunRecord>(`/api/runs/${runId}`);
        if (run.status === "completed") {
          const suggestion = parseOrganizationSuggestion(run.output?.text ?? "");
          setOrganizationSuggestion(suggestion);
          setMessage("AI 建议已生成；请放入编辑器后修改或确认。");
          return;
        }
        if (["failed", "cancelled"].includes(run.status)) {
          throw new Error(run.error_message ?? "论文组织建议生成失败。");
        }
      }
      throw new Error("论文组织建议生成超时，请稍后重试。");
    } catch (suggestionError) {
      setMessage(messageFor(suggestionError));
    } finally {
      setOrganizationBusy(false);
    }
  }

  function applyOrganizationSuggestion() {
    if (!organizationSuggestion) return;
    setPaperTags(organizationSuggestion.tags.map((item) => item.value).join(", "));
    setPaperCategories(organizationSuggestion.categories.map((item) => item.value).join(", "));
    setMessage("建议已放入编辑器，尚未保存；可以继续修改。");
  }

  return (
    <main className="resource-workbench">
      <header className="workbench-header">
        <Link className="workbench-back" href="/materials">← 返回材料</Link>
        <div>
          <span className="eyebrow">READING WORKBENCH</span>
          <strong>{document?.resource.title ?? "Resource 阅读工作台"}</strong>
        </div>
        {document ? (
          <a href={document.source.canonical_uri} target="_blank" rel="noreferrer">
            查看原始材料 ↗
          </a>
        ) : <span />}
      </header>

      {loading ? <div className="workbench-state">正在读取 Resource…</div> : null}
      {error ? (
        <div className="workbench-state error">
          <p>{error}</p>
          {!authenticated ? <Link href="/materials">回到材料页登录</Link> : null}
        </div>
      ) : null}

      {document ? (
        <div className="workbench-grid">
          <article className="workbench-reader">
            <div className="workbench-resource-meta">
              <span>{document.source.kind === "paper" ? "论文" : "材料"}</span>
              <span>{document.resource.review_status === "reviewed" ? "已评论" : "待判断"}</span>
              <time dateTime={document.resource.created_at}>{formatTime(document.resource.created_at)}</time>
            </div>
            {isPaperReadingBrief(document.resource)
              ? <PaperReadingBrief markdown={document.content} />
              : <MarkdownPreview markdown={document.content} />}
          </article>

          <aside className="workbench-comment" aria-label="Comment 编辑器">
            <div className="workbench-comment-heading">
              <div>
                <span className="eyebrow">MY COMMENT</span>
                <h1>{comment ? "继续修改判断" : "写下你的判断"}</h1>
              </div>
              <span className="draft-state">{comment ? "已保存过" : "本地自动保存草稿"}</span>
            </div>
            <p className="comment-guidance">
              不必复述摘要。记录你是否认同、最关键的证据、仍然存疑的地方，以及它和你已有工作的关系。
              评论直接保存在 Atlas；未提交的内容只作为本机草稿保留。
            </p>
            {document.source.kind === "paper" ? (
              <section className="paper-organization" aria-label="论文标签与分类">
                <header>
                  <div>
                    <span className="eyebrow">PAPER ORGANIZATION</span>
                    <h2>标签与分类</h2>
                  </div>
                  <button
                    type="button"
                    disabled={organizationBusy}
                    onClick={() => void requestOrganizationSuggestion()}
                  >
                    {organizationBusy ? "AI 分析中…" : "AI 建议"}
                  </button>
                </header>
                <p>AI 会优先复用 Atlas 已有词表；只有确有语义缺口时才建议新建。</p>
                {organizationSuggestion ? (
                  <div className="organization-proposal">
                    <div>
                      {[...organizationSuggestion.categories, ...organizationSuggestion.tags].map((item) => (
                        <span key={`${item.decision}-${item.value}`} className={item.decision}>
                          {item.value}<small>{item.decision === "reuse" ? "已有" : "新建"}</small>
                        </span>
                      ))}
                    </div>
                    <p>{organizationSuggestion.rationale}</p>
                    <button type="button" onClick={applyOrganizationSuggestion}>放入编辑器</button>
                  </div>
                ) : null}
                <label>
                  分类
                  <input
                    value={paperCategories}
                    placeholder="例如：机器学习安全"
                    onChange={(event) => setPaperCategories(event.target.value)}
                  />
                </label>
                <label>
                  标签
                  <input
                    value={paperTags}
                    placeholder="例如：agent, evaluation"
                    onChange={(event) => setPaperTags(event.target.value)}
                  />
                </label>
              </section>
            ) : null}
            <textarea
              aria-label="我的 Comment"
              autoFocus
              value={draft}
              placeholder={"例如：\n- 这篇工作的真正贡献是什么？\n- 哪个实验最能支撑或削弱结论？\n- 我之后需要回原文核查什么？"}
              onChange={(event) => setDraft(event.target.value)}
            />
            <footer className="workbench-comment-actions">
              <span role="status">{message || `${draft.trim().length} 字`}</span>
              <button type="button" disabled={saving} onClick={() => void saveComment()}>
                {saving ? "保存中…" : comment ? "更新评论" : "保存评论"}
              </button>
            </footer>
          </aside>
        </div>
      ) : null}
    </main>
  );
}
