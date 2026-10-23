import { afterEach, beforeEach, expect, test } from "bun:test";
import { mkdtemp, readFile, readdir, rm, stat } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseFrontmatter } from "@lumio/core";
import { Paper } from "@lumio/schema";
import { runCli, type CliOptions } from "../src/cli.ts";
import type { PaperFetcher } from "../src/paper-source.ts";

const fixture = (name: string) => readFile(new URL(`../../../fixtures/papers/${name}`, import.meta.url), "utf8");
const main = fileURLToPath(new URL("../src/main.ts", import.meta.url));
let vault: string;
beforeEach(async () => { vault = await mkdtemp(join(tmpdir(), "lumio-cli-paper-test-")); });
afterEach(async () => { await rm(vault, { recursive: true, force: true }); });

const fixtureFetcher: PaperFetcher = async (url) => {
  const parsed = new URL(url);
  if (parsed.origin === "https://export.arxiv.org") {
    return new Response(await fixture(`${parsed.searchParams.get("id_list")}.xml`));
  }
  if (parsed.origin === "https://arxiv.org" && parsed.pathname.startsWith("/bibtex/")) {
    return new Response(await fixture(`${parsed.pathname.slice(8)}.bib`));
  }
  if (parsed.origin === "https://api.crossref.org") return new Response(await fixture("crossref-lightgcn.json"));
  if (parsed.origin === "https://doi.org") return new Response(await fixture("crossref-lightgcn.bib"));
  throw new Error(`Network is disabled in this test: ${url}`);
};

async function run(args: string[], overrides: CliOptions = {}) {
  const output: string[] = [];
  const code = await runCli([...args, "--vault", vault], {
    fetcher: fixtureFetcher, interactive: false, log: (line) => output.push(line), ...overrides,
  });
  return { code, output };
}

test.each([
  ["2002.02126v2", "He_2020_LightGCN", "2002.02126"],
  ["https://arxiv.org/pdf/2403.14720v2.pdf", "Hines_2024_DAIP", "2403.14720"],
  ["arXiv:2406.13352", "Debenedetti_2024_AgentDojo", "2406.13352"],
  ["https://doi.org/10.1145/3397271.3401063", "He_2020_LightGCN", "doi"],
])("new paper %s passes Paper and sync writes nothing", async (input, citekey, identifier) => {
  const result = await run(["new", "paper", input, "--yes"]);
  expect(result).toEqual({ code: 0, output: [`papers/${citekey}.md`] });
  const path = join(vault, "papers", `${citekey}.md`);
  const bytes = await readFile(path);
  const parsed = parseFrontmatter(bytes);
  expect(Paper.safeParse(parsed.data).success).toBe(true);
  expect(parsed.data.citekey).toBe(citekey);
  if (identifier !== "doi") expect(parsed.data.arxiv).toBe(identifier);
  else expect(parsed.data.doi).toBe("10.1145/3397271.3401063");
  const before = await stat(path);
  expect(await run(["sync"])).toEqual({ code: 0, output: ["完成：扫描 1 个，补全 0 个，问题 0 个，跳过 0 个"] });
  expect(await readFile(path)).toEqual(bytes);
  expect((await stat(path)).mtimeMs).toBe(before.mtimeMs);
  expect((await stat(path)).ino).toBe(before.ino);
  expect(await readdir(vault)).toEqual(["papers"]);
});

test("--abbr explicitly confirms Spotlighting and changes only the abbreviation", async () => {
  expect(await run(["new", "paper", "2403.14720", "--abbr", "Spotlighting"])).toEqual({ code: 0, output: ["papers/Hines_2024_Spotlighting.md"] });
  const parsed = parseFrontmatter(await readFile(join(vault, "papers/Hines_2024_Spotlighting.md")));
  expect(parsed.body.toString()).toContain("@misc{Hines_2024_Spotlighting,");
});

test.each([
  ["arxiv", "2002.02126", "2002.02126v3", "--abbr", "Other", "已存在"],
  ["doi", "10.1145/3397271.3401063", "https://doi.org/10.1145/3397271.3401063", "--abbr", "Other", "已存在"],
  ["citekey", "2002.02126", "10.1145/3397271.3401063", "--abbr", "LightGCN", "--abbr"],
])("duplicate %s is rejected without overwriting any note", async (_kind, first, second, flag, abbreviation, message) => {
  await run(["new", "paper", first, "--yes"]);
  const files = await readdir(join(vault, "papers"));
  const path = join(vault, "papers", files[0]!);
  const bytes = await readFile(path);
  const before = await stat(path);
  await expect(run(["new", "paper", second, flag, abbreviation])).rejects.toThrow(message);
  expect(await readdir(join(vault, "papers"))).toEqual(files);
  expect(await readFile(path)).toEqual(bytes);
  expect((await stat(path)).mtimeMs).toBe(before.mtimeMs);
  expect((await stat(path)).ino).toBe(before.ino);
});

test("non-interactive input without flags fails before fetching or writing", async () => {
  let calls = 0;
  await expect(run(["new", "paper", "2002.02126"], { fetcher: async () => { calls++; throw new Error("must not fetch"); } })).rejects.toThrow("--abbr");
  expect(calls).toBe(0);
  expect(await readdir(vault)).toEqual([]);
  const proc = Bun.spawn([process.execPath, main, "new", "paper", "2002.02126", "--vault", vault], { stdin: "pipe", stdout: "pipe", stderr: "pipe" });
  proc.stdin.end();
  const [code, stderr] = await Promise.all([proc.exited, new Response(proc.stderr).text()]);
  expect(code).toBe(1);
  expect(stderr).toContain("标准输入不是终端");
  expect(stderr).toContain("--yes");
  expect(await readdir(vault)).toEqual([]);
});

test("interactive confirmation re-prompts invalid input; no file exists before confirmation", async () => {
  const answers = ["bad-hyphen", "Spotlighting"];
  const result = await run(["new", "paper", "2403.14720"], {
    interactive: true, ask: async (question) => {
      expect(question).toContain("citekey: Hines_2024_DAIP");
      expect(await readdir(vault)).toEqual([]);
      return answers.shift()!;
    },
  });
  expect(result.code).toBe(0);
  expect(result.output[0]).toContain("citekey 不合法");
  expect(result.output.at(-1)).toBe("papers/Hines_2024_Spotlighting.md");
});

test.each(["arXiv API", "arXiv BibTeX", "Crossref", "DOI BibTeX"])("source failure %s writes no files", async (source) => {
  const arxiv = source.startsWith("arXiv");
  const fetcher: PaperFetcher = async (url, init) => {
    const fail = (source === "arXiv API" && url.includes("export.arxiv"))
      || (source === "arXiv BibTeX" && url.includes("/bibtex/"))
      || (source === "Crossref" && url.includes("api.crossref"))
      || (source === "DOI BibTeX" && url.startsWith("https://doi.org/"));
    return fail ? new Response("unavailable", { status: 503 }) : fixtureFetcher(url, init);
  };
  await expect(run(["new", "paper", arxiv ? "2002.02126" : "10.1145/3397271.3401063", "--yes"], { fetcher })).rejects.toThrow(`${source} 请求失败`);
  expect(await readdir(vault)).toEqual([]);
});

test.each(["invalid XML", "wrong ID", "invalid BibTeX"])("bad source content (%s) writes no files", async (kind) => {
  const fetcher: PaperFetcher = async (url, init) => {
    if (url.includes("export.arxiv")) {
      if (kind === "invalid XML") return new Response("<feed><entry></feed>");
      if (kind === "wrong ID") return new Response(await fixture("2403.14720.xml"));
    } else if (kind === "invalid BibTeX") return new Response("<html>error</html>");
    return fixtureFetcher(url, init);
  };
  await expect(run(["new", "paper", "2002.02126", "--yes"], { fetcher })).rejects.toThrow();
  expect(await readdir(vault)).toEqual([]);
});

test("--yes with no candidate fails, explicit --abbr can supply the missing abbreviation", async () => {
  const xml = (await fixture("2002.02126.xml")).replace(/(<entry>[\s\S]*?<title>)[\s\S]*?(<\/title>)/, "$1---$2");
  const fetcher: PaperFetcher = (url, init) => url.includes("export.arxiv") ? Promise.resolve(new Response(xml)) : fixtureFetcher(url, init);
  await expect(run(["new", "paper", "2002.02126", "--yes"], { fetcher })).rejects.toThrow("无法生成 citekey 候选");
  expect(await readdir(vault)).toEqual([]);
  expect(await run(["new", "paper", "2002.02126", "--abbr", "Manual"], { fetcher })).toEqual({ code: 0, output: ["papers/He_2020_Manual.md"] });
});

test("invalid abbreviation and unsupported input are rejected without writes", async () => {
  await expect(run(["new", "paper", "2002.02126", "--abbr", "bad-hyphen"])).rejects.toThrow("citekey 不合法");
  await expect(run(["new", "paper", "unsupported", "--yes"])).rejects.toThrow("接受 arXiv");
  await expect(run(["new", "paper", "2002.02126", "--dry-run", "--yes"])).rejects.toThrow("用法");
  expect(await readdir(vault)).toEqual([]);
});
