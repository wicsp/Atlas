import { lstat, readdir, stat } from "node:fs/promises";
import { join, relative } from "node:path";
import { CoreError } from "./errors.ts";
import type { EntityType } from "./fill.ts";

const DIRECTORIES = {
  papers: "paper", ideas: "idea", projects: "project", tasks: "task", experiments: "experiment",
} as const satisfies Record<string, EntityType>;

export interface VaultFile { path: string; relativePath: string; type: EntityType }

export function resolveVault(explicit: string | undefined, env: string | undefined): string {
  const path = explicit ?? env;
  if (!path) throw new CoreError("VAULT_REQUIRED", "请使用 --vault <路径> 或设置 LUMIO_VAULT");
  return path;
}

export async function scanVault(root: string): Promise<VaultFile[]> {
  const files: VaultFile[] = [];
  async function walk(dir: string, type: EntityType) {
    const entries = await readdir(dir, { withFileTypes: true });
    entries.sort((a, b) => a.name.localeCompare(b.name));
    for (const entry of entries) {
      if (entry.name.startsWith(".")) continue;
      const path = join(dir, entry.name);
      if (entry.isDirectory()) await walk(path, type);
      else if (entry.isFile() && entry.name.endsWith(".md")) files.push({ path, relativePath: relative(root, path), type });
    }
  }
  try {
    if (!(await stat(root)).isDirectory()) throw new Error("vault 路径不是目录");
    for (const [dir, type] of Object.entries(DIRECTORIES)) {
      const path = join(root, dir);
      let info;
      try { info = await lstat(path); }
      catch (cause) {
        if ((cause as NodeJS.ErrnoException).code === "ENOENT") continue;
        throw cause;
      }
      if (info.isDirectory()) await walk(path, type);
    }
    return files;
  } catch (cause) {
    throw new CoreError("VAULT_READ_FAILED", `无法扫描 vault：${root}`, { cause });
  }
}
