import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the Atlas Review shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html[^>]*lang="zh-CN"/i);
  assert.match(html, /<title>Atlas — 材料与项目写作<\/title>/i);
  assert.match(html, /ATLAS · RESOURCE REVIEW/);
  assert.match(html, /正在连接 Atlas/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("removes starter surfaces and keeps credentials out of client source", async () => {
  const [page, reviewClient, apiClient, projectClient, knowledgeClient, markdownPreview, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/review-console.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/console-api.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/projects/projects-console.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/knowledge/knowledge-console.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/markdown-preview.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  const client = `${reviewClient}\n${apiClient}`;

  assert.match(page, /<ReviewConsole \/>/);
  assert.match(client, /credentials:\s*"include"/);
  assert.match(client, /\/api\/resources\/.*\/content/);
  assert.match(client, /\/api\/comments\?limit=500/);
  assert.match(client, /\/api\/review-actions\/complete-comment/);
  assert.match(client, /\/api\/review-actions\/compare/);
  assert.match(client, /\/api\/review-actions\/ignore-resource/);
  assert.match(client, /\/api\/review-actions\/restore-resource/);
  assert.doesNotMatch(client, /忽略评论与 Resource/);
  assert.equal(
    client.match(/changeReviewStatus\(resource\.resource_id,\s*"dismissed"\)/g)?.length,
    1,
  );
  assert.match(client, /最近 10 项内可随时撤销/);
  assert.doesNotMatch(client, /purge-source|彻底删除机器材料|window\.confirm/);
  assert.match(client, /阅读与评论/);
  assert.match(client, /保存评论/);
  assert.match(reviewClient, /<PaperReadingBrief markdown=\{document\.content\} \/>/);
  assert.match(reviewClient, /<MarkdownPreview markdown=\{document\.content\} \/>/);
  assert.doesNotMatch(reviewClient, /<pre className="resource-content"/);
  assert.match(markdownPreview, /Vditor\.preview/);
  assert.match(markdownPreview, /cdn: "\/vendor\/vditor"/);
  assert.match(markdownPreview, /engine: "KaTeX"/);
  assert.match(markdownPreview, /sanitize: true/);
  assert.match(client, /评论直接保存在 Atlas/);
  assert.doesNotMatch(client, /把评论提炼成可复用知识/);
  assert.match(client, /这条 Comment 是材料的一部分，不需要再重写一次/);
  assert.match(client, /\/api\/knowledge-notes/);
  assert.match(knowledgeClient, /AI 推荐新知识页/);
  assert.match(knowledgeClient, /AI 检查并建议改进/);
  assert.match(knowledgeClient, /knowledge\.suggest/);
  assert.doesNotMatch(client, /crypto\.subtle|content_hash:\s*await/);
  assert.match(client, /生成观点对比/);
  assert.match(client, /\/api\/paper\/fulltext/);
  assert.match(client, /生成阅读简报/);
  assert.match(client, /project_id=paper-library/);
  assert.match(client, /kind=comparison/);
  assert.match(client, /查看对比/);
  assert.match(client, /comparisonByResource/);
  assert.match(client, /<strong>\{onlineRunnerCount\}<\/strong>/);
  assert.doesNotMatch(client, /online\)\.length\}\/\{runners\.length\}/);
  assert.match(client, /<span>活动 Run<\/span>/);
  assert.match(client, /\{executingRunCount\} 执行 · \{waitingRunCount\} 等待/);
  assert.match(client, /\/api\/papers\?limit=20/);
  assert.match(client, /\/api\/papers\/compare/);
  assert.match(client, /检索、组织与对比论文/);
  assert.match(client, /保存组织信息/);
  assert.doesNotMatch(client, /openObsidianPair|obsidianCommentCreateUri/);
  assert.doesNotMatch(client, /shared[_-]?token|control[_-]?token|localStorage/i);
  assert.match(projectClient, /\/api\/writing-projects/);
  assert.match(projectClient, /\/api\/work-items/);
  assert.match(projectClient, /\/api\/documents/);
  assert.match(projectClient, /Markdown 是唯一正文/);
  assert.match(projectClient, /knowledgeRelevance/);
  assert.match(projectClient, /动态排序/);
  assert.match(projectClient, /\/api\/comments\?limit=200/);
  assert.match(projectClient, /插入评论摘录/);
  assert.match(projectClient, /atlas:comment:/);
  assert.match(projectClient, /knowledge-page:/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton|drizzle/);

  await assert.rejects(access(new URL("../app/_sites-preview", import.meta.url)));
  await assert.rejects(access(new URL("../db", import.meta.url)));
  await assert.rejects(access(new URL("../drizzle.config.ts", import.meta.url)));
});
