import { z } from "zod";
import { Timestamp, idOf } from "./common.ts";

/**
 * Hub ↔ Runtime 的工作单元。Runtime 按 `requires` 里的能力领取 job，执行后回报结果。
 *
 * 这是 P0 的最小版本。ADR 0005 规定的 Attempt、fencing 编号与 `needs_attention`
 * 状态将在 P2 实现 Runtime 时通过新 ADR 补进来。
 */
export const JOB_PROTOCOL_VERSION = 1;

export const Job = z.strictObject({
  protocol_version: z.literal(JOB_PROTOCOL_VERSION),
  id: idOf("job"),
  kind: z
    .enum(["agent.run", "script.run", "paper.ingest"])
    .describe("agent.run：调用 coding agent；script.run：跑脚本或实验；paper.ingest：论文入库"),
  requires: z
    .array(z.string())
    .describe('Runtime 必须具备的能力，例如 ["agent:claude-code", "gpu"]'),
  input: z.record(z.string(), z.unknown()).describe("按 kind 解释；agent.run 至少包含 prompt 与 workspace"),
  status: z.enum(["queued", "claimed", "running", "succeeded", "failed", "cancelled"]),
  claimed_by: z.string().optional().describe("领取它的 Runtime 设备 ID"),
  result_ref: z.string().optional().describe("结果位置：vault 中的路径、git 分支或 PR"),
  error: z.string().optional(),
  source: idOf("task").optional().describe("触发它的 task"),
  created: Timestamp,
  started: Timestamp.optional(),
  finished: Timestamp.optional(),
});

export type Job = z.infer<typeof Job>;
