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
  assert.match(html, /<title>Atlas Review — Resource Inbox<\/title>/i);
  assert.match(html, /ATLAS · RESOURCE REVIEW/);
  assert.match(html, /正在连接 Atlas/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/i);
});

test("removes starter surfaces and keeps credentials out of client source", async () => {
  const [page, client, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/review-console.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);

  assert.match(page, /<ReviewConsole \/>/);
  assert.match(client, /credentials:\s*"include"/);
  assert.match(client, /\/api\/review-actions\/sync-comment/);
  assert.match(client, /\/api\/comments\?limit=500/);
  assert.match(client, /\/api\/review-actions\/compare/);
  assert.match(client, /\/api\/review-actions\/purge-source/);
  assert.match(client, /彻底删除机器材料/);
  assert.match(client, /window\.confirm/);
  assert.match(client, /obsidian:\/\/new\?vault=Vortex/);
  assert.match(client, /openObsidianPair/);
  assert.match(client, /完成评论/);
  assert.match(client, /生成观点对比/);
  assert.match(client, /kind=comparison/);
  assert.match(client, /查看对比/);
  assert.match(client, /comparisonByResource/);
  assert.doesNotMatch(client, /shared[_-]?token|control[_-]?token|localStorage/i);
  assert.doesNotMatch(packageJson, /react-loading-skeleton|drizzle/);

  await assert.rejects(access(new URL("../app/_sites-preview", import.meta.url)));
  await assert.rejects(access(new URL("../db", import.meta.url)));
  await assert.rejects(access(new URL("../drizzle.config.ts", import.meta.url)));
});
