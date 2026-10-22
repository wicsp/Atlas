/**
 * 把 Zod 契约导出为 JSON Schema（draft 2020-12），写到 packages/schema/json/。
 * 供 Python SDK 等非 TS 使用方生成类型。输出是生成物，不入库、不得手改。
 *
 *   bun run schema:export
 */
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { z } from "zod";
import { CONTRACTS } from "../src/index.ts";

const outDir = join(import.meta.dir, "..", "json");
await mkdir(outDir, { recursive: true });

for (const [name, schema] of Object.entries(CONTRACTS)) {
  // io: "input" —— 带默认值的字段在输入端是可选的，这正是写 frontmatter 时的视角
  const json = z.toJSONSchema(schema, { target: "draft-2020-12", io: "input" });
  const file = join(outDir, `${name}.json`);
  await writeFile(file, `${JSON.stringify({ title: name, ...json }, null, 2)}\n`);
  console.log(`wrote ${file}`);
}
