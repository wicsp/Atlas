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

export function ResourceWorkbench({ resourceId }: { resourceId: string }) {
  const [document, setDocument] = useState<ResourceDocument | null>(null);
  const [comment, setComment] = useState<CommentRecord | null>(null);
  const [draft, setDraft] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [authenticated, setAuthenticated] = useState(true);

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
