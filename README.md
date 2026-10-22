# Atlas

个人研究工作台：论文笔记、想法、项目/任务、实验结果，以及在多台设备上给 AI 派活。

- 数据（笔记/论文/任务…）**不在本仓库**，放在独立的 vault 仓库里（Markdown + YAML frontmatter）。
- 本仓库只放代码：Rust 后端（Cargo workspace）+ TS 客户端（pnpm workspace），通过 `schema/` 对接。

先读：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) → [`AGENTS.md`](AGENTS.md) → [`docs/adr/`](docs/adr/)

## 目录

| 路径 | 内容 | 语言 |
|---|---|---|
| `schema/` | 契约：实体与 job 协议的 JSON Schema，唯一事实来源 | JSON |
| `crates/core` | vault 解析、链接、索引、BibTeX，纯本地逻辑 | Rust |
| `crates/cli` | `atlas` 命令行 | Rust |
| `crates/hub` | 服务器：HTTP API、job 队列、定时调度、MCP | Rust |
| `crates/runtime` | 每台设备上的 daemon，领取 job 并调用 agent | Rust |
| `packages/api-client` | 调 Hub 的 TS SDK（从 OpenAPI 生成） | TS |
| `apps/feishu-bot` | 飞书入口与通知 | TS |
| `apps/web` `apps/chrome-ext` `apps/mobile` | 后期客户端 | TS |
| `sdk/python` | 实验侧的薄客户端（后期） | Python |
| `infra/` | Docker / Nix（后期） | — |

## 开始

```sh
cargo check --workspace        # Rust 后端
corepack enable && pnpm install # TS 客户端
just check                      # 全部检查
```

## 当前阶段

P0：`schema` + `crates/core` + `crates/cli`，做到"arXiv/DOI 一键入库 → 笔记 + BibTeX"。
