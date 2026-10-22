/**
 * @lumio/schema —— Lumio 的契约，唯一事实来源（ADR 0003）。
 *
 * 修改这里的任何导出都是契约变更：先写 ADR，人类批准后再改。
 * 其他语言使用 `bun run schema:export` 生成的 JSON Schema，不得手写对应类型。
 */
export * from "./common.ts";
export * from "./entities.ts";
export * from "./job.ts";

import { Experiment, Idea, Paper, Project, Task } from "./entities.ts";
import { Job } from "./job.ts";

/** 需要导出为 JSON Schema 的全部契约，键名即输出文件名。 */
export const CONTRACTS = {
  paper: Paper,
  idea: Idea,
  project: Project,
  task: Task,
  experiment: Experiment,
  job: Job,
} as const;
