import { expect, test } from "bun:test";
import type { PaperMetadata } from "@lumio/core";
import { selectCitekey, type ConfirmOptions } from "../src/paper-confirm.ts";

const metadata: PaperMetadata = { title: "LightGCN: A model", authors: ["Xiangnan He"], year: 2020 };
const options: ConfirmOptions = {
  interactive: false, log: () => {}, ask: async () => { throw new Error("must not prompt"); },
};

test("explicit --abbr and --yes mark a citekey as confirmed without prompting", async () => {
  expect(await selectCitekey(metadata, { ...options, abbreviation: "LightGCNb" })).toEqual({ kind: "confirmed", citekey: "He_2020_LightGCNb" });
  expect(await selectCitekey(metadata, { ...options, yes: true })).toEqual({ kind: "confirmed", citekey: "He_2020_LightGCN" });
});

test("non-interactive input requires --abbr or --yes", async () => {
  await expect(selectCitekey(metadata, options)).rejects.toThrow("--abbr");
  await expect(selectCitekey(metadata, options)).rejects.toThrow("--yes");
});

test("interactive enter accepts candidate, new abbreviation changes only its last part", async () => {
  for (const [answer, expected] of [["", "He_2020_LightGCN"], ["  Custom42  ", "He_2020_Custom42"]]) {
    const result = await selectCitekey(metadata, { ...options, interactive: true, ask: async (question) => {
      expect(question).toContain("citekey: He_2020_LightGCN");
      expect(question).toContain("回车确认");
      return answer!;
    } });
    expect(result.citekey).toBe(expected!);
  }
});

test("interactive invalid abbreviations are rejected and re-prompted", async () => {
  const answers = ["bad-hyphen", "two words", "Custom"];
  const errors: string[] = [];
  const result = await selectCitekey(metadata, { ...options, interactive: true, log: (line) => errors.push(line), ask: async () => answers.shift()! });
  expect(result.citekey).toBe("He_2020_Custom");
  expect(errors).toHaveLength(2);
});

test("--yes rejects an absent candidate; explicit or interactive abbreviation can supply it", async () => {
  const paper = { ...metadata, title: "---" };
  await expect(selectCitekey(paper, { ...options, yes: true })).rejects.toThrow("无法生成 citekey 候选");
  expect((await selectCitekey(paper, { ...options, abbreviation: "Manual" })).citekey).toBe("He_2020_Manual");
  expect((await selectCitekey(paper, { ...options, interactive: true, ask: async () => "Manual" })).citekey).toBe("He_2020_Manual");
});
