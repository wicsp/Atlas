#!/usr/bin/env bun
import { parseArgs } from "node:util";
import { resolveVault } from "@lumio/core";
import { syncVault } from "./sync.ts";

async function main(): Promise<number> {
  const { values, positionals } = parseArgs({
    args: process.argv.slice(2), allowPositionals: true, strict: true,
    options: { vault: { type: "string" }, "dry-run": { type: "boolean", default: false } },
  });
  if (positionals.length !== 1 || positionals[0] !== "sync") {
    throw new Error("用法：lumio sync [--vault <路径>] [--dry-run]");
  }
  const root = resolveVault(values.vault, process.env.LUMIO_VAULT);
  return syncVault(root, { dryRun: values["dry-run"] });
}

try { process.exitCode = await main(); }
catch (cause) {
  console.error(cause instanceof Error ? cause.message : "无法执行 sync");
  process.exitCode = 1;
}
