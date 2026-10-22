import { randomUUID } from "node:crypto";
import { open, readFile, rename, stat, unlink } from "node:fs/promises";
import { dirname, basename, join } from "node:path";
import { CoreError } from "./errors.ts";

/** Replace through a sibling temporary file; leave unchanged files untouched. */
export async function writeFileAtomic(path: string, content: Uint8Array): Promise<boolean> {
  let temp: string | undefined;
  try {
    let mode = 0o666;
    try {
      if ((await readFile(path)).equals(content)) return false;
      mode = (await stat(path)).mode & 0o777;
    } catch (cause) {
      if ((cause as NodeJS.ErrnoException).code !== "ENOENT") throw cause;
    }
    temp = join(dirname(path), `.${basename(path)}.${randomUUID()}.tmp`);
    const handle = await open(temp, "wx", mode);
    try { await handle.writeFile(content); }
    finally { await handle.close(); }
    await rename(temp, path);
    temp = undefined;
    return true;
  } catch (cause) {
    throw new CoreError("WRITE_FAILED", `无法安全写入文件：${path}`, { cause });
  } finally {
    if (temp) await unlink(temp).catch(() => {});
  }
}
