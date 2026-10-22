# 0003 以 JSON Schema 作为跨语言契约

- 状态：**Proposed**（依赖 0002）
- 日期：2026-10-22

## 背景
Rust、TS、Python 三种语言需要共享同一套实体与协议定义。

## 决定（提议）
- `schema/` 下的 JSON Schema（draft 2020-12）为唯一事实来源。
- 各语言类型通过 `just codegen` 生成：Rust 用 typify，TS 用 json-schema-to-zod，
  Python 用 datamodel-code-generator。生成代码不得手改。
- Hub 的 HTTP API 另外导出 OpenAPI，供 `packages/api-client` 生成客户端。

## 备选
以 Rust 类型为源头，用 schemars / ts-rs / specta 导出。好处是少一层；代价是契约被绑在
后端语言上，前端 agent 改契约必须改 Rust。

## 待验证
typify 对 `allOf` + `$ref` 组合、`oneOf` 的生成质量；三种生成器对同一 schema 的一致性。
