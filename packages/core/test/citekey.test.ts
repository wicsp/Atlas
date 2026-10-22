import { expect, test } from "bun:test";
import { CITEKEY_PATTERN } from "@lumio/schema";
import { confirmCitekey, proposeCitekey, type PaperMetadata } from "../src/index.ts";

const metadata: PaperMetadata = { title: "LightGCN: A model", authors: ["Xiangnan He"], year: 2020 };

test("a candidate is distinct from a user-confirmed citekey", () => {
  const candidate = proposeCitekey(metadata);
  expect(candidate).toEqual({ kind: "candidate", citekey: "He_2020_LightGCN", abbreviation: "LightGCN" });
  const confirmed = confirmCitekey(metadata, candidate!.abbreviation);
  expect(confirmed).toEqual({ kind: "confirmed", citekey: candidate!.citekey });
  expect(CITEKEY_PATTERN.test(confirmed.citekey)).toBe(true);
  expect(confirmCitekey(metadata, "LightGCNb").citekey).toBe("He_2020_LightGCNb");
});

test.each([
  ["Mislav Balunović", "Balunovic_2020_LightGCN"],
  ["A Müller", "Muller_2020_LightGCN"],
  ["A Fernández-López", "FernandezLopez_2020_LightGCN"],
  ["A O'Brien", "OBrien_2020_LightGCN"],
  ["Laurens van der Maaten", "Maaten_2020_LightGCN"],
])("arXiv full name %s uses the last word then ASCII normalization", (author, citekey) => {
  expect(proposeCitekey({ ...metadata, authors: [author] })?.citekey).toBe(citekey);
});

test("Crossref family takes precedence; only its first character is capitalized", () => {
  expect(proposeCitekey({ ...metadata, authors: ["Laurens van der Maaten"], firstAuthorFamily: "van der Maaten" })?.citekey)
    .toBe("VanderMaaten_2020_LightGCN");
});

test.each([
  ["van der Maaten", "VanderMaaten"],
  ["Fernández-López", "FernandezLopez"],
  ["O'Brien", "OBrien"],
])("Crossref family %s matches the accepted ADR 0004 example %s", (family, expected) => {
  expect(proposeCitekey({ ...metadata, firstAuthorFamily: family })?.citekey).toBe(`${expected}_2020_LightGCN`);
});

test("fallback takes four non-stopword initials; Spotlighting is not the first named word", () => {
  const result = proposeCitekey({ title: "Defending Against Indirect Prompt Injection Attacks With Spotlighting", authors: ["Keegan Hines"], year: 2024 });
  expect(result?.citekey).toBe("Hines_2024_DAIP");
  expect(proposeCitekey({ ...metadata, title: "A study of the graph and for with on in to model" })?.citekey).toBe("He_2020_SGM");
});

test("no candidate if it cannot match the contract; explicit abbreviation can fix only the abbreviation", () => {
  expect(proposeCitekey({ ...metadata, title: "---" })).toBeUndefined();
  expect(proposeCitekey({ ...metadata, authors: ["张三"] })).toBeUndefined();
  expect(proposeCitekey({ ...metadata, year: 20 })).toBeUndefined();
  expect(confirmCitekey({ ...metadata, title: "---" }, "Manual").citekey).toBe("He_2020_Manual");
  for (const abbr of ["", "not-valid", "two words", "中文", "Foo/../bar"]) {
    expect(() => confirmCitekey(metadata, abbr)).toThrow("citekey 不合法");
  }
});
