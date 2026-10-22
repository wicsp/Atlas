import { z } from "zod";
import { Assignee, Base, Timestamp, idOf, optional, withDefault } from "./common.ts";

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
  venue: optional(z.string()),
  arxiv: optional(z.string()),
  doi: optional(z.string()),
  url: optional(z.url()),
  status: withDefault(z.enum(["to-read", "reading", "read"]), "to-read"),
});

/** 想法 / 灵感，可以链接论文和其他想法，最后被串进报告。 */
export const Idea = Base.extend({
  type: z.literal("idea"),
  id: idOf("idea"),
  status: withDefault(z.enum(["seed", "developing", "used", "dropped"]), "seed"),
  project: optional(idOf("prj")),
});

export const Project = Base.extend({
  type: z.literal("project"),
  id: idOf("prj"),
  status: withDefault(z.enum(["planning", "active", "paused", "done"]), "planning"),
  goal: optional(z.string()),
  repo: optional(z.string()).describe("关联代码仓库的路径或 URL"),
  deadline: optional(Timestamp),
});

export const Task = Base.extend({
  type: z.literal("task"),
  id: idOf("task"),
  status: withDefault(z.enum(["todo", "doing", "blocked", "review", "done"]), "todo"),
  project: optional(idOf("prj")),
  assignee: withDefault(Assignee, "human"),
  due: optional(Timestamp),
  job: optional(idOf("job")).describe("派给 AI 时对应的 job"),
});

export const Experiment = Base.extend({
  type: z.literal("experiment"),
  id: idOf("exp"),
  project: idOf("prj"),
  status: withDefault(z.enum(["planned", "running", "done", "failed"]), "planned"),
  hypothesis: optional(z.string()),
  config_ref: optional(z.string()).describe("配置文件路径或 git commit"),
  device: optional(z.string()),
  metrics: optional(z.record(z.string(), z.number())),
  artifacts: optional(z.array(z.string())),
});

/** 任意 vault 实体，按 `type` 字段区分。 */
export const Entity = z.discriminatedUnion("type", [Paper, Idea, Project, Task, Experiment]);

export type Paper = z.infer<typeof Paper>;
export type Idea = z.infer<typeof Idea>;
export type Project = z.infer<typeof Project>;
export type Task = z.infer<typeof Task>;
export type Experiment = z.infer<typeof Experiment>;
export type Entity = z.infer<typeof Entity>;
