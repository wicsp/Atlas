import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Paper } from "@lumio/schema";
import response from "../../../fixtures/papers/crossref-lightgcn.json";
import { confirmCitekey, createPaper, fillMetadata, parseCrossrefMetadata, parseFrontmatter, renderPaper, type FillContext } from "../src/index.ts";

const metadata = parseCrossrefMetadata(response);
const confirmed = confirmCitekey(metadata, "LightGCN");
const ctx: FillContext = {
  now: new Date("2026-10-22T23:00:00+08:00"), tz: "Asia/Singapore",
  newId: (prefix) => `${prefix}_01J9Z3K8M2N4P6Q8R0S2T4V6W8`,
};
const bibtex = await readFile(new URL("../../../fixtures/papers/crossref-lightgcn.bib", import.meta.url), "utf8");
let vault: string;
beforeEach(async () => { vault = await mkdtemp(join(tmpdir(), "lumio-paper-test-")); });
afterEach(async () => { await rm(vault, { recursive: true, force: true }); });

test("a rendered paper passes its contract, has all sections and no invented links/default fields", async () => {
  const path = await createPaper(vault, metadata, confirmed, bibtex, ctx);
  expect(path).toBe("papers/He_2020_LightGCN.md");
  const parsed = parseFrontmatter(await readFile(join(vault, path)));
  expect(Paper.safeParse(parsed.data).success).toBe(true);
  expect(parsed.data).toMatchObject({ type: "paper", citekey: "He_2020_LightGCN", title: metadata.title, authors: metadata.authors, year: metadata.year, doi: metadata.doi });
  for (const field of ["status", "tags", "related", "arxiv", "firstAuthorFamily"]) expect(parsed.data).not.toHaveProperty(field);
  const body = parsed.body.toString();
  expect(body.startsWith("\n## 一句话\n")).toBe(true);
  expect(body.match(/^## .+$/gm)).toEqual(["## 一句话", "## 我的笔记", "## 可以引用的点", "## 和我的研究的关系", "## BibTeX"]);
  expect(body).toContain("```bibtex\n");
  expect(body).toContain("@inproceedings{He_2020_LightGCN,");
  expect(body).not.toContain("[[");
  expect(fillMetadata({ type: "paper", frontmatter: parsed.data, fileName: "He_2020_LightGCN", birthtime: ctx.now, mtime: ctx.now }, ctx))
    .toEqual({ patch: {}, issues: [] });
  expect(await readdir(vault)).toEqual(["papers"]);
});

test("arXiv metadata with empty optional fields omits those fields", () => {
  const parsed = parseFrontmatter(renderPaper({ title: "LightGCN", authors: metadata.authors, year: 2020, arxiv: "2002.02126", doi: "", venue: "" }, confirmed, bibtex, ctx).content);
  expect(parsed.data).toHaveProperty("arxiv", "2002.02126");
  for (const key of ["doi", "venue", "url"]) expect(parsed.data).not.toHaveProperty(key);
  expect(Paper.safeParse(parsed.data).success).toBe(true);
});

test("identical DOI is rejected, including case/URL variants and nested existing notes", async () => {
  const path = await createPaper(vault, metadata, confirmed, bibtex, ctx);
  await mkdir(join(vault, "papers/nested"));
  const original = await readFile(join(vault, path));
  await writeFile(join(vault, "papers/nested/existing.md"), parseFrontmatter("body").render({ doi: `https://doi.org/${metadata.doi!.toUpperCase()}` }));
  await rm(join(vault, path));
  await expect(createPaper(vault, metadata, confirmCitekey(metadata, "Other"), bibtex, ctx)).rejects.toMatchObject({ code: "DUPLICATE_PAPER" });
  expect(await readdir(join(vault, "papers"))).toEqual(["nested"]);
  expect(original.length).toBeGreaterThan(0);
});

test("identical arXiv is rejected regardless of stored version", async () => {
  await mkdir(join(vault, "papers"));
  const existing = join(vault, "papers/existing.md");
  await writeFile(existing, parseFrontmatter("body").render({ arxiv: "https://arxiv.org/abs/2002.02126v2" }));
  const before = await stat(existing);
  const paper = { ...metadata, arxiv: "2002.02126" };
  await expect(createPaper(vault, paper, confirmed, bibtex, ctx)).rejects.toMatchObject({ code: "DUPLICATE_PAPER" });
  expect((await stat(existing)).mtimeMs).toBe(before.mtimeMs);
  expect(await readdir(join(vault, "papers"))).toEqual(["existing.md"]);
});

test("identical citekey reports --abbr and preserves the file byte for byte", async () => {
  const path = join(vault, await createPaper(vault, metadata, confirmed, bibtex, ctx));
  const bytes = await readFile(path);
  const before = await stat(path);
  await expect(createPaper(vault, { ...metadata, doi: "10.1234/different" }, confirmed, bibtex, ctx)).rejects.toThrow("--abbr");
  expect(await readFile(path)).toEqual(bytes);
  expect((await stat(path)).mtimeMs).toBe(before.mtimeMs);
  expect((await stat(path)).ino).toBe(before.ino);
});

test("unconfirmed citekey, invalid metadata and invalid BibTeX fail before filesystem changes", async () => {
  await expect(createPaper(vault, metadata, { kind: "candidate", citekey: confirmed.citekey } as never, bibtex, ctx)).rejects.toMatchObject({ code: "UNCONFIRMED_CITEKEY" });
  await expect(createPaper(vault, { ...metadata, authors: [] }, confirmed, bibtex, ctx)).rejects.toMatchObject({ code: "INVALID_METADATA" });
  await expect(createPaper(vault, metadata, confirmed, "<html>error</html>", ctx)).rejects.toMatchObject({ code: "INVALID_BIBTEX" });
  expect(await readdir(vault)).toEqual([]);
});

test("cannot silently skip an existing malformed paper while checking identities", async () => {
  await mkdir(join(vault, "papers"));
  const bad = await readFile(new URL("../../../fixtures/sync-vault/ideas/坏文件.md", import.meta.url));
  await writeFile(join(vault, "papers/broken.md"), bad);
  await expect(createPaper(vault, metadata, confirmed, bibtex, ctx)).rejects.toMatchObject({ code: "DUPLICATE_CHECK_FAILED" });
  expect(await readdir(join(vault, "papers"))).toEqual(["broken.md"]);
  expect(await readFile(join(vault, "papers/broken.md"))).toEqual(bad);
});

test("concurrent new paper creation never replaces another complete note", async () => {
  const secondCtx: FillContext = { ...ctx, newId: (prefix) => `${prefix}_01J9Z3K8M2N4P6Q8R0S2T4V6W9` };
  const results = await Promise.allSettled([
    createPaper(vault, metadata, confirmed, bibtex, ctx),
    createPaper(vault, metadata, confirmed, bibtex, secondCtx),
  ]);
  expect(results.filter((result) => result.status === "fulfilled")).toHaveLength(1);
  const failure = results.find((result) => result.status === "rejected") as PromiseRejectedResult;
  expect(["CITEKEY_EXISTS", "DUPLICATE_PAPER"]).toContain(failure.reason.code);
  const winnerCtx = results[0]!.status === "fulfilled" ? ctx : secondCtx;
  const bytes = await readFile(join(vault, "papers/He_2020_LightGCN.md"));
  expect(bytes.equals(renderPaper(metadata, confirmed, bibtex, winnerCtx).content)).toBe(true);
  expect(Paper.safeParse(parseFrontmatter(bytes).data).success).toBe(true);
  expect(await readdir(join(vault, "papers"))).toEqual(["He_2020_LightGCN.md"]);
});
