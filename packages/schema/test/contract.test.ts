import { describe, expect, test } from "bun:test";
import { z } from "zod";
import { CITEKEY_PATTERN, CONTRACTS, Entity, Job, Paper, Task } from "../src/index.ts";

const ULID = "01J9Z3K8M2N4P6Q8R0S2T4V6W8";
const now = "2026-10-22T20:00:00+08:00";

const paper = {
  type: "paper",
  id: `pap_${ULID}`,
  title: "LightGCN: Simplifying and Powering Graph Convolution Network for Recommendation",
  created: now,
  updated: now,
  citekey: "He_2020_LightGCN",
  authors: ["Xiangnan He", "Kuan Deng"],
  year: 2020,
  arxiv: "2002.02126",
};

describe("citekey (ADR 0004)", () => {
  test.each(["He_2020_LightGCN", "VanDerMaaten_2008_tSNE", "He_2020_LightGCNb", "Vaswani_2017_Transformer"])(
    "accepts %s",
    (key) => expect(CITEKEY_PATTERN.test(key)).toBe(true),
  );

  test.each([
    "He:2020:LightGCN", // 旧的冒号格式
    "He-2020-LightGCN",
    "he_2020_LightGCN", // 姓必须大写开头
    "He_20_LightGCN", // 年份必须四位
    "Fernandez-Lopez_2019_X", // 姓里不能有连字符
    "He_2020_",
  ])("rejects %s", (key) => expect(CITEKEY_PATTERN.test(key)).toBe(false));
});

describe("Paper", () => {
  test("parses a minimal paper and fills defaults", () => {
    const parsed = Paper.parse(paper);
    expect(parsed.status).toBe("to-read");
    expect(parsed.tags).toEqual([]);
    expect(parsed.schema_version).toBe(1);
  });

  test("keeps unknown frontmatter fields so they survive a rewrite", () => {
    const parsed = Paper.parse({ ...paper, cssclasses: ["wide"], aliases: ["LightGCN"] });
    expect(parsed).toMatchObject({ cssclasses: ["wide"], aliases: ["LightGCN"] });
  });

  test("rejects an ID with the wrong prefix", () => {
    expect(Paper.safeParse({ ...paper, id: `idea_${ULID}` }).success).toBe(false);
  });

  test("rejects a timestamp without a time zone", () => {
    expect(Paper.safeParse({ ...paper, created: "2026-10-22T20:00:00" }).success).toBe(false);
  });
});

describe("Entity", () => {
  test("dispatches on type", () => {
    expect(Entity.parse(paper).type).toBe("paper");
  });
});

describe("Task assignee", () => {
  const task = { type: "task", id: `task_${ULID}`, title: "Read LightGCN", created: now, updated: now };

  test("defaults to human", () => {
    expect(Task.parse(task).assignee).toBe("human");
  });

  test("accepts an agent and rejects an unknown one", () => {
    expect(Task.parse({ ...task, assignee: { agent: "codex" } }).assignee).toEqual({ agent: "codex" });
    expect(Task.safeParse({ ...task, assignee: { agent: "gpt-9" } }).success).toBe(false);
  });
});

describe("Job", () => {
  test("rejects unknown fields (protocol is strict)", () => {
    const job = {
      protocol_version: 1,
      id: `job_${ULID}`,
      kind: "paper.ingest",
      requires: [],
      input: { arxiv: "2002.02126" },
      status: "queued",
      created: now,
    };
    expect(Job.parse(job).kind).toBe("paper.ingest");
    expect(Job.safeParse({ ...job, surprise: true }).success).toBe(false);
  });
});

describe("JSON Schema export", () => {
  test("every contract converts, and the citekey pattern survives", () => {
    for (const schema of Object.values(CONTRACTS)) {
      expect(() => z.toJSONSchema(schema, { io: "input" })).not.toThrow();
    }
    const json = z.toJSONSchema(Paper, { io: "input" }) as { properties: Record<string, { pattern?: string }> };
    expect(json.properties.citekey?.pattern).toBe(CITEKEY_PATTERN.source);
  });
});
