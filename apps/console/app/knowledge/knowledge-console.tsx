"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../console-api";
import { ConsoleNav } from "../console-nav";
import { MarkdownEditor } from "../markdown-editor";
import type { CommentRecord } from "../review-model";

type AuthState = "checking" | "anonymous" | "authenticated";
type NoteStatus = "draft" | "active" | "superseded" | "archived";

interface KnowledgePageRecord {
  knowledge_note_id: string;
  title: string;
  claim: string;
  body_markdown: string;
  tags: string[];
  source_ids: string[];
  resource_ids: string[];
  comment_ids: string[];
  status: NoteStatus;
  origin: "human" | "ai";
  revision: number;
  updated_at: string;
}

interface Invocation {
  invocation_id: string;
  status: "running" | "completed" | "failed" | "cancelled";
  step_runs: Record<string, string>;
}

interface RunRecord {
  status: string;
  output: { text?: string } | null;
  error_message: string | null;
}

interface Suggestion {
  title: string;
  claim: string;
  body_markdown: string;
  tags: string[];
  comment_ids: string[];
  rationale: string;
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : "发生了未知错误";
}

function parseTags(value: string): string[] {
  return Array.from(new Set(value.split(/[,，\n]/).map((item) => item.trim()).filter(Boolean)));
}

function parseSuggestion(text: string): Suggestion[] {
  const cleaned = text.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  const parsed = JSON.parse(cleaned) as { suggestions?: Suggestion[] };
  return Array.isArray(parsed.suggestions) ? parsed.suggestions : [];
}

export function KnowledgeConsole() {
  const [auth, setAuth] = useState<AuthState>("checking");
  const [password, setPassword] = useState("");
  const [pages, setPages] = useState<KnowledgePageRecord[]>([]);
  const [comments, setComments] = useState<CommentRecord[]>([]);
  const [pageId, setPageId] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [claim, setClaim] = useState("");
  const [body, setBody] = useState("");
  const [tags, setTags] = useState("");
  const [selectedComments, setSelectedComments] = useState<Set<string>>(new Set());
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [query, setQuery] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const activePage = pages.find((page) => page.knowledge_note_id === pageId) ?? null;
  const filteredPages = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return pages.filter((page) => !needle || `${page.title}\n${page.claim}\n${page.tags.join(" ")}`.toLowerCase().includes(needle));
  }, [pages, query]);

  const load = useCallback(async () => {
    const [nextPages, nextComments] = await Promise.all([
      api<KnowledgePageRecord[]>("/api/knowledge-notes?limit=500"),
      api<CommentRecord[]>("/api/comments?limit=500"),
    ]);
    setPages(nextPages);
    setComments(nextComments);
    return nextPages;
  }, []);

  function selectPage(page: KnowledgePageRecord) {
    setPageId(page.knowledge_note_id);
    setTitle(page.title);
    setClaim(page.claim);
    setBody(page.body_markdown);
    setTags(page.tags.join(", "));
    setSelectedComments(new Set(page.comment_ids));
    setSuggestions([]);
  }

  function newPage(commentIds: string[] = []) {
    setPageId(null);
    setTitle("");
    setClaim("");
    setBody("## 思考\n\n\n\n## 参考材料\n\n");
    setTags("");
    setSelectedComments(new Set(commentIds));
    setSuggestions([]);
  }

  useEffect(() => {
    void api<{ authenticated: boolean }>("/api/auth/me").then(async (state) => {
      setAuth(state.authenticated ? "authenticated" : "anonymous");
      if (!state.authenticated) return;
      const next = await load();
      const requested = new URLSearchParams(window.location.search).get("comment_id");
      const requestedPage = new URLSearchParams(window.location.search).get("note_id");
      const linkedPage = next.find((page) => page.knowledge_note_id === requestedPage);
      if (requested) newPage([requested]);
      else if (linkedPage) selectPage(linkedPage);
      else if (next[0]) selectPage(next[0]);
      else newPage();
    }).catch(() => setAuth("anonymous"));
  }, [load]);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setMessage("");
    try {
      await api("/api/auth/login", { method: "POST", body: JSON.stringify({ password }) });
      setAuth("authenticated");
      const next = await load();
      if (next[0]) selectPage(next[0]); else newPage();
    } catch (error) { setMessage(messageOf(error)); } finally { setBusy(false); }
  }

  async function savePage(status?: NoteStatus) {
    setBusy(true); setMessage("");
    const payload = {
      title, claim, body_markdown: body, tags: parseTags(tags),
      comment_ids: [...selectedComments], ...(status ? { status } : {}),
    };
    try {
      const saved = activePage
        ? await api<KnowledgePageRecord>(`/api/knowledge-notes/${activePage.knowledge_note_id}`, {
            method: "PATCH", body: JSON.stringify({ expected_revision: activePage.revision, ...payload }),
          })
        : await api<KnowledgePageRecord>("/api/knowledge-notes", {
            method: "POST", body: JSON.stringify({ ...payload, status: status ?? "draft", origin: "human" }),
          });
      const next = await load();
      selectPage(next.find((page) => page.knowledge_note_id === saved.knowledge_note_id) ?? saved);
      setMessage(status === "active" ? "知识页已确认发布。" : "知识页已保存到 Atlas。");
    } catch (error) { setMessage(messageOf(error)); } finally { setBusy(false); }
  }

  async function requestSuggestions(mode: "new_pages" | "improve_page") {
    setBusy(true); setMessage("AI 正在整理建议；结果不会自动写入知识库。"); setSuggestions([]);
    try {
      const candidateComments = selectedComments.size > 0
        ? comments.filter((item) => selectedComments.has(item.comment_id))
        : comments;
      const invocation = await api<Invocation>("/api/workflow-invocations", {
        method: "POST",
        body: JSON.stringify({
          workflow_name: "knowledge.suggest", workflow_version: "1",
          input: {
            mode,
            target_page: mode === "improve_page" ? activePage : null,
            comments: candidateComments.slice(0, 100).map((item) => ({
              comment_id: item.comment_id, body_markdown: item.body_markdown,
              source_ids: item.source_ids, resource_ids: item.resource_ids,
            })),
            existing_pages: pages.map((page) => ({ knowledge_note_id: page.knowledge_note_id, title: page.title, claim: page.claim })),
          },
        }),
      });
      const runId = invocation.step_runs.suggest;
      for (let attempt = 0; attempt < 120; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        const run = await api<RunRecord>(`/api/runs/${runId}`);
        if (run.status === "completed") {
          const next = parseSuggestion(run.output?.text ?? "");
          setSuggestions(next);
          setMessage(next.length ? "AI 建议已生成，请审阅后再采用。" : "AI 没有找到足够可靠的建议。");
          return;
        }
        if (["failed", "cancelled"].includes(run.status)) throw new Error(run.error_message ?? "AI 建议生成失败");
      }
      throw new Error("AI 建议生成超时，请稍后重试");
    } catch (error) { setMessage(messageOf(error)); } finally { setBusy(false); }
  }

  function applySuggestion(suggestion: Suggestion) {
    setTitle(suggestion.title); setClaim(suggestion.claim); setBody(suggestion.body_markdown);
    setTags(suggestion.tags.join(", "));
    setSelectedComments(new Set(suggestion.comment_ids.filter((id) => comments.some((item) => item.comment_id === id))));
    setMessage("建议已放入编辑器，尚未保存；请修改并确认。");
  }

  if (auth === "checking") return <main className="center-stage"><h1>正在连接知识库…</h1></main>;
  if (auth === "anonymous") return <main className="project-login"><p className="eyebrow">ATLAS · KNOWLEDGE BASE</p><h1>整理你对问题的长期理解。</h1><form onSubmit={login}><label>Atlas 密码</label><input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoFocus /><button className="primary-button" disabled={busy}>进入知识库</button></form>{message ? <p className="form-error">{message}</p> : null}</main>;

  return <main className="knowledge-shell">
    <header className="project-topbar"><div><p className="eyebrow">ATLAS · KNOWLEDGE BASE</p><strong>知识库</strong></div><span>知识页围绕问题组织，可综合多份材料</span></header>
    <ConsoleNav current="knowledge" />
    <section className="knowledge-layout">
      <aside className="knowledge-page-sidebar">
        <header><h1>知识页</h1><button onClick={() => newPage()}>+ 新建</button></header>
        <input placeholder="搜索标题、观点或标签" value={query} onChange={(event) => setQuery(event.target.value)} />
        <button className="ai-suggest-button" disabled={busy || comments.length === 0} onClick={() => void requestSuggestions("new_pages")}>AI 推荐新知识页</button>
        <div>{filteredPages.map((page) => <button key={page.knowledge_note_id} className={pageId === page.knowledge_note_id ? "active" : ""} onClick={() => selectPage(page)}><strong>{page.title}</strong><small>{page.claim}</small><span>{page.status === "active" ? "已确认" : "草稿"} · r{page.revision}</span></button>)}</div>
      </aside>
      <section className="knowledge-editor">
        <header><div><p className="eyebrow">{activePage ? `REVISION ${activePage.revision}` : "NEW PAGE"}</p><h1>{activePage ? "编辑知识页" : "建立知识页"}</h1></div><div><button disabled={busy || !title || !claim} onClick={() => void savePage()}>保存草稿</button><button className="primary-button" disabled={busy || !title || !claim} onClick={() => void savePage("active")}>确认发布</button></div></header>
        <label>标题<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="这个知识页讨论什么问题？" /></label>
        <label>核心观点<textarea className="knowledge-claim" value={claim} onChange={(event) => setClaim(event.target.value)} placeholder="用完整的一两句话说明你目前的判断" /></label>
        <div className="knowledge-body-field"><span>正文（即时渲染 Markdown）</span><MarkdownEditor value={body} onChange={setBody} /></div>
        <label>标签<input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="用逗号分隔" /></label>
        {message ? <p className="project-message" role="status">{message}</p> : null}
      </section>
      <aside className="knowledge-evidence">
        <header><p className="eyebrow">MATERIAL & AI</p><h2>材料与改进</h2><p>Comment 是你对单份材料的判断；知识页可以组合多条 Comment，并自动保留其 Source 与 Resource。</p></header>
        <div className="evidence-list">{comments.map((comment) => <label key={comment.comment_id}><input type="checkbox" checked={selectedComments.has(comment.comment_id)} onChange={() => setSelectedComments((current) => { const next = new Set(current); if (next.has(comment.comment_id)) next.delete(comment.comment_id); else next.add(comment.comment_id); return next; })} /><span><strong>{comment.body_markdown.slice(0, 100)}</strong><small>{comment.source_ids.length} Source · {comment.resource_ids.length} Resource</small></span></label>)}</div>
        <button className="ai-suggest-button" disabled={busy || !activePage} onClick={() => void requestSuggestions("improve_page")}>AI 检查并建议改进</button>
        <div className="suggestion-list">{suggestions.map((suggestion, index) => <article key={`${suggestion.title}-${index}`}><span className="eyebrow">AI PROPOSAL</span><h3>{suggestion.title}</h3><p>{suggestion.rationale}</p><button onClick={() => applySuggestion(suggestion)}>放入编辑器审阅</button></article>)}</div>
      </aside>
    </section>
  </main>;
}
