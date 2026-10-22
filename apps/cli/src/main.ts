#!/usr/bin/env bun
import { randomBytes } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { basename } from "node:path";
import { parseArgs } from "node:util";
import { CoreError, fillMetadata, newId, parseFrontmatter, resolveVault, scanVault, writeFileAtomic } from "@lumio/core";

async function main(): Promise<number> {
  const { values, positionals } = parseArgs({
    args: process.argv.slice(2), allowPositionals: true, strict: true,
    options: { vault: { type: "string" }, "dry-run": { type: "boolean", default: false } },
  });
  if (positionals.length !== 1 || positionals[0] !== "sync") {
    throw new Error("用法：lumio sync [--vault <路径>] [--dry-run]");
  }
  const root = resolveVault(values.vault, process.env.LUMIO_VAULT);
  const files = await scanVault(root);
  const now = new Date();
  const ctx = {
    now, tz: Intl.DateTimeFormat().resolvedOptions().timeZone,
    newId: (prefix: Parameters<typeof newId>[0]) => newId(prefix, now, randomBytes),
  };
  let filled = 0, problems = 0, skipped = 0;
  for (const file of files) {
    try {
      const source = await readFile(file.path);
      const parsed = parseFrontmatter(source);
      const info = await stat(file.path);
      const { patch, issues } = fillMetadata({
        type: file.type, frontmatter: parsed.data, fileName: basename(file.path, ".md"),
        birthtime: info.birthtime, mtime: info.mtime,
      }, ctx);
      const keys = Object.keys(patch);
      if (keys.length) {
        const output = parsed.render(patch);
        if (!values["dry-run"]) await writeFileAtomic(file.path, output);
        filled++;
      }
      if (issues.length) problems++;
      const details = [
        ...keys.map((key) => `+${key}`),
        ...issues.map((issue) => `${issue.path}: ${issue.message}`),
      ];
      if (details.length) console.log(`${issues.length ? "问题" : "补全"}  ${file.relativePath}  ${details.join(" ")}`);
    } catch (cause) {
      skipped++;
      const message = cause instanceof CoreError ? cause.message : "无法读取或处理文件";
      console.log(`跳过  ${file.relativePath}  ${message}`);
    }
  }
  console.log(`完成：扫描 ${files.length} 个，补全 ${filled} 个，问题 ${problems} 个，跳过 ${skipped} 个`);
  return problems || skipped ? 1 : 0;
}

try { process.exitCode = await main(); }
catch (cause) {
  console.error(cause instanceof Error ? cause.message : "无法执行 sync");
  process.exitCode = 1;
}
