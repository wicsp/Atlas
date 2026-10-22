# schema/ — 契约（唯一事实来源）

JSON Schema（draft 2020-12）。Rust、TS、Python 的类型都从这里**生成**，不得手改生成结果。

- `common.json`：ID、时间戳、通用字段
- `entities/`：存在 vault 里的实体，对应 Markdown 文件的 YAML frontmatter
- `protocol/`：Hub ↔ Runtime 的 job 协议

修改流程：先写 ADR（Proposed）→ 人类批准 → 改 schema → `just codegen` → 两边修实现。

生成工具（待 ADR 0003 定稿）：Rust 用 `typify`，TS 用 `json-schema-to-zod`，Python 用 `datamodel-code-generator`。
