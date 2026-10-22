import { randomBytes } from "node:crypto";
import { createInterface } from "node:readline/promises";
import { parseArgs } from "node:util";
import {
  createIdea, createPaper, newId, parseArxivMetadata,
  parseCrossrefMetadata, parsePaperInput, resolveVault,
} from "@lumio/core";
import { version } from "../package.json";
import { syncVault } from "./sync.ts";
import { selectCitekey } from "./paper-confirm.ts";
import { fetchPaperSource, type PaperFetcher } from "./paper-source.ts";

export interface CliOptions {
  fetcher?: PaperFetcher;
  log?: (line: string) => void;
  interactive?: boolean;
  ask?: (question: string) => Promise<string>;
}

export async function runCli(args: string[], options: CliOptions = {}): Promise<number> {
  const log = options.log ?? console.log;
  const { values, positionals } = parseArgs({
    args, allowPositionals: true, strict: true,
    options: {
      vault: { type: "string" }, "dry-run": { type: "boolean" },
      abbr: { type: "string" }, yes: { type: "boolean" },
    },
  });
  const sync = positionals.length === 1 && positionals[0] === "sync";
  const idea = positionals.length === 3 && positionals[0] === "new" && positionals[1] === "idea";
  const paper = positionals.length === 3 && positionals[0] === "new" && positionals[1] === "paper";
  if ((!sync && !idea && !paper) || (!sync && values["dry-run"] !== undefined)
    || (!paper && (values.abbr !== undefined || values.yes !== undefined))) {
    throw new Error("用法：lumio sync [--vault <路径>] [--dry-run]；lumio new idea <标题> [--vault <路径>]；lumio new paper <输入> [--vault <路径>] [--abbr <缩写>] [--yes]");
  }
  const root = resolveVault(values.vault, process.env.LUMIO_VAULT);
  const now = new Date();
  const ctx = {
    now, tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    newId: (prefix: Parameters<typeof newId>[0]) => newId(prefix, now, randomBytes),
  };
  if (paper) {
    const input = parsePaperInput(positionals[2]!);
    const interactive = options.interactive ?? Boolean(process.stdin.isTTY);
    if (!interactive && values.abbr === undefined && !values.yes) {
      throw new Error("标准输入不是终端，请使用 --abbr <缩写> 或 --yes");
    }
    const source = await fetchPaperSource(input, {
      version, fetcher: options.fetcher, contactEmail: process.env.LUMIO_CONTACT_EMAIL,
    });
    const metadata = source.kind === "arxiv" ? parseArxivMetadata(source.metadata) : parseCrossrefMetadata(source.metadata);
    if (input.kind === "arxiv" && metadata.arxiv !== input.id) throw new Error("arXiv API 返回的论文 ID 与输入不一致");
    if (input.kind === "doi") {
      if (metadata.doi && metadata.doi.toLowerCase() !== input.doi.toLowerCase()) throw new Error("Crossref 返回的 DOI 与输入不一致");
      metadata.doi ??= input.doi;
    }
    let readline: ReturnType<typeof createInterface> | undefined;
    try {
      const confirmed = await selectCitekey(metadata, {
        abbreviation: values.abbr, yes: values.yes, interactive, log,
        ask: options.ask ?? ((question) => {
          readline ??= createInterface({ input: process.stdin, output: process.stdout });
          return readline.question(question);
        }),
      });
      log(await createPaper(root, metadata, confirmed, source.bibtex, ctx));
      return 0;
    } finally { readline?.close(); }
  }
  if (idea) {
    log(await createIdea(root, positionals[2]!, ctx));
    return 0;
  }
  return syncVault(root, { dryRun: values["dry-run"], log });
}
