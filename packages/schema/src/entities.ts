import { z } from "zod";
import { Assignee, Base, Timestamp, idOf } from "./common.ts";

/**
 * 论文 citekey：`<第一作者姓>_<年份>_<标题缩写>`，例如 `He_2020_LightGCN`。
 * 同时是文件名、笔记链接和 `\cite{}` 的 key。规则见 ADR 0004。
 */
export const CITEKEY_PATTERN = /^[A-Z][A-Za-z]*_[0-9]{4}_[A-Za-z0-9]+$/;
export const Citekey = z
  .string()
  .regex(CITEKEY_PATTERN, "citekey 必须是 姓_年份_缩写，例如 He_2020_LightGCN");

/** 论文笔记，文件位于 `vault/papers/<citekey>.md`。 */
export const Paper = Base.extend({
  type: z.literal("paper"),
  id: idOf("pap"),
  citekey: Citekey,
  authors: z.array(z.string().min(1)).min(1),
  year: z.number().int(),
  venue: z.string().optional(),
  arxiv: z.string().optional(),
  doi: z.string().optional(),
  url: z.url().optional(),
  status: z.enum(["to-read", "reading", "read"]).default("to-read"),
});

/** 想法 / 灵感，可以链接论文和其他想法，最后被串进报告。 */
export const Idea = Base.extend({
  type: z.literal("idea"),
  id: idOf("idea"),
  status: z.enum(["seed", "developing", "used", "dropped"]).default("seed"),
  project: idOf("prj").optional(),
});

export const Project = Base.extend({
  type: z.literal("project"),
  id: idOf("prj"),
  status: z.enum(["planning", "active", "paused", "done"]).default("planning"),
  goal: z.string().optional(),
  repo: z.string().optional().describe("关联代码仓库的路径或 URL"),
  deadline: Timestamp.optional(),
});

export const Task = Base.extend({
  type: z.literal("task"),
  id: idOf("task"),
  status: z.enum(["todo", "doing", "blocked", "review", "done"]).default("todo"),
  project: idOf("prj").optional(),
  assignee: Assignee.default("human"),
  due: Timestamp.optional(),
  job: idOf("job").optional().describe("派给 AI 时对应的 job"),
});

export const Experiment = Base.extend({
  type: z.literal("experiment"),
  id: idOf("exp"),
  project: idOf("prj"),
  status: z.enum(["planned", "running", "done", "failed"]).default("planned"),
  hypothesis: z.string().optional(),
  config_ref: z.string().optional().describe("配置文件路径或 git commit"),
  device: z.string().optional(),
  metrics: z.record(z.string(), z.number()).optional(),
  artifacts: z.array(z.string()).optional(),
});

/** 任意 vault 实体，按 `type` 字段区分。 */
export const Entity = z.discriminatedUnion("type", [Paper, Idea, Project, Task, Experiment]);

export type Paper = z.infer<typeof Paper>;
export type Idea = z.infer<typeof Idea>;
export type Project = z.infer<typeof Project>;
export type Task = z.infer<typeof Task>;
export type Experiment = z.infer<typeof Experiment>;
export type Entity = z.infer<typeof Entity>;
