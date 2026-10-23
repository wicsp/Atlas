import { lstat, mkdir, stat } from "node:fs/promises";
import { join } from "node:path";
import { Idea } from "@lumio/schema";
import { CoreError } from "./errors.ts";
import { fillMetadata, type FillContext } from "./fill.ts";
import { parseFrontmatter } from "./frontmatter.ts";
import { entityDirectory, entityTypeOfPath, VAULT_LAYOUT } from "./vault.ts";
import { writeFileAtomic } from "./write.ts";

export interface NewNote { relativePath: string; content: Buffer }

export function renderIdea(title: string, ctx: FillContext): NewNote {
  if (!title.trim()) throw new CoreError("EMPTY_TITLE", "标题不能为空或只有空白");
  const fileName = title.replace(/[\\/:*?"<>|#^\[\]]/g, " ").replace(/\s+/gu, " ").trim();
  if (!fileName) throw new CoreError("INVALID_FILE_NAME", "标题替换非法字符后为空，无法生成文件名");
  const original = { title };
  const { patch, issues } = fillMetadata({
    type: "idea", frontmatter: original, fileName,
    birthtime: ctx.now, mtime: ctx.now,
  }, ctx);
  const frontmatter = { ...original, ...patch };
  if (issues.length || !Idea.safeParse(frontmatter).success) {
    throw new CoreError("INVALID_METADATA", "无法生成合法的想法元数据");
  }
  return { relativePath: `${entityDirectory("idea")}/${fileName}.md`, content: parseFrontmatter("\n").render(frontmatter) };
}

export async function saveNewNote(vault: string, note: NewNote): Promise<string> {
  try {
    const type = entityTypeOfPath(note.relativePath);
    const name = type && note.relativePath.slice(entityDirectory(type).length + 1);
    if (!type || !name || !/^[^/\\]+\.md$/.test(name)) {
      const dirs = VAULT_LAYOUT.map((e) => `${e.dir}/`).join("、");
      throw new CoreError("INVALID_NOTE_PATH", `新笔记必须直接位于类型目录内（${dirs}）`);
    }
    if (!(await stat(vault)).isDirectory()) throw new Error("vault 路径不是目录");
    const segments = note.relativePath.split("/");
    const path = join(vault, ...segments);
    // 逐级创建并检查：大类目录（如 research/）和类型目录都不能是符号链接，否则会写到 vault 之外。
    let directory = vault;
    for (const segment of segments.slice(0, -1)) {
      directory = join(directory, segment);
      try { await mkdir(directory); }
      catch (cause) { if ((cause as NodeJS.ErrnoException).code !== "EEXIST") throw cause; }
      if (!(await lstat(directory)).isDirectory()) throw new CoreError("INVALID_NOTE_DIRECTORY", "笔记目录不能是符号链接");
    }
    await writeFileAtomic(path, note.content, { overwrite: false });
    return note.relativePath;
  } catch (cause) {
    if (cause instanceof CoreError) throw cause;
    throw new CoreError("CREATE_FAILED", "无法创建笔记，请确认 vault 目录存在且可写", { cause });
  }
}

export async function createIdea(vault: string, title: string, ctx: FillContext): Promise<string> {
  return saveNewNote(vault, renderIdea(title, ctx));
}
