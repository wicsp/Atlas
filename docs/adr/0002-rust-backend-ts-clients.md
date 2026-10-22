# 0002 Rust 写后端，TS 写客户端

- 状态：**Proposed**（待研究后由人类决定）
- 日期：2026-10-22

## 背景
Runtime 需要部署在 Mac 与服务器上，未来考虑 Nix 打包；同时需要飞书 Bot、Chrome 插件、
Web、手机端。代码主要由 AI 编写，后端默认交给 GPT/Codex，前端默认交给 Claude。

## 决定（提议）
- `crates/`（core、cli、hub、runtime）用 Rust。
- `apps/` 与 `packages/` 用 TypeScript。
- 两侧只通过 `schema/` 与 Hub 的 HTTP API 对接，没有代码依赖。

## 后果
- 好处：Runtime/CLI 为单二进制，易分发、易用 Nix 打包；编译器是 AI 代码的护栏；
  语言边界即 AI 分工边界，不易漂移。
- 代价：起步比全 TS 慢；飞书无官方 Rust SDK（因此 Bot 用 TS）；无法直接嵌入 pi-agent-core
  （agent 本就以 CLI worker 方式调用，影响小）。

## 待研究
1. 契约跨语言共享方案（见 ADR 0003）
2. rmcp、rusqlite/sqlx 全文检索、frontmatter 解析库的成熟度
3. Tauri 2 能否覆盖桌面/手机端并复用 Rust core
4. Claude Code / Codex 在 Rust 项目中的迭代效率
5. 备选：全 TS，仅后期用 Rust 重写 Runtime
