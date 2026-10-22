import { expect, test } from "bun:test";
import { CoreError, parseFrontmatter } from "../src/index.ts";

test.each(["\n", "\r\n"])("body bytes, old formatting, comments and key order survive %j", (nl) => {
  const header = ["---", "# 注释", "title: '保持引号' # inline", "aliases: &a [甲, 乙]", "custom: *a", "related: [pap_01J9Z3K8M2N4P6Q8R0S2T4V6W8]", ""].join(nl);
  const body = Buffer.concat([Buffer.from(`${nl}中文 [[链接]]  ${nl}\`\`\`yaml${nl}---${nl}`), Buffer.from([0xff, 0, 10])]);
  const bytes = Buffer.concat([Buffer.from(header + "---" + nl), body]);
  const parsed = parseFrontmatter(bytes);
  const result = parsed.render({ id: "idea_01J9Z3K8M2N4P6Q8R0S2T4V6W8", updated: "2026-10-22T20:00:00+08:00" });
  expect(result.subarray(0, Buffer.byteLength(header))).toEqual(Buffer.from(header));
  const reread = parseFrontmatter(result);
  expect(reread.body).toEqual(body);
  expect(reread.data).toMatchObject({ ...parsed.data, id: "idea_01J9Z3K8M2N4P6Q8R0S2T4V6W8" });
  expect(Object.keys(reread.data)).toEqual([...Object.keys(parsed.data), "id", "updated"]);
  expect(parsed.render({})).toEqual(bytes);
});

test.each(["", "# 标题\n正文 [[链接]]\n", "--- horizontal rule without closing"])("creates frontmatter without changing body %j", (body) => {
  const parsed = parseFrontmatter(body);
  expect(parsed.data).toEqual({});
  expect(parseFrontmatter(parsed.render({ title: "new" })).body).toEqual(Buffer.from(body));
});

test.each(["id:\n", "id: # 保留注释\n", "id: null # 保留注释\n", "id: ~\n"])("fills empty ID safely: %j", (header) => {
  const result = parseFrontmatter(`---\n${header}title: old\n---\nbody`).render({ id: "idea_00000000000000000000000000", type: "idea" });
  expect(parseFrontmatter(result).data).toEqual({ id: "idea_00000000000000000000000000", title: "old", type: "idea" });
  if (header.includes("#")) expect(result.toString()).toContain("# 保留注释");
});

test.each(["{ title: old } # comment\n", "{ title: old, }\n", "{ title: old, # comment\n}\n", "{}\n", "  title: old\n", "title: old\n... # end\n", "# only comment\n"])("supports YAML mapping formatting %j", (header) => {
  const result = parseFrontmatter(`---\n${header}---\nbody`).render({ id: "idea_00000000000000000000000000" });
  expect(parseFrontmatter(result).data.id).toBe("idea_00000000000000000000000000");
  expect(parseFrontmatter(result).body.toString()).toBe("body");
  if (header.includes("title")) expect(result.toString()).toContain("title: old");
  if (header.includes("# comment")) expect(result.toString()).toContain("# comment");
});

test("keeps UTF-8 BOM and an EOF closing delimiter", () => {
  const result = parseFrontmatter("\ufeff---\r\ntitle: old\r\n---").render({ type: "idea" });
  expect(result.toString().startsWith("\ufeff---\r\ntitle: old\r\n")).toBe(true);
  expect(result.toString().endsWith("---")).toBe(true);
  expect(parseFrontmatter(result).body.length).toBe(0);
});

test.each(["---\ntitle: [broken\n---\nbody", "---\ntitle: a\ntitle: b\n---\nbody", "---\n- sequence\n---\n", "---\nscalar\n---\n", "---\nfoo: *missing\n---\n", "---\ntitle: no closing delimiter"])("invalid YAML produces a coded library error: %j", (source) => {
  try { parseFrontmatter(source); }
  catch (cause) { expect(cause).toBeInstanceOf(CoreError); expect(cause).toMatchObject({ code: "INVALID_FRONTMATTER" }); return; }
  throw new Error("expected parse error");
});

test("refuses to overwrite existing fields", () => {
  expect(() => parseFrontmatter("---\ntitle: old\n---\nbody").render({ title: "new" })).toThrow(CoreError);
});

test("refuses edits whose YAML tags or anchors would change existing values", () => {
  for (const header of ["id: !!null null\n", "id: &empty null\ncustom: *empty\n"]) {
    expect(() => parseFrontmatter(`---\n${header}---\nbody`).render({ id: "idea_00000000000000000000000000" }))
      .toThrow(CoreError);
  }
});
