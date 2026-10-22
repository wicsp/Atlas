# AGENTS.md — 所有 AI 共用的规则

本文件对 Claude Code、Codex 等所有编码 agent 生效。`CLAUDE.md` 只是引用本文件。

## 必读
开始任何任务前先读 `docs/ARCHITECTURE.md` 和 `docs/adr/` 里相关的条目。

## 硬规则
1. **契约不可私改**：`schema/` 是唯一事实来源。需要改它时，先在 `docs/adr/` 写一条
   状态为 `Proposed` 的 ADR，停下来等人类批准，批准后再改。生成的类型代码不得手改。
2. **依赖方向**
   - Rust：`cli` / `hub` / `runtime` → `core`。`core` 不依赖其他 crate，不做网络请求。
     `runtime` 与 `hub` 之间**不得互相依赖**，只通过 HTTP + job 协议通信。
   - TS：`apps/*` → `packages/*`。`packages/*` 不得依赖 `apps/*`；`apps/*` 之间不得互相 import。
   - Rust 与 TS 之间没有代码依赖，只通过 `schema/` 和 Hub 的 HTTP API 对接。
3. **一次只动一个 crate 或 package**，除非任务明确是契约变更的连带修改。
4. **新功能必须带测试**；契约相关行为要有契约测试（用 `schema/` 校验输入输出）。
5. **不引入新依赖**，除非在 PR 描述里写明理由和替代方案。
6. **不碰 vault 数据**：测试一律用 `fixtures/` 里的合成数据，不读写真实 vault。
7. **不在代码/配置里写真实密钥**，只用占位符（如 `${secret:openai}`），由运行时注入。

## 约定
- Rust：edition 2021，`cargo clippy -- -D warnings` 必须通过；库用 `thiserror`，二进制用 `anyhow`。
- TS：strict，ESM，Node ≥ 22。
- ID 格式：`<前缀>_<ULID>`，例如 `pap_01J...`。不要用文件名或标题当 ID。
- 时间一律 ISO 8601 带时区。
- 提交信息：`<crate 或 package>: <做了什么>`，例如 `core: parse paper frontmatter`。

## 分工
- `crates/*`：后端 agent（默认 Codex/GPT）。
- `apps/*`、`packages/*`：前端 agent（默认 Claude）。
- 交叉 review：一方写的 PR 由另一方 review，争议点标出来交给人类。

## 完成一项任务时
在回复里列出：改了哪些 crate/package、是否动了契约、新增了哪些依赖、怎么验证的。
