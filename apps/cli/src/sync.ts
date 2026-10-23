import { randomBytes } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import { basename } from "node:path";
import { CoreError, fillMetadata, newId, parseFrontmatter, scanVault, writeFileAtomic } from "@lumio/core";

export interface SyncOptions {
  dryRun?: boolean;
  log?: (line: string) => void;
  writeFile?: typeof writeFileAtomic;
}

export async function syncVault(root: string, options: SyncOptions = {}): Promise<number> {
  const log = options.log ?? console.log;
  const writeFile = options.writeFile ?? writeFileAtomic;
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
        if (!options.dryRun) await writeFile(file.path, output, { expectedContent: source });
        filled++;
      }
      if (issues.length) problems++;
      const details = [
        ...keys.map((key) => `+${key}`),
        ...issues.map((issue) => `${issue.path}: ${issue.message}`),
      ];
      if (details.length) log(`${issues.length ? "问题" : "补全"}  ${file.relativePath}  ${details.join(" ")}`);
    } catch (cause) {
      skipped++;
      const message = cause instanceof CoreError ? cause.message : "无法读取或处理文件";
      log(`跳过  ${file.relativePath}  ${message}`);
    }
  }
  log(`完成：扫描 ${files.length} 个，补全 ${filled} 个，问题 ${problems} 个，跳过 ${skipped} 个`);
  return problems || skipped ? 1 : 0;
}
