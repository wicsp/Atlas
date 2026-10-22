import { z } from "zod";

/** 每类实体的 ID 前缀。ID 形如 `pap_01J9Z3...`（前缀 + ULID）。 */
export const ID_PREFIXES = {
  paper: "pap",
  idea: "idea",
  project: "prj",
  task: "task",
  experiment: "exp",
  report: "rpt",
  job: "job",
} as const;

const ULID = "[0-9A-HJKMNP-TV-Z]{26}";
const ALL_PREFIXES = Object.values(ID_PREFIXES).join("|");

/** 任意实体的 ID。 */
export const Id = z
  .string()
  .regex(new RegExp(`^(${ALL_PREFIXES})_${ULID}$`), "ID 必须是 <前缀>_<ULID>")
  .describe("<前缀>_<ULID>，例如 pap_01J9Z3...");

/** 指定前缀的 ID，例如 `idOf("pap")` 只接受论文 ID。 */
export const idOf = (prefix: (typeof ID_PREFIXES)[keyof typeof ID_PREFIXES]) =>
  z.string().regex(new RegExp(`^${prefix}_${ULID}$`), `ID 必须是 ${prefix}_<ULID>`);

/** ISO 8601 时间，必须带时区。 */
export const Timestamp = z.iso.datetime({ offset: true });

/**
 * 所有 vault 实体共有的 frontmatter 字段。
 *
 * 用 looseObject：frontmatter 里可能有 Obsidian 或其他工具写入的额外字段，
 * 解析后再写回时必须原样保留，不能丢掉。
 */
export const Base = z.looseObject({
  schema_version: z.literal(1).default(1),
  id: Id,
  title: z.string().min(1),
  created: Timestamp,
  updated: Timestamp,
  tags: z.array(z.string()).default([]),
  related: z
    .array(Id)
    .default([])
    .describe("显式关联，由人维护（ADR 0006）；正文里的 [[链接]] 由 indexer 另行解析"),
});

export const AGENTS = ["claude-code", "codex", "pi"] as const;

/** 任务的负责人：`human` 表示自己，或指定某个 AI agent。 */
export const Assignee = z.union([
  z.literal("human"),
  z.strictObject({
    agent: z.enum(AGENTS),
    device: z.string().optional().describe("指定设备；省略则由调度决定"),
  }),
]);
