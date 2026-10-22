import { lstat, readFile } from "node:fs/promises";
import { join } from "node:path";
import { Citekey, Paper } from "@lumio/schema";
import { rewriteBibtexKey } from "./bibtex.ts";
import type { ConfirmedCitekey } from "./citekey.ts";
import { saveNewNote, type NewNote } from "./create.ts";
import { CoreError } from "./errors.ts";
import { fillMetadata, type FillContext } from "./fill.ts";
import { parseFrontmatter } from "./frontmatter.ts";
import { parsePaperInput } from "./paper-input.ts";
import type { PaperMetadata } from "./paper-metadata.ts";
import { scanVault } from "./vault.ts";

export function renderPaper(metadata: PaperMetadata, confirmed: ConfirmedCitekey, bibtex: string, ctx: FillContext): NewNote {
  if (confirmed.kind !== "confirmed" || !Citekey.safeParse(confirmed.citekey).success) {
    throw new CoreError("UNCONFIRMED_CITEKEY", "必须先确认 citekey，才能创建论文笔记");
  }
  const original: Record<string, unknown> = {
    title: metadata.title, citekey: confirmed.citekey, authors: metadata.authors, year: metadata.year,
  };
  for (const key of ["arxiv", "doi", "url", "venue"] as const) {
    if (metadata[key]) original[key] = metadata[key];
  }
  const { patch, issues } = fillMetadata({
    type: "paper", frontmatter: original, fileName: confirmed.citekey,
    birthtime: ctx.now, mtime: ctx.now,
  }, ctx);
  const frontmatter = { ...original, ...patch };
  if (issues.length || !Paper.safeParse(frontmatter).success) throw new CoreError("INVALID_METADATA", "无法生成合法的论文元数据");
  const rewritten = rewriteBibtexKey(bibtex, confirmed.citekey);
  const body = ["", "## 一句话", "", "## 我的笔记", "", "## 可以引用的点", "", "## 和我的研究的关系", "", "## BibTeX", "", "```bibtex", rewritten, "```", ""].join("\n");
  return { relativePath: `papers/${confirmed.citekey}.md`, content: parseFrontmatter(body).render(frontmatter) };
}

function identity(value: unknown, kind: "arxiv" | "doi"): string | undefined {
  if (typeof value !== "string" || !value.trim()) return undefined;
  try {
    const parsed = parsePaperInput(value);
    if (parsed.kind !== kind) return undefined;
    return parsed.kind === "arxiv" ? parsed.id.toLowerCase() : parsed.doi.toLowerCase();
  } catch { return value.trim().toLowerCase(); }
}

export async function createPaper(vault: string, metadata: PaperMetadata, confirmed: ConfirmedCitekey, bibtex: string, ctx: FillContext): Promise<string> {
  const note = renderPaper(metadata, confirmed, bibtex, ctx);
  const path = join(vault, note.relativePath);
  try {
    try {
      await lstat(path);
      throw new CoreError("CITEKEY_EXISTS", `文件已存在：${path}；请使用 --abbr 换一个缩写，例如在末尾加 b`);
    } catch (cause) {
      if ((cause as NodeJS.ErrnoException).code !== "ENOENT") throw cause;
    }
    const arxiv = identity(metadata.arxiv, "arxiv");
    const doi = identity(metadata.doi, "doi");
    for (const file of await scanVault(vault, ["paper"])) {
      let fm: Record<string, unknown>;
      try { fm = parseFrontmatter(await readFile(file.path)).data; }
      catch (cause) { throw new CoreError("DUPLICATE_CHECK_FAILED", `无法检查已有论文：${file.relativePath}，请先修复该文件`, { cause }); }
      if ((arxiv && identity(fm.arxiv, "arxiv") === arxiv) || (doi && identity(fm.doi, "doi") === doi)) {
        throw new CoreError("DUPLICATE_PAPER", `该论文已存在：${file.relativePath}`);
      }
    }
    return await saveNewNote(vault, note);
  } catch (cause) {
    if (cause instanceof CoreError) {
      if (cause.code === "FILE_EXISTS") throw new CoreError("CITEKEY_EXISTS", `${cause.message}；请使用 --abbr 换一个缩写，例如在末尾加 b`, { cause });
      throw cause;
    }
    throw new CoreError("CREATE_FAILED", "无法创建论文笔记", { cause });
  }
}
