import { readFile } from "node:fs/promises";
import { Citekey, Paper } from "@lumio/schema";
import { rewriteBibtexKey } from "./bibtex.ts";
import { saveNewNote, type NewNote } from "./create.ts";
import { CoreError } from "./errors.ts";
import { fillMetadata, type FillContext } from "./fill.ts";
import { parseFrontmatter } from "./frontmatter.ts";
import { parsePaperInput } from "./paper-input.ts";
import type { PaperMetadata } from "./paper-metadata.ts";
import { scanVault } from "./vault.ts";

export function renderPaper(metadata: PaperMetadata, citekey: string, bibtex: string, ctx: FillContext): NewNote {
  if (!Citekey.safeParse(citekey).success) {
    throw new CoreError("INVALID_CITEKEY", "论文 citekey 不符合契约");
  }
  const original: Record<string, unknown> = {
    title: metadata.title, citekey, authors: metadata.authors, year: metadata.year,
  };
  for (const key of ["arxiv", "doi", "url", "venue"] as const) {
    if (metadata[key]) original[key] = metadata[key];
  }
  const { patch, issues } = fillMetadata({
    type: "paper", frontmatter: original, fileName: citekey,
    birthtime: ctx.now, mtime: ctx.now,
  }, ctx);
  const frontmatter = { ...original, ...patch };
  if (issues.length || !Paper.safeParse(frontmatter).success) throw new CoreError("INVALID_METADATA", "无法生成合法的论文元数据");
  const rewritten = rewriteBibtexKey(bibtex, citekey);
  const body = ["", "## 一句话", "", "## 我的笔记", "", "## 可以引用的点", "", "## 和我的研究的关系", "", "## BibTeX", "", "```bibtex", rewritten, "```", ""].join("\n");
  return { relativePath: `papers/${citekey}.md`, content: parseFrontmatter(body).render(frontmatter) };
}

function identity(value: unknown, kind: "arxiv" | "doi"): string | undefined {
  if (typeof value !== "string" || !value.trim()) return undefined;
  try {
    const parsed = parsePaperInput(value);
    if (parsed.kind !== kind) return undefined;
    return parsed.kind === "arxiv" ? parsed.id.toLowerCase() : parsed.doi.toLowerCase();
  } catch { return value.trim().toLowerCase(); }
}

export async function createPaper(vault: string, metadata: PaperMetadata, citekey: string, bibtex: string, ctx: FillContext): Promise<string> {
  let note = renderPaper(metadata, citekey, bibtex, ctx);
  const arxiv = identity(metadata.arxiv, "arxiv");
  const doi = identity(metadata.doi, "doi");
  async function checkDuplicate(): Promise<void> {
    for (const file of await scanVault(vault, ["paper"])) {
      let fm: Record<string, unknown>;
      try { fm = parseFrontmatter(await readFile(file.path)).data; }
      catch (cause) { throw new CoreError("DUPLICATE_CHECK_FAILED", `无法检查已有论文：${file.relativePath}，请先修复该文件`, { cause }); }
      if ((arxiv && identity(fm.arxiv, "arxiv") === arxiv) || (doi && identity(fm.doi, "doi") === doi)) {
        throw new CoreError("DUPLICATE_PAPER", `该论文已存在：${file.relativePath}`);
      }
    }
  }
  try {
    await checkDuplicate();
    for (const suffix of ["", ..."bcdefghijklmnopqrstuvwxyz"]) {
      if (suffix) note = renderPaper(metadata, citekey + suffix, bibtex, ctx);
      try { return await saveNewNote(vault, note); }
      catch (cause) {
        if (!(cause instanceof CoreError) || cause.code !== "FILE_EXISTS") throw cause;
        // A concurrent creator may have added this same paper. Recheck before
        // trying another suffix (including after the final possible collision).
        await checkDuplicate();
      }
    }
    throw new CoreError("CITEKEY_EXHAUSTED", `citekey ${citekey} 及后缀 b 到 z 已全部占用`);
  } catch (cause) {
    if (cause instanceof CoreError) throw cause;
    throw new CoreError("CREATE_FAILED", "无法创建论文笔记", { cause });
  }
}
