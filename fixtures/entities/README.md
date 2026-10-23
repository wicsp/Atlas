# 实体样例（P0-5）

`cases.json` 是 source、post、asset 的 frontmatter 样例，供 `packages/schema` 的契约测试使用。
- `valid`：必须通过 `Entity` 校验，包括 ADR 0012 中的示例。
- `invalid`：必须被拒绝。`cardNumbers` 列出的样例含有测试用卡号（公开的测试号码），
  校验错误信息不得回显这些数字。

全部是合成数据，不对应任何真实的人或账户。
