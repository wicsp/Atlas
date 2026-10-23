#!/usr/bin/env bun
import { randomBytes } from "node:crypto";
import { parseArgs } from "node:util";
import { createIdea, newId, resolveVault } from "@lumio/core";
import { syncVault } from "./sync.ts";

async function main(): Promise<number> {
  const { values, positionals } = parseArgs({
    args: process.argv.slice(2), allowPositionals: true, strict: true,
    options: { vault: { type: "string" }, "dry-run": { type: "boolean", default: false } },
  });
  const sync = positionals.length === 1 && positionals[0] === "sync";
  const idea = positionals.length === 3 && positionals[0] === "new" && positionals[1] === "idea";
  if ((!sync && !idea) || (idea && values["dry-run"])) {
    throw new Error("用法：lumio sync [--vault <路径>] [--dry-run] 或 lumio new idea <标题> [--vault <路径>]");
  }
  const root = resolveVault(values.vault, process.env.LUMIO_VAULT);
  if (idea) {
    const now = new Date();
    console.log(await createIdea(root, positionals[2]!, {
      now, tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
      newId: (prefix) => newId(prefix, now, randomBytes),
    }));
    return 0;
  }
  return syncVault(root, { dryRun: values["dry-run"] });
}

try { process.exitCode = await main(); }
catch (cause) {
  console.error(cause instanceof Error ? cause.message : "无法执行 sync");
  process.exitCode = 1;
}
