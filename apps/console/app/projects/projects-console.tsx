"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import { api } from "../console-api";
import { ConsoleNav } from "../console-nav";
import type { CommentRecord } from "../review-model";

type AuthState = "checking" | "anonymous" | "authenticated";
type ProjectStatus = "active" | "on_hold" | "completed" | "archived";
type WorkItemStatus = "todo" | "in_progress" | "blocked" | "done" | "cancelled";
type DocumentStatus = "draft" | "final" | "archived";

interface ProjectRecord {
  project_id: string;
  title: string;
  goal: string;
  description: string;
  audience: string;
  deadline: string | null;
  status: ProjectStatus;
  revision: number;
  updated_at: string;
}

interface WorkItemRecord {
  work_item_id: string;
  project_id: string;
  title: string;
  description: string;
  document_id: string | null;
  status: WorkItemStatus;
  revision: number;
}

interface DocumentRecord {
  document_id: string;
  project_id: string;
  title: string;
  body_markdown: string;
  status: DocumentStatus;
  linked_knowledge_note_ids: string[];
  revision: number;
  updated_at: string;
}

interface ProjectDetail {
  project: ProjectRecord;
  work_items: WorkItemRecord[];
  documents: DocumentRecord[];
}

interface KnowledgeNote {
  knowledge_note_id: string;
  title: string;
  claim: string;
  body_markdown: string;
  tags: string[];
  status: string;
  revision: number;
}

type WritingReference =
  | { kind: "knowledge"; note: KnowledgeNote; score: number }
  | { kind: "comment"; comment: CommentRecord; score: number };

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "发生了未知错误";
}

function statusLabel(status: WorkItemStatus): string {
  return {
    todo: "待处理",
    in_progress: "进行中",
    blocked: "受阻",
    done: "已完成",
    cancelled: "已取消",
  }[status];
}

function searchTokens(value: string): Set<string> {
  const normalized = value.toLowerCase();
  const tokens = normalized.match(/[a-z0-9_-]{2,}|[\u3400-\u9fff]{2,}/g) ?? [];
  const expanded = new Set<string>();
  for (const token of tokens) {
    expanded.add(token);
    if (/^[\u3400-\u9fff]+$/.test(token)) {
      for (let index = 0; index < token.length - 1; index += 1) {
        expanded.add(token.slice(index, index + 2));
      }
    }
  }
  return expanded;
}

function knowledgeRelevance(note: KnowledgeNote, context: Set<string>): number {
  if (context.size === 0) return 0;
  const title = searchTokens(note.title);
  const claim = searchTokens(note.claim);
  const tags = searchTokens(note.tags.join(" "));
  let score = 0;
  for (const token of context) {
    if (title.has(token)) score += 5;
    if (tags.has(token)) score += 3;
    if (claim.has(token)) score += 1;
  }
  return score;
}

function commentRelevance(comment: CommentRecord, context: Set<string>): number {
  if (context.size === 0) return 0;
  const body = searchTokens(comment.body_markdown);
  let score = 0;
  for (const token of context) {
    if (body.has(token)) score += 1;
  }
  return score;
}

export function ProjectsConsole() {
  const [auth, setAuth] = useState<AuthState>("checking");
  const [password, setPassword] = useState("");
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProjectDetail | null>(null);
  const [documentId, setDocumentId] = useState<string | null>(null);
  const [documentTitle, setDocumentTitle] = useState("");
  const [markdown, setMarkdown] = useState("");
  const [notes, setNotes] = useState<KnowledgeNote[]>([]);
  const [comments, setComments] = useState<CommentRecord[]>([]);
  const [noteQuery, setNoteQuery] = useState("");
  const [newProjectTitle, setNewProjectTitle] = useState("");
  const [newProjectGoal, setNewProjectGoal] = useState("");
  const [newWorkItem, setNewWorkItem] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const activeDocument = useMemo(
    () => detail?.documents.find((item) => item.document_id === documentId) ?? null,
    [detail, documentId],
  );
  const writingReferences = useMemo(() => {
    const query = noteQuery.trim().toLowerCase();
    const context = searchTokens(query || `${detail?.project.goal ?? ""}\n${markdown}`);
    const noteReferences: WritingReference[] = notes
      .filter((note) => note.status !== "archived")
      .filter((note) =>
        !query
        || note.title.toLowerCase().includes(query)
        || note.claim.toLowerCase().includes(query)
        || note.tags.some((tag) => tag.toLowerCase().includes(query))
      )
      .map((note) => ({ kind: "knowledge", note, score: knowledgeRelevance(note, context) }));
    const commentReferences: WritingReference[] = comments
      .filter((comment) =>
        !query || comment.body_markdown.toLowerCase().includes(query)
      )
      .map((comment) => ({
        kind: "comment",
        comment,
        score: commentRelevance(comment, context),
      }));
    return [...noteReferences, ...commentReferences]
      .sort((left, right) =>
        right.score - left.score
        || (left.kind === "knowledge" ? 0 : 1) - (right.kind === "knowledge" ? 0 : 1)
      )
      .slice(0, 30);
  }, [comments, detail?.project.goal, markdown, noteQuery, notes]);

  const loadProject = useCallback(async (nextProjectId: string) => {
    const next = await api<ProjectDetail>(`/api/writing-projects/${nextProjectId}`);
    setDetail(next);
    setProjectId(nextProjectId);
    const preferred =
      next.documents.find((item) => item.status !== "archived")
      ?? next.documents[0]
      ?? null;
    setDocumentId(preferred?.document_id ?? null);
    setDocumentTitle(preferred?.title ?? "");
    setMarkdown(preferred?.body_markdown ?? "");
  }, []);

  const load = useCallback(async () => {
    const [nextProjects, nextNotes, nextComments] = await Promise.all([
      api<ProjectRecord[]>("/api/writing-projects?limit=100"),
      api<KnowledgeNote[]>("/api/knowledge-notes?limit=200"),
      api<CommentRecord[]>("/api/comments?limit=200"),
    ]);
    setProjects(nextProjects);
    setNotes(nextNotes);
    setComments(nextComments);
    const selected = projectId && nextProjects.some((item) => item.project_id === projectId)
      ? projectId
      : nextProjects[0]?.project_id;
    if (selected) await loadProject(selected);
  }, [loadProject, projectId]);

  useEffect(() => {
    void api<{ authenticated: boolean }>("/api/auth/me")
      .then(async (status) => {
        setAuth(status.authenticated ? "authenticated" : "anonymous");
        if (status.authenticated) await load();
      })
      .catch(() => setAuth("anonymous"));
  // Initial session check only.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await api("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      setAuth("authenticated");
      await load();
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function createProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const project = await api<ProjectRecord>("/api/writing-projects", {
        method: "POST",
        body: JSON.stringify({ title: newProjectTitle, goal: newProjectGoal }),
      });
      setProjects((current) => [project, ...current]);
      setNewProjectTitle("");
      setNewProjectGoal("");
      await loadProject(project.project_id);
      setMessage("项目已建立。下一步可以创建正文和工作项。");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function createDocument() {
    if (!projectId) return;
    setBusy(true);
    try {
      const document = await api<DocumentRecord>("/api/documents", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          title: "项目正文",
          body_markdown: `# ${detail?.project.title ?? "项目正文"}\n\n`,
        }),
      });
      await loadProject(projectId);
      setDocumentId(document.document_id);
      setDocumentTitle(document.title);
      setMarkdown(document.body_markdown);
      setMessage("Markdown 正文已创建。");
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function saveDocument(status?: DocumentStatus) {
    if (!activeDocument) return;
    setBusy(true);
    setMessage("");
    try {
      const saved = await api<DocumentRecord>(
        `/api/documents/${activeDocument.document_id}`,
        {
          method: "PATCH",
          body: JSON.stringify({
            expected_revision: activeDocument.revision,
            title: documentTitle,
            body_markdown: markdown,
            ...(status ? { status } : {}),
          }),
        },
      );
      setDetail((current) => current ? {
        ...current,
        documents: current.documents.map((item) =>
          item.document_id === saved.document_id ? saved : item
        ),
      } : current);
      setMessage(status === "final" ? "正文已标记为定稿。" : "Markdown 已保存到 Atlas。");
    } catch (error) {
      setMessage(errorMessage(error));
      if (projectId) await loadProject(projectId);
    } finally {
      setBusy(false);
    }
  }

  async function snapshot() {
    if (!activeDocument) return;
    await saveDocument();
    const current = await api<DocumentRecord>(`/api/documents/${activeDocument.document_id}`);
    await api(`/api/documents/${current.document_id}/versions`, {
      method: "POST",
      body: JSON.stringify({ label: "手动快照" }),
    });
    setMessage(`已创建第 ${current.revision} 版不可变快照。`);
  }

  async function addWorkItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    setBusy(true);
    try {
      await api("/api/work-items", {
        method: "POST",
        body: JSON.stringify({
          project_id: projectId,
          title: newWorkItem,
          document_id: documentId,
        }),
      });
      setNewWorkItem("");
      await loadProject(projectId);
    } catch (error) {
      setMessage(errorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function advanceWorkItem(item: WorkItemRecord) {
    const next: WorkItemStatus =
      item.status === "todo" ? "in_progress" : item.status === "in_progress" ? "done" : "todo";
    try {
      await api(`/api/work-items/${item.work_item_id}`, {
        method: "PATCH",
        body: JSON.stringify({ expected_revision: item.revision, status: next }),
      });
      if (projectId) await loadProject(projectId);
    } catch (error) {
      setMessage(errorMessage(error));
    }
  }

  function selectDocument(document: DocumentRecord) {
    setDocumentId(document.document_id);
    setDocumentTitle(document.title);
    setMarkdown(document.body_markdown);
  }

  function insertKnowledge(note: KnowledgeNote) {
    const link = `[[${note.knowledge_note_id}|${note.title}]]`;
    setMarkdown((current) => `${current}${current.endsWith("\n") ? "" : "\n"}${link} `);
    setMessage(`已插入「${note.title}」的引用；保存后 Atlas 会自动建立 Link 和 Backlink。`);
  }

  function embedKnowledge(note: KnowledgeNote) {
    const embed = `{{knowledge-page:${note.knowledge_note_id}}}`;
    setMarkdown((current) => `${current}${current.endsWith("\n") ? "" : "\n"}${embed}\n`);
    setMessage(`已嵌入「${note.title}」；它会跟随知识页更新。`);
  }

  function insertComment(comment: CommentRecord) {
    const excerpt = comment.body_markdown.trim();
    const quoted = excerpt
      .split("\n")
      .map((line) => `> ${line}`)
      .join("\n");
    const marker = `<!-- atlas:comment:${comment.comment_id} -->`;
    setMarkdown((current) =>
      `${current}${current.endsWith("\n") ? "" : "\n"}\n${marker}\n${quoted}\n`
    );
    setMessage("已插入个人评论摘录并保留 Atlas Comment 来源标记。");
  }

  if (auth === "checking") {
    return <main className="center-stage"><div className="connection-mark" /><h1>正在连接项目空间…</h1></main>;
  }
  if (auth === "anonymous") {
    return (
      <main className="project-login">
        <p className="eyebrow">ATLAS · PROJECT WRITING</p>
        <h1>从知识走向最终输出。</h1>
        <form onSubmit={login}>
          <label htmlFor="project-password">Atlas 密码</label>
          <input
            id="project-password"
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            autoFocus
          />
          <button className="primary-button" disabled={busy}>进入项目空间</button>
        </form>
        {message ? <p className="form-error">{message}</p> : null}
        <a href="/materials">返回材料空间</a>
      </main>
    );
  }

  return (
    <main className="project-shell">
      <header className="project-topbar">
        <div>
          <p className="eyebrow">ATLAS · MARKDOWN FIRST</p>
          <strong>项目写作</strong>
        </div>
        <span>Atlas 中心存储 · Markdown 是唯一正文</span>
      </header>
      <ConsoleNav current="projects" />

      <section className="project-layout">
        <aside className="project-sidebar">
          <header><h1>项目</h1><span>{projects.length}</span></header>
          <div className="project-list">
            {projects.map((project) => (
              <button
                key={project.project_id}
                className={project.project_id === projectId ? "active" : ""}
                onClick={() => void loadProject(project.project_id)}
              >
                <strong>{project.title}</strong>
                <small>{project.goal}</small>
              </button>
            ))}
          </div>
          <form className="new-project" onSubmit={createProject}>
            <h2>新建项目</h2>
            <input
              placeholder="项目名称"
              value={newProjectTitle}
              onChange={(event) => setNewProjectTitle(event.target.value)}
              required
            />
            <textarea
              placeholder="这个项目最终要完成什么？"
              value={newProjectGoal}
              onChange={(event) => setNewProjectGoal(event.target.value)}
              required
            />
            <button className="primary-button" disabled={busy}>建立项目</button>
          </form>
        </aside>

        <section className="writing-stage">
          {!detail ? (
            <div className="project-empty">
              <h1>先建立一个有明确结果的项目</h1>
              <p>Project 管目标，WorkItem 管下一步，Document 保存最终 Markdown。</p>
            </div>
          ) : (
            <>
              <header className="project-heading">
                <div>
                  <p className="eyebrow">CURRENT PROJECT</p>
                  <h1>{detail.project.title}</h1>
                  <p>{detail.project.goal}</p>
                </div>
                <span className={`project-status ${detail.project.status}`}>{detail.project.status}</span>
              </header>

              <section className="work-items">
                <header><h2>下一步</h2><small>点击状态向前推进</small></header>
                <div>
                  {detail.work_items.map((item) => (
                    <button key={item.work_item_id} onClick={() => void advanceWorkItem(item)}>
                      <span className={`work-status ${item.status}`}>{statusLabel(item.status)}</span>
                      <strong>{item.title}</strong>
                    </button>
                  ))}
                </div>
                <form onSubmit={addWorkItem}>
                  <input
                    placeholder="添加一个可以完成的动作"
                    value={newWorkItem}
                    onChange={(event) => setNewWorkItem(event.target.value)}
                    required
                  />
                  <button disabled={busy}>添加</button>
                </form>
              </section>

              <section className="document-tabs">
                {detail.documents.map((document) => (
                  <button
                    key={document.document_id}
                    className={document.document_id === documentId ? "active" : ""}
                    onClick={() => selectDocument(document)}
                  >
                    {document.title}<small>r{document.revision}</small>
                  </button>
                ))}
                <button className="new-document" onClick={() => void createDocument()}>
                  + 新建正文
                </button>
              </section>

              {activeDocument ? (
                <section className="markdown-workbench">
                  <header>
                    <input
                      aria-label="文档标题"
                      value={documentTitle}
                      onChange={(event) => setDocumentTitle(event.target.value)}
                    />
                    <div>
                      <button disabled={busy} onClick={() => void saveDocument()}>保存</button>
                      <button disabled={busy} onClick={() => void snapshot()}>创建快照</button>
                      <button
                        className="finalize"
                        disabled={busy}
                        onClick={() => void saveDocument("final")}
                      >
                        标记定稿
                      </button>
                    </div>
                  </header>
                  <textarea
                    aria-label="Markdown 正文"
                    value={markdown}
                    onChange={(event) => setMarkdown(event.target.value)}
                    onKeyDown={(event) => {
                      if ((event.metaKey || event.ctrlKey) && event.key === "s") {
                        event.preventDefault();
                        void saveDocument();
                      }
                    }}
                    spellCheck
                  />
                  <footer>
                    <span>{markdown.length.toLocaleString("zh-CN")} 字符</span>
                    <span>{activeDocument.linked_knowledge_note_ids.length} 个已索引知识链接</span>
                    <span>{activeDocument.status === "final" ? "已定稿" : "草稿"}</span>
                  </footer>
                </section>
              ) : (
                <button className="create-first-document" onClick={() => void createDocument()}>
                  创建第一份 Markdown 正文
                </button>
              )}
            </>
          )}
          {message ? <p className="project-message" role="status">{message}</p> : null}
        </section>

        <aside className="knowledge-sidebar">
          <header>
            <p className="eyebrow">KNOWLEDGE</p>
            <h2>写作参考</h2>
            <p>
              根据项目目标和当前正文动态排序。知识页可以只建立引用，也可以嵌入正文；Comment 可直接作为材料摘录。
            </p>
          </header>
          <input
            aria-label="搜索写作参考"
            placeholder="搜索知识、评论或标签"
            value={noteQuery}
            onChange={(event) => setNoteQuery(event.target.value)}
          />
          <div className="knowledge-note-list">
            {writingReferences.map((reference) =>
              reference.kind === "knowledge" ? (
                <article key={reference.note.knowledge_note_id}>
                  <span className="reference-kind">知识页</span>
                  <h3>{reference.note.title}</h3>
                  <p>{reference.note.claim}</p>
                  <small>{reference.note.tags.join(" · ") || "未标记"}</small>
                  <div className="reference-actions">
                    <button disabled={!activeDocument} onClick={() => insertKnowledge(reference.note)}>
                      插入引用
                    </button>
                    <button disabled={!activeDocument} onClick={() => embedKnowledge(reference.note)}>
                      嵌入正文
                    </button>
                    <a href={`/knowledge?note_id=${reference.note.knowledge_note_id}`}>打开知识页</a>
                  </div>
                </article>
              ) : (
                <article key={reference.comment.comment_id}>
                  <span className="reference-kind comment">个人评论</span>
                  <h3>来自材料处理的判断</h3>
                  <p>{reference.comment.body_markdown.slice(0, 320)}</p>
                  <small>{reference.comment.comment_id}</small>
                  <div className="reference-actions">
                    <button
                      disabled={!activeDocument}
                      onClick={() => insertComment(reference.comment)}
                    >
                      插入评论摘录
                    </button>
                    {reference.comment.resource_ids[0] ? (
                      <a href={`/materials#resource-${reference.comment.resource_ids[0]}`}>
                        查看材料
                      </a>
                    ) : null}
                  </div>
                </article>
              )
            )}
            {writingReferences.length === 0 ? (
              <div className="reference-empty">
                <strong>还没有可用参考</strong>
                <p>先在材料页保存 Comment，或在知识库建立知识页。</p>
                <a href="/materials">去处理材料</a>
              </div>
            ) : null}
          </div>
        </aside>
      </section>
    </main>
  );
}
