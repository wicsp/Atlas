import { describe, expect, test } from "bun:test";
import { z } from "zod";
import { CONTRACTS, Id, LinksResult, NewProposal, Proposal, SearchResult } from "../src/index.ts";

const U = "01J9Z3K8M2N4P6Q8R0S2T4V6W8";
const now = "2026-10-23T16:30:00+08:00";
const ref = { id: `pap_${U}`, type: "paper", title: "LightGCN", path: "papers/He_2020_LightGCN.md", citekey: "He_2020_LightGCN" };

describe("query contracts", () => {
  test("search result", () => {
    expect(SearchResult.parse({ query: "来源", hits: [{ note: ref, snippet: "…来源边界…" }], total: 1 }).total).toBe(1);
  });

  test("dangling links have no note; incoming links must resolve", () => {
    const parsed = LinksResult.parse({
      note: ref,
      outgoing: [{ source: "wikilink", target: "Missing_2020_X", dangling: true }],
      incoming: [{ source: "related", target: `pap_${U}`, dangling: false, note: { ...ref, citekey: undefined, type: "idea", id: `idea_${U}` } }],
    });
    expect(parsed.outgoing[0]?.note).toBeUndefined();
    expect(LinksResult.safeParse({ note: ref, outgoing: [], incoming: [{ source: "related", target: "x", dangling: true }] }).success).toBe(false);
  });

  test("query contracts are strict", () => {
    expect(SearchResult.safeParse({ query: "x", hits: [], total: 0, extra: 1 }).success).toBe(false);
  });
});

describe("proposal contracts", () => {
  const p = { id: `prop_${U}`, kind: "link", from: `idea_${U}`, to: `pap_${U}`, reason: "两者都讨论来源标记", author: "claude-code@mac", status: "pending", created: now };

  test("valid proposal", () => expect(Proposal.parse(p).status).toBe("pending"));
  test("proposal ids use the prop prefix", () => {
    expect(Proposal.safeParse({ ...p, id: `idea_${U}` }).success).toBe(false);
    expect(Id.safeParse(`prop_${U}`).success).toBe(true);
  });
  test("new proposal accepts only client fields", () => {
    expect(NewProposal.parse({ kind: "link", from: p.from, to: p.to, reason: p.reason })).toBeTruthy();
    expect(NewProposal.safeParse({ ...p }).success).toBe(false);
  });
  test("empty reason rejected", () => expect(Proposal.safeParse({ ...p, reason: "" }).success).toBe(false));
});

test("all P1 contracts export to JSON Schema", () => {
  for (const s of Object.values(CONTRACTS)) expect(() => z.toJSONSchema(s, { io: "input" })).not.toThrow();
});
