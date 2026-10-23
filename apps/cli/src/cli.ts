import { randomBytes } from "node:crypto";
import { parseArgs } from "node:util";
import {
  createIdea, createPaper, generateCitekey, newId, parseArxivMetadata,
  parseCrossrefMetadata, parsePaperInput, resolveVault,
} from "@lumio/core";
import { version } from "../package.json";
import { syncVault } from "./sync.ts";
import { fetchPaperSource, type PaperFetcher } from "./paper-source.ts";

export interface CliOptions {
  fetcher?: PaperFetcher;
  log?: (line: string) => void;
}

export async function runCli(args: string[], options: CliOptions = {}): Promise<number> {
  const log = options.log ?? console.log;
  const { values, positionals } = parseArgs({
    args, allowPositionals: true, strict: true,
    options: {
      vault: { type: "string" }, "dry-run": { type: "boolean" },
      abbr: { type: "string" },
    },
  });
  const sync = positionals.length === 1 && positionals[0] === "sync";
  const idea = positionals.length === 3 && positionals[0] === "new" && positionals[1] === "idea";
  const paper = positionals.length === 3 && positionals[0] === "new" && positionals[1] === "paper";
  if ((!sync && !idea && !paper) || (!sync && values["dry-run"] !== undefined)
    || (!paper && values.abbr !== undefined)) {
    throw new Error("用法：lumio sync [--vault <路径>] [--dry-run]；lumio new idea <标题> [--vault <路径>]；lumio new paper <输入> [--vault <路径>] [--abbr <缩写>]");
  }
  const root = resolveVault(values.vault, process.env.LUMIO_VAULT);
  const now = new Date();
  const ctx = {
    now, tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    newId: (prefix: Parameters<typeof newId>[0]) => newId(prefix, now, randomBytes),
  };
  if (paper) {
    const input = parsePaperInput(positionals[2]!);
    const source = await fetchPaperSource(input, {
      version, fetcher: options.fetcher, contactEmail: process.env.LUMIO_CONTACT_EMAIL,
    });
    const metadata = source.kind === "arxiv" ? parseArxivMetadata(source.metadata) : parseCrossrefMetadata(source.metadata);
    if (input.kind === "arxiv" && metadata.arxiv !== input.id) throw new Error("arXiv API 返回的论文 ID 与输入不一致");
    if (input.kind === "doi") {
      if (metadata.doi && metadata.doi.toLowerCase() !== input.doi.toLowerCase()) throw new Error("Crossref 返回的 DOI 与输入不一致");
      metadata.doi ??= input.doi;
    }
    log(await createPaper(root, metadata, generateCitekey(metadata, values.abbr), source.bibtex, ctx));
    return 0;
  }
  if (idea) {
    log(await createIdea(root, positionals[2]!, ctx));
    return 0;
  }
  return syncVault(root, { dryRun: values["dry-run"], log });
}
